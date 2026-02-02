"""
Pearl AI API Router - FastAPI endpoints for Pearl AI chat and feed.

Add to your FastAPI app:
    from pearl_ai.api_router import create_pearl_router
    app.include_router(create_pearl_router(brain), prefix="/api/pearl")

Authentication:
    All endpoints require API key authentication when PEARL_API_AUTH_ENABLED=true.
    Pass the API key via X-API-Key header.

Pearl AI 3.0: Added /metrics and /chat/stream endpoints.
"""

import asyncio
import logging
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable, AsyncIterator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Security, Query
from fastapi.security import APIKeyHeader
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .brain import PearlBrain, PearlMessage

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    message: str
    context: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None  # I3.3: Session ID for chat persistence


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    response: str
    timestamp: str
    complexity: str  # "quick" or "deep"
    source: Optional[str] = None  # "cache", "local", "claude", "template" (P5.1)


class StreamChatRequest(BaseModel):
    """Request body for streaming chat endpoint."""
    message: str
    context: Optional[Dict[str, Any]] = None


class FeedMessage(BaseModel):
    """A message in the Pearl feed."""
    id: str
    content: str
    type: str
    priority: str
    timestamp: str
    trade_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


class MetricsSummary(BaseModel):
    """Metrics summary response."""
    period_hours: int
    total_requests: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    cache_hit_rate: float
    error_rate: float
    fallback_rate: float
    by_endpoint: Dict[str, Any]
    by_model: Dict[str, Any]
    cache: Optional[Dict[str, Any]] = None


class CostSummary(BaseModel):
    """Cost summary response."""
    today_usd: float
    month_usd: float
    limit_usd: Optional[float] = None


class SuggestionFeedbackRequest(BaseModel):
    """Request body for suggestion feedback endpoint (I3.1)."""
    suggestion_id: str
    action: str  # "accept" or "dismiss"
    dismiss_reason: Optional[str] = None  # "not_relevant", "wrong_timing", "too_risky", "other"
    dismiss_comment: Optional[str] = None  # Optional comment for "other" reason


def create_pearl_router(
    brain: PearlBrain,
    auth_dependency: Optional[Callable] = None,
) -> APIRouter:
    """
    Create the Pearl AI API router.

    Args:
        brain: The PearlBrain instance to use for AI operations
        auth_dependency: Optional authentication dependency to inject.
                        If None, uses built-in API key authentication.

    Returns:
        FastAPI router with Pearl AI endpoints
    """
    router = APIRouter(tags=["Pearl AI"])

    # Store for WebSocket connections
    websocket_connections: List[WebSocket] = []

    # ---------------------------------------------------------------------------
    # Authentication Setup
    # ---------------------------------------------------------------------------
    _auth_enabled = os.getenv("PEARL_API_AUTH_ENABLED", "true").lower() == "true"
    _api_keys: set = set()

    def _load_api_keys() -> set:
        """Load API keys from environment."""
        keys = set()
        env_key = os.getenv("PEARL_API_KEY")
        if env_key:
            keys.add(env_key.strip())

        # Load from file if specified
        key_file_path = os.getenv("PEARL_API_KEY_FILE")
        if key_file_path:
            from pathlib import Path
            key_file = Path(key_file_path)
            if key_file.exists():
                try:
                    for line in key_file.read_text().strip().split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#"):
                            keys.add(line)
                except Exception as e:
                    logger.warning(f"Failed to read API key file: {e}")
        return keys

    if _auth_enabled:
        _api_keys = _load_api_keys()
        if not _api_keys:
            logger.warning("[Pearl AI] Auth enabled but no API keys configured. "
                          "Set PEARL_API_KEY or PEARL_API_KEY_FILE.")

    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    async def verify_api_key(
        api_key: Optional[str] = Security(api_key_header),
    ) -> Optional[str]:
        """Verify API key from header."""
        if not _auth_enabled:
            return None
        if not api_key:
            raise HTTPException(status_code=401, detail="Missing API key. Provide X-API-Key header.")
        if api_key not in _api_keys:
            raise HTTPException(status_code=403, detail="Invalid API key.")
        return api_key

    # Use provided auth dependency or built-in
    auth_dep = auth_dependency if auth_dependency else verify_api_key

    # Register message handler to broadcast to WebSockets
    async def broadcast_message(message: PearlMessage):
        """Broadcast Pearl message to all connected WebSocket clients."""
        feed_msg = FeedMessage(
            id=f"pearl-{datetime.now().timestamp()}",
            content=message.content,
            type=message.message_type,
            priority=message.priority,
            timestamp=message.timestamp.isoformat(),
            trade_id=message.related_trade_id,
            metadata=message.metadata,
        )

        disconnected = []
        for ws in websocket_connections:
            try:
                await ws.send_json(feed_msg.model_dump())
            except Exception as e:
                logger.debug(f"WebSocket send error: {e}")
                disconnected.append(ws)

        # Clean up disconnected
        for ws in disconnected:
            if ws in websocket_connections:
                websocket_connections.remove(ws)

    brain.add_message_handler(broadcast_message)

    @router.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, _: Optional[str] = Depends(auth_dep)):
        """
        Send a message to Pearl AI and get a response.

        The AI will automatically determine whether to use local LLM (fast)
        or Claude (deep analysis) based on the complexity of the question.

        Requires X-API-Key header when authentication is enabled.
        """
        try:
            response = await brain.chat(request.message)

            # Determine which LLM was used
            complexity = brain._classify_query(request.message).value

            # Get response source (P5.1)
            source = brain.get_last_response_source()

            return ChatResponse(
                response=response,
                timestamp=datetime.now().isoformat(),
                complexity=complexity,
                source=source,
            )

        except Exception as e:
            logger.error(f"Chat error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/chat/stream")
    async def chat_stream(request: StreamChatRequest, _: Optional[str] = Depends(auth_dep)):
        """
        Send a message to Pearl AI and get a streaming response.

        Returns Server-Sent Events (SSE) with progressive text chunks.

        Requires X-API-Key header when authentication is enabled.
        """
        async def generate_stream() -> AsyncIterator[str]:
            """Generate SSE stream of response chunks."""
            try:
                # Send initial event
                yield f"data: {json.dumps({'type': 'start', 'timestamp': datetime.now().isoformat()})}\n\n"

                # Check if Claude LLM supports streaming
                if brain.claude_llm:
                    try:
                        # Build context
                        context = brain._build_chat_context(request.message)
                        rag_context = brain._get_rag_context(request.message)
                        if rag_context:
                            context["trade_history"] = rag_context

                        # Build prompts
                        system_prompt = brain._build_deep_system_prompt(context)
                        user_prompt = brain._build_deep_user_prompt(request.message, context)

                        # Stream response
                        full_response = ""
                        async for chunk in brain.claude_llm.generate_stream(
                            prompt=user_prompt,
                            system=system_prompt,
                            max_tokens=1000,
                        ):
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

                        # Store in memory
                        brain.memory.add_user_message(request.message)
                        brain.memory.add_assistant_message(full_response)

                        # Final event
                        yield f"data: {json.dumps({'type': 'done', 'timestamp': datetime.now().isoformat()})}\n\n"

                    except Exception as e:
                        logger.error(f"Streaming error: {e}")
                        # Fallback to non-streaming
                        response = await brain.chat(request.message)
                        yield f"data: {json.dumps({'type': 'chunk', 'content': response})}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'timestamp': datetime.now().isoformat()})}\n\n"

                else:
                    # No Claude LLM, use non-streaming response
                    response = await brain.chat(request.message)
                    yield f"data: {json.dumps({'type': 'chunk', 'content': response})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'timestamp': datetime.now().isoformat()})}\n\n"

            except Exception as e:
                logger.error(f"Stream generation error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )

    @router.get("/feed", response_model=List[FeedMessage])
    async def get_feed(limit: int = 50, _: Optional[str] = Depends(auth_dep)):
        """
        Get recent Pearl AI messages (narrations, insights, alerts).

        Returns the most recent messages from Pearl's feed.

        Requires X-API-Key header when authentication is enabled.
        """
        messages = brain.memory.pearl_messages[-limit:]

        return [
            FeedMessage(
                id=f"pearl-{i}",
                content=msg.content,
                type=msg.message_type,
                priority=msg.priority,
                timestamp=msg.timestamp.isoformat(),
                trade_id=msg.related_trade_id,
                metadata=msg.metadata,
            )
            for i, msg in enumerate(messages)
        ]

    @router.websocket("/feed/ws")
    async def feed_websocket(websocket: WebSocket, api_key: Optional[str] = Query(default=None)):
        """
        WebSocket endpoint for real-time Pearl AI messages.

        Connect to receive live narrations, insights, and alerts as they happen.

        Pass api_key as query parameter for authentication when enabled.
        """
        # Verify API key for WebSocket connections
        if _auth_enabled:
            if not api_key:
                await websocket.close(code=1008, reason="Missing API key")
                return
            if api_key not in _api_keys:
                await websocket.close(code=1008, reason="Invalid API key")
                return

        await websocket.accept()
        websocket_connections.append(websocket)
        logger.info(f"Pearl feed WebSocket connected. Total: {len(websocket_connections)}")

        try:
            # Send recent messages on connect
            recent = brain.memory.pearl_messages[-10:]
            for i, msg in enumerate(recent):
                await websocket.send_json({
                    "id": f"pearl-history-{i}",
                    "content": msg.content,
                    "type": msg.message_type,
                    "priority": msg.priority,
                    "timestamp": msg.timestamp.isoformat(),
                    "trade_id": msg.related_trade_id,
                    "metadata": msg.metadata,
                })

            # Keep connection alive
            while True:
                try:
                    # Wait for client messages (ping/pong or commands)
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30)

                    # Handle client commands
                    if data == "ping":
                        await websocket.send_text("pong")
                    elif data.startswith("chat:"):
                        # Allow chat via WebSocket too
                        message = data[5:]
                        response = await brain.chat(message)
                        await websocket.send_json({
                            "type": "chat_response",
                            "content": response,
                            "timestamp": datetime.now().isoformat(),
                        })

                except asyncio.TimeoutError:
                    # Send keepalive
                    await websocket.send_text("ping")

        except WebSocketDisconnect:
            logger.info("Pearl feed WebSocket disconnected")
        except Exception as e:
            logger.error(f"Pearl feed WebSocket error: {e}")
        finally:
            if websocket in websocket_connections:
                websocket_connections.remove(websocket)

    @router.post("/insight")
    async def generate_insight(_: Optional[str] = Depends(auth_dep)):
        """
        Trigger Pearl to generate a proactive insight.

        Useful for testing or forcing an insight generation.

        Requires X-API-Key header when authentication is enabled.
        """
        insight = await brain.generate_insight()

        if insight:
            return {
                "generated": True,
                "content": insight.content,
                "timestamp": insight.timestamp.isoformat(),
            }

        return {"generated": False, "reason": "No insight generated (cooldown or no data)"}

    @router.post("/daily-review")
    async def generate_daily_review(_: Optional[str] = Depends(auth_dep)):
        """
        Generate an end-of-day trading review.

        Provides a summary of the day's performance with coaching insights.

        Requires X-API-Key header when authentication is enabled.
        """
        review = await brain.daily_review()

        if review:
            return {
                "generated": True,
                "content": review.content,
                "timestamp": review.timestamp.isoformat(),
            }

        return {"generated": False, "reason": "Could not generate review (Claude unavailable?)"}

    @router.get("/status")
    async def get_status(_: Optional[str] = Depends(auth_dep)):
        """
        Get Pearl AI system status.

        Shows which LLM backends are available and configuration.

        Requires X-API-Key header when authentication is enabled.
        """
        local_available = False
        claude_available = False

        if brain.local_llm:
            local_available = await brain.local_llm.is_available()

        if brain.claude_llm:
            claude_available = True  # Assume available if configured

        return {
            "version": "3.0.0",
            "local_llm": {
                "enabled": brain.local_llm is not None,
                "available": local_available,
                "model": brain.local_llm.model if brain.local_llm else None,
            },
            "claude": {
                "enabled": brain.claude_llm is not None,
                "model": brain.claude_llm.model if brain.claude_llm else None,
            },
            "features": {
                "tools_enabled": brain.enable_tools,
                "caching_enabled": brain.cache is not None,
                "rag_enabled": brain.data_access.is_available(),
            },
            "memory": {
                "conversation_messages": len(brain.memory.conversation_history),
                "pearl_messages": len(brain.memory.pearl_messages),
                "patterns_learned": len(brain.memory.user_patterns),
                "session_id": brain.memory.session_id,
            },
        }

    @router.get("/conversation")
    async def get_conversation(limit: int = 20, _: Optional[str] = Depends(auth_dep)):
        """
        Get recent conversation history (I3.3).

        Returns the most recent user and assistant messages.
        Use this endpoint on page load to restore chat history.

        Requires X-API-Key header when authentication is enabled.
        """
        return {
            "session_id": brain.memory.session_id,
            "messages": brain.memory.get_recent_messages(limit),
        }

    @router.delete("/conversation")
    async def clear_conversation(_: Optional[str] = Depends(auth_dep)):
        """
        Clear the current conversation history.

        Keeps learned patterns but clears the conversation context.

        Requires X-API-Key header when authentication is enabled.
        """
        brain.memory.clear_session()
        return {"cleared": True}

    @router.get("/context")
    async def get_trading_context(_: Optional[str] = Depends(auth_dep)):
        """
        Get current trading context summary for UI display.

        Returns P&L, win/loss, regime, position info for chat state panel.

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.get_trading_context_summary()

    @router.get("/rejections")
    async def explain_rejections(_: Optional[str] = Depends(auth_dep)):
        """
        Get explanation of signal rejections today.

        Returns breakdown of why signals were rejected.

        Requires X-API-Key header when authentication is enabled.
        """
        explanation = brain.explain_rejections(brain._current_state)
        return {"explanation": explanation}

    # ================================================================
    # Pearl AI 3.0 Metrics Endpoints
    # ================================================================

    @router.get("/metrics", response_model=MetricsSummary)
    async def get_metrics(hours: int = 24, _: Optional[str] = Depends(auth_dep)):
        """
        Get Pearl AI usage metrics.

        Returns token counts, costs, latency percentiles, cache hit rates,
        and breakdown by endpoint and model.

        Args:
            hours: Number of hours to look back (default 24)

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.get_metrics_summary(hours)

    @router.get("/metrics/cost", response_model=CostSummary)
    async def get_cost(_: Optional[str] = Depends(auth_dep)):
        """
        Get Pearl AI cost summary.

        Returns today's cost, month's cost, and daily limit if set.

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.get_cost_summary()

    @router.get("/metrics/recent")
    async def get_recent_requests(limit: int = 20, _: Optional[str] = Depends(auth_dep)):
        """
        Get recent LLM requests for debugging.

        Returns the most recent requests with full details.

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.metrics.get_recent_requests(limit)

    @router.get("/metrics/errors")
    async def get_error_summary(hours: int = 24, _: Optional[str] = Depends(auth_dep)):
        """
        Get error summary by error type.

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.metrics.get_error_summary(hours)

    @router.post("/cache/clear")
    async def clear_cache(_: Optional[str] = Depends(auth_dep)):
        """
        Clear the response cache.

        Useful if responses seem stale or after configuration changes.

        Requires X-API-Key header when authentication is enabled.
        """
        if brain.cache:
            count = brain.cache.invalidate()
            return {"cleared": True, "entries_removed": count}
        return {"cleared": False, "reason": "Caching not enabled"}

    @router.get("/cache/stats")
    async def get_cache_stats(_: Optional[str] = Depends(auth_dep)):
        """
        Get cache statistics.

        Returns cache size, hit rate, and entry details.

        Requires X-API-Key header when authentication is enabled.
        """
        if brain.cache:
            return {
                "enabled": True,
                "stats": brain.cache.get_stats(),
                "entries": brain.cache.get_entries(),
            }
        return {"enabled": False}

    # ================================================================
    # Pearl AI Improvement Plan Endpoints (A2.2, A2.3)
    # ================================================================

    @router.get("/metrics/sources")
    async def get_response_sources(
        hours: Optional[int] = Query(default=None, description="Time window in hours (omit for all-time)"),
        _: Optional[str] = Depends(auth_dep)
    ):
        """
        Get response source distribution (A2.2).

        Returns breakdown of responses by source: cache, local, claude, template.
        Shows both counts and percentages.

        Args:
            hours: Optional time window. Omit for all-time statistics.

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.get_response_source_distribution(hours)

    @router.get("/ml-status")
    async def get_ml_status(_: Optional[str] = Depends(auth_dep)):
        """
        Get ML filter lift metrics (A2.3).

        Returns whether the ML filter is adding value:
        - pass_win_rate: Win rate of signals that passed
        - fail_win_rate: Win rate of signals that were blocked
        - lift_pct: Percentage improvement from ML
        - confidence: Statistical confidence level
        - sample_size: Number of samples

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.get_ml_lift_metrics()

    # ================================================================
    # SUGGESTION FEEDBACK ENDPOINTS (I3.1)
    # ================================================================

    @router.post("/feedback")
    async def record_feedback(
        request: SuggestionFeedbackRequest,
        _: Optional[str] = Depends(auth_dep)
    ):
        """
        Record user feedback on a suggestion (I3.1).

        Used to improve suggestion quality by tracking which suggestions
        are accepted vs dismissed, and the reasons for dismissal.

        Args:
            suggestion_id: Unique identifier for the suggestion
            action: "accept" or "dismiss"
            dismiss_reason: (optional) Reason for dismissal
                           Options: "not_relevant", "wrong_timing", "too_risky", "other"
            dismiss_comment: (optional) Additional comment for "other" reason

        Returns:
            Confirmation with updated feedback statistics

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.record_suggestion_feedback(
            suggestion_id=request.suggestion_id,
            action=request.action,
            dismiss_reason=request.dismiss_reason,
            dismiss_comment=request.dismiss_comment,
        )

    @router.get("/feedback/stats")
    async def get_feedback_stats(
        hours: Optional[int] = Query(default=None, description="Time window in hours (omit for all-time)"),
        _: Optional[str] = Depends(auth_dep)
    ):
        """
        Get suggestion feedback statistics (I3.1).

        Returns acceptance rate, dismiss reasons breakdown, and totals.

        Args:
            hours: Optional time window. Omit for all-time statistics.

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.metrics.get_feedback_stats(hours)

    @router.get("/feedback/recent")
    async def get_recent_feedback(
        limit: int = Query(default=20, le=100),
        _: Optional[str] = Depends(auth_dep)
    ):
        """
        Get recent feedback entries for debugging (I3.1).

        Requires X-API-Key header when authentication is enabled.
        """
        return brain.metrics.get_recent_feedback(limit)

    return router


# Standalone test server
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    # Create a test app
    app = FastAPI(title="Pearl AI Test Server")

    # Initialize brain (without LLMs for testing)
    test_brain = PearlBrain(enable_local=False, enable_claude=False)

    # Add router
    app.include_router(create_pearl_router(test_brain), prefix="/api/pearl")

    # Run
    uvicorn.run(app, host="0.0.0.0", port=8001)
