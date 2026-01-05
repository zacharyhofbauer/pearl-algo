"""
Mini App FastAPI Server

Serves the Decision Room terminal and JSON API endpoints.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from pearlalgo.utils.logger import logger

try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logger.error("FastAPI not installed. Run: pip install -e '.[miniapp]'")

from pearlalgo.miniapp.auth import AuthError, InitDataValidator, get_validator
from pearlalgo.miniapp.data import MiniAppDataProvider, get_data_provider
from pearlalgo.miniapp.models import (
    AgentStatus,
    ATSConstraints,
    DataQuality,
    DecisionRoomResponse,
    GateStatus,
    HealthResponse,
    MLView,
    NoteRequest,
    NoteResponse,
    OHLCVBar,
    OHLCVResponse,
    PerformanceResponse,
    SignalDetail,
    SignalEvidence,
    SignalRisks,
    SignalsResponse,
    SignalSummary,
    StatusResponse,
)


# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PearlAlgo Terminal",
    description="Decision Room Mini App API",
    version="1.0.0",
)

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_init_data_validator() -> InitDataValidator:
    """Get the initData validator (dependency injection point)."""
    return get_validator()


def get_provider() -> MiniAppDataProvider:
    """Get the data provider (dependency injection point)."""
    return get_data_provider()


async def require_auth(
    x_telegram_init_data: Annotated[Optional[str], Header()] = None,
) -> None:
    """
    Require valid Telegram initData for API access.
    
    Raises HTTPException 401 if auth fails.
    """
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Missing initData header")
    
    try:
        validator = get_init_data_validator()
        validator.validate(x_telegram_init_data)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.warning(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


# ---------------------------------------------------------------------------
# Static Files / Frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the Mini App frontend."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    else:
        # Return a placeholder if static files not yet created
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>PearlAlgo Terminal</title>
                <script src="https://telegram.org/js/telegram-web-app.js"></script>
                <style>
                    body { font-family: system-ui; padding: 20px; background: var(--tg-theme-bg-color, #1a1a1a); color: var(--tg-theme-text-color, #fff); }
                    h1 { color: var(--tg-theme-hint-color, #888); }
                </style>
            </head>
            <body>
                <h1>PearlAlgo Terminal</h1>
                <p>Decision Room Mini App is initializing...</p>
                <p>Static files will be served from: <code>src/pearlalgo/miniapp/static/</code></p>
                <script>
                    Telegram.WebApp.ready();
                    Telegram.WebApp.expand();
                </script>
            </body>
            </html>
            """,
            status_code=200,
        )


# Mount static files (CSS, JS, images) - only if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Health Check (no auth required)
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint (no auth required)."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc),
        version="1.0.0",
    )


# ---------------------------------------------------------------------------
# Status Endpoint
# ---------------------------------------------------------------------------

@app.get("/api/status", response_model=StatusResponse)
async def get_status(
    x_telegram_init_data: Annotated[Optional[str], Header()] = None,
):
    """Get current agent status for terminal header."""
    await require_auth(x_telegram_init_data)
    
    provider = get_provider()
    state = provider.get_state()
    
    # Agent status
    running = state.get("running", False)
    paused = state.get("paused", False)
    pause_reason = state.get("pause_reason")
    gateway_running = state.get("gateway_running", False)
    last_cycle = state.get("last_successful_cycle")
    
    # Calculate activity pulse
    last_cycle_seconds = None
    activity_pulse = "unknown"
    if last_cycle:
        try:
            if isinstance(last_cycle, str):
                last_cycle_dt = datetime.fromisoformat(last_cycle.replace("Z", "+00:00"))
            else:
                last_cycle_dt = last_cycle
            if last_cycle_dt.tzinfo is None:
                last_cycle_dt = last_cycle_dt.replace(tzinfo=timezone.utc)
            last_cycle_seconds = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
            
            if last_cycle_seconds < 120:
                activity_pulse = "active"
            elif last_cycle_seconds < 300:
                activity_pulse = "slow"
            else:
                activity_pulse = "stale"
        except Exception:
            pass
    
    agent = AgentStatus(
        running=running,
        paused=paused,
        pause_reason=pause_reason,
        gateway_running=gateway_running,
        last_cycle_seconds=last_cycle_seconds,
        activity_pulse=activity_pulse,
    )
    
    # Gates
    gates = GateStatus(
        futures_open=state.get("futures_market_open", False),
        session_open=state.get("strategy_session_open", False),
        session_window=state.get("session_window"),
        next_session=state.get("next_session"),
    )
    
    # Data quality
    level, age_minutes, is_stale, explanation = provider.get_data_quality()
    data_quality = DataQuality(
        level=level,
        age_minutes=age_minutes,
        is_stale=is_stale,
        explanation=explanation,
    )
    
    # Price info
    price = None
    price_change = None
    latest_bar = state.get("latest_bar")
    if latest_bar:
        price = latest_bar.get("close")
    
    # Activity counts
    scans_session = state.get("cycles_session", 0)
    scans_total = state.get("cycles_total", 0)
    signals_generated = state.get("signals_generated", 0)
    signals_sent = state.get("signals_sent", 0)
    active_trades = len(state.get("active_trades", []))
    
    return StatusResponse(
        symbol=state.get("symbol", "MNQ"),
        price=price,
        price_change=price_change,
        sparkline=state.get("sparkline"),
        agent=agent,
        gates=gates,
        data_quality=data_quality,
        scans_session=scans_session,
        scans_total=scans_total,
        signals_generated=signals_generated,
        signals_sent=signals_sent,
        active_trades=active_trades,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Signals Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/signals", response_model=SignalsResponse)
async def get_signals(
    x_telegram_init_data: Annotated[Optional[str], Header()] = None,
    limit: int = 20,
):
    """Get recent signals list."""
    await require_auth(x_telegram_init_data)
    
    provider = get_provider()
    raw_signals = provider.get_signals(limit=limit)
    
    signals = []
    for sig in raw_signals:
        try:
            # Parse timestamp
            ts = sig.get("timestamp")
            if isinstance(ts, str):
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                timestamp = ts or datetime.now(timezone.utc)
            
            summary = SignalSummary(
                signal_id=sig.get("signal_id", ""),
                timestamp=timestamp,
                direction=sig.get("direction", "").upper(),
                signal_type=sig.get("type", "unknown"),
                entry_price=sig.get("entry_price", 0),
                status=sig.get("status", "generated"),
                confidence=sig.get("confidence", 0),
                pnl=sig.get("pnl"),
            )
            signals.append(summary)
        except Exception as e:
            logger.warning(f"Could not parse signal: {e}")
            continue
    
    return SignalsResponse(
        signals=signals,
        total=len(raw_signals),
    )


@app.get("/api/signals/{signal_id}", response_model=SignalDetail)
async def get_signal_detail(
    signal_id: str,
    x_telegram_init_data: Annotated[Optional[str], Header()] = None,
):
    """Get detailed info for a specific signal."""
    await require_auth(x_telegram_init_data)
    
    provider = get_provider()
    sig = provider.get_signal_by_id(signal_id)
    
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    # Parse timestamp
    ts = sig.get("timestamp")
    if isinstance(ts, str):
        timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        timestamp = ts or datetime.now(timezone.utc)
    
    # Parse optional timestamps
    entry_time = None
    if sig.get("entry_time"):
        try:
            entry_time = datetime.fromisoformat(str(sig["entry_time"]).replace("Z", "+00:00"))
        except Exception:
            pass
    
    exit_time = None
    if sig.get("exit_time"):
        try:
            exit_time = datetime.fromisoformat(str(sig["exit_time"]).replace("Z", "+00:00"))
        except Exception:
            pass
    
    # Calculate risk/reward
    entry_price = sig.get("entry_price", 0)
    stop_loss = sig.get("stop_loss", 0)
    take_profit = sig.get("take_profit", 0)
    direction = sig.get("direction", "").upper()
    
    risk_reward = 0.0
    if direction == "LONG" and stop_loss > 0 and entry_price > stop_loss:
        risk = entry_price - stop_loss
        reward = take_profit - entry_price if take_profit > entry_price else 0
        risk_reward = reward / risk if risk > 0 else 0
    elif direction == "SHORT" and stop_loss > 0 and entry_price < stop_loss:
        risk = stop_loss - entry_price
        reward = entry_price - take_profit if take_profit < entry_price else 0
        risk_reward = reward / risk if risk > 0 else 0
    
    return SignalDetail(
        signal_id=sig.get("signal_id", ""),
        timestamp=timestamp,
        symbol=sig.get("symbol", "MNQ"),
        direction=direction,
        signal_type=sig.get("type", "unknown"),
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=round(risk_reward, 2),
        position_size=sig.get("position_size"),
        risk_amount=sig.get("risk_amount"),
        status=sig.get("status", "generated"),
        entry_time=entry_time,
        exit_time=exit_time,
        exit_price=sig.get("exit_price"),
        exit_reason=sig.get("exit_reason"),
        pnl=sig.get("pnl"),
        hold_duration_minutes=sig.get("hold_duration_minutes"),
        confidence=sig.get("confidence", 0),
        reason=sig.get("reason"),
    )


# ---------------------------------------------------------------------------
# Decision Room Endpoint
# ---------------------------------------------------------------------------

@app.get("/api/decision-room/{signal_id}", response_model=DecisionRoomResponse)
async def get_decision_room(
    signal_id: str,
    x_telegram_init_data: Annotated[Optional[str], Header()] = None,
):
    """Get full Decision Room data for a signal."""
    await require_auth(x_telegram_init_data)
    
    provider = get_provider()
    sig = provider.get_signal_by_id(signal_id)
    
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    # Build signal detail
    signal_detail_response = await get_signal_detail(signal_id, x_telegram_init_data)
    
    # Build evidence
    evidence_dict = provider.build_evidence(sig)
    evidence = SignalEvidence(**evidence_dict)
    
    # Build risks
    risks_dict = provider.build_risks(sig)
    risks = SignalRisks(**risks_dict)
    
    # Build ATS constraints
    ats_dict = provider.build_ats_constraints()
    ats = ATSConstraints(**ats_dict)
    
    # Build ML view
    ml_dict = provider.build_ml_view(sig)
    ml = MLView(**ml_dict)
    
    # Get notes
    notes = provider.get_notes(signal_id)
    
    # Current price
    state = provider.get_state()
    current_price = None
    latest_bar = state.get("latest_bar")
    if latest_bar:
        current_price = latest_bar.get("close")
    
    # Data quality
    level, age_minutes, is_stale, explanation = provider.get_data_quality()
    data_quality = DataQuality(
        level=level,
        age_minutes=age_minutes,
        is_stale=is_stale,
        explanation=explanation,
    )
    
    return DecisionRoomResponse(
        signal=signal_detail_response,
        evidence=evidence,
        risks=risks,
        ats=ats,
        ml=ml,
        notes=notes,
        current_price=current_price,
        data_quality=data_quality,
    )


# ---------------------------------------------------------------------------
# OHLCV Endpoint
# ---------------------------------------------------------------------------

@app.get("/api/ohlcv", response_model=OHLCVResponse)
async def get_ohlcv(
    x_telegram_init_data: Annotated[Optional[str], Header()] = None,
    lookback_hours: float = 12.0,
    signal_id: Optional[str] = None,
):
    """Get OHLCV data for charting."""
    await require_auth(x_telegram_init_data)
    
    provider = get_provider()
    raw_bars = provider.get_ohlcv(lookback_hours=lookback_hours)
    
    bars = []
    for bar in raw_bars:
        try:
            ts = bar.get("timestamp")
            if isinstance(ts, str):
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                timestamp = ts
            
            bars.append(OHLCVBar(
                timestamp=timestamp,
                open=bar.get("open", 0),
                high=bar.get("high", 0),
                low=bar.get("low", 0),
                close=bar.get("close", 0),
                volume=bar.get("volume", 0),
            ))
        except Exception:
            continue
    
    # Get signal overlay prices if signal_id provided
    entry_price = None
    stop_loss = None
    take_profit = None
    exit_price = None
    
    if signal_id:
        sig = provider.get_signal_by_id(signal_id)
        if sig:
            entry_price = sig.get("entry_price")
            stop_loss = sig.get("stop_loss")
            take_profit = sig.get("take_profit")
            exit_price = sig.get("exit_price")
    
    return OHLCVResponse(
        symbol="MNQ",
        timeframe="5m",
        bars=bars,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        exit_price=exit_price,
    )


# ---------------------------------------------------------------------------
# Notes Endpoint
# ---------------------------------------------------------------------------

@app.post("/api/notes", response_model=NoteResponse)
async def save_note(
    request: NoteRequest,
    x_telegram_init_data: Annotated[Optional[str], Header()] = None,
):
    """Save a note for a signal."""
    await require_auth(x_telegram_init_data)
    
    provider = get_provider()
    
    # Verify signal exists
    sig = provider.get_signal_by_id(request.signal_id)
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    # Save note
    success = provider.add_note(request.signal_id, request.note)
    
    return NoteResponse(
        success=success,
        signal_id=request.signal_id,
        note=request.note,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Performance Endpoint
# ---------------------------------------------------------------------------

@app.get("/api/performance", response_model=PerformanceResponse)
async def get_performance(
    x_telegram_init_data: Annotated[Optional[str], Header()] = None,
):
    """Get performance metrics."""
    await require_auth(x_telegram_init_data)
    
    provider = get_provider()
    perf = provider.get_performance()
    
    # Get recent exits for display
    signals = provider.get_signals(limit=20)
    recent_exits = []
    for sig in signals:
        if sig.get("status") == "exited":
            try:
                ts = sig.get("timestamp")
                if isinstance(ts, str):
                    timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    timestamp = ts or datetime.now(timezone.utc)
                
                recent_exits.append(SignalSummary(
                    signal_id=sig.get("signal_id", ""),
                    timestamp=timestamp,
                    direction=sig.get("direction", "").upper(),
                    signal_type=sig.get("type", "unknown"),
                    entry_price=sig.get("entry_price", 0),
                    status="exited",
                    confidence=sig.get("confidence", 0),
                    pnl=sig.get("pnl"),
                ))
            except Exception:
                continue
    
    return PerformanceResponse(
        period="7d",
        total_signals=perf.get("total_signals", 0),
        exited_signals=perf.get("exited_signals", 0),
        wins=perf.get("wins", 0),
        losses=perf.get("losses", 0),
        win_rate=perf.get("win_rate", 0.0),
        total_pnl=perf.get("total_pnl", 0.0),
        avg_pnl=perf.get("avg_pnl", 0.0),
        recent_exits=recent_exits[:5],
    )


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def main():
    """Run the Mini App server."""
    if not FASTAPI_AVAILABLE:
        print("❌ FastAPI not installed. Run: pip install -e '.[miniapp]'")
        return
    
    import uvicorn
    
    host = os.getenv("MINIAPP_HOST", "127.0.0.1")
    port = int(os.getenv("MINIAPP_PORT", "8080"))
    
    print(f"🚀 Starting PearlAlgo Terminal Mini App server...")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Static: {STATIC_DIR}")
    print()
    print(f"💡 Open in browser: http://{host}:{port}")
    print(f"💡 Health check: http://{host}:{port}/api/health")
    print()
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()





