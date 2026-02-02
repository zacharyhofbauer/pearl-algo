"""
Pearl AI API Router - FastAPI endpoints for Pearl AI chat and feed.

Add to your FastAPI app:
    from pearl_ai.api_router import create_pearl_router
    app.include_router(create_pearl_router(brain), prefix="/api/pearl")
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .brain import PearlBrain, PearlMessage

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    message: str
    context: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    response: str
    timestamp: str
    complexity: str  # "quick" or "deep"


class FeedMessage(BaseModel):
    """A message in the Pearl feed."""
    id: str
    content: str
    type: str
    priority: str
    timestamp: str
    trade_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


def create_pearl_router(brain: PearlBrain) -> APIRouter:
    """
    Create the Pearl AI API router.

    Args:
        brain: The PearlBrain instance to use for AI operations

    Returns:
        FastAPI router with Pearl AI endpoints
    """
    router = APIRouter(tags=["Pearl AI"])

    # Store for WebSocket connections
    websocket_connections: List[WebSocket] = []

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
    async def chat(request: ChatRequest):
        """
        Send a message to Pearl AI and get a response.

        The AI will automatically determine whether to use local LLM (fast)
        or Claude (deep analysis) based on the complexity of the question.
        """
        try:
            response = await brain.chat(request.message)

            # Determine which LLM was used
            complexity = brain._classify_query(request.message).value

            return ChatResponse(
                response=response,
                timestamp=datetime.now().isoformat(),
                complexity=complexity,
            )

        except Exception as e:
            logger.error(f"Chat error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/feed", response_model=List[FeedMessage])
    async def get_feed(limit: int = 50):
        """
        Get recent Pearl AI messages (narrations, insights, alerts).

        Returns the most recent messages from Pearl's feed.
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
    async def feed_websocket(websocket: WebSocket):
        """
        WebSocket endpoint for real-time Pearl AI messages.

        Connect to receive live narrations, insights, and alerts as they happen.
        """
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
    async def generate_insight():
        """
        Trigger Pearl to generate a proactive insight.

        Useful for testing or forcing an insight generation.
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
    async def generate_daily_review():
        """
        Generate an end-of-day trading review.

        Provides a summary of the day's performance with coaching insights.
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
    async def get_status():
        """
        Get Pearl AI system status.

        Shows which LLM backends are available and configuration.
        """
        local_available = False
        claude_available = False

        if brain.local_llm:
            local_available = await brain.local_llm.is_available()

        if brain.claude_llm:
            claude_available = True  # Assume available if configured

        return {
            "local_llm": {
                "enabled": brain.local_llm is not None,
                "available": local_available,
                "model": brain.local_llm.model if brain.local_llm else None,
            },
            "claude": {
                "enabled": brain.claude_llm is not None,
                "model": brain.claude_llm.model if brain.claude_llm else None,
            },
            "memory": {
                "conversation_messages": len(brain.memory.conversation_history),
                "pearl_messages": len(brain.memory.pearl_messages),
                "patterns_learned": len(brain.memory.user_patterns),
            },
        }

    @router.get("/conversation")
    async def get_conversation(limit: int = 20):
        """
        Get recent conversation history.

        Returns the most recent user and assistant messages.
        """
        return brain.memory.get_recent_messages(limit)

    @router.delete("/conversation")
    async def clear_conversation():
        """
        Clear the current conversation history.

        Keeps learned patterns but clears the conversation context.
        """
        brain.memory.clear_session()
        return {"cleared": True}

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
