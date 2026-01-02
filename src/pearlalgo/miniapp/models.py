"""
Pydantic models for Mini App API responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health / Status
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    timestamp: datetime
    version: str = "1.0.0"


class DataQuality(BaseModel):
    """Data quality information."""
    level: str = Field(description="level1, historical, error, unknown")
    age_minutes: Optional[float] = None
    is_stale: bool = False
    explanation: Optional[str] = None


class GateStatus(BaseModel):
    """Market/session gate status."""
    futures_open: bool
    session_open: bool
    session_window: Optional[str] = None
    next_session: Optional[str] = None


class AgentStatus(BaseModel):
    """Agent status summary."""
    running: bool
    paused: bool = False
    pause_reason: Optional[str] = None
    gateway_running: bool = False
    last_cycle_seconds: Optional[float] = None
    activity_pulse: str = "unknown"  # active, slow, stale


class StatusResponse(BaseModel):
    """Full status response for terminal header."""
    symbol: str = "MNQ"
    price: Optional[float] = None
    price_change: Optional[str] = None
    sparkline: Optional[str] = None
    
    agent: AgentStatus
    gates: GateStatus
    data_quality: DataQuality
    
    scans_session: int = 0
    scans_total: int = 0
    signals_generated: int = 0
    signals_sent: int = 0
    active_trades: int = 0
    
    timestamp: datetime


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class SignalSummary(BaseModel):
    """Brief signal info for list view."""
    signal_id: str
    timestamp: datetime
    direction: str  # LONG, SHORT
    signal_type: str
    entry_price: float
    status: str  # generated, entered, exited, expired
    confidence: float
    pnl: Optional[float] = None


class SignalsResponse(BaseModel):
    """List of recent signals."""
    signals: List[SignalSummary]
    total: int


class SignalEvidence(BaseModel):
    """Evidence supporting a signal."""
    mtf_alignment: Optional[str] = None
    regime: Optional[str] = None
    vwap_location: Optional[str] = None
    pressure: Optional[str] = None
    additional: Dict[str, Any] = Field(default_factory=dict)


class SignalRisks(BaseModel):
    """Risk factors and invalidation conditions."""
    invalidation: Optional[str] = None
    key_levels: List[float] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ATSConstraints(BaseModel):
    """ATS (Automated Trading System) constraints."""
    armed: bool = False
    max_daily_loss: Optional[float] = None
    current_daily_pnl: Optional[float] = None
    session_allowed: bool = True
    position_size: Optional[int] = None
    risk_per_trade: Optional[float] = None


class MLView(BaseModel):
    """ML model diagnostics."""
    confidence: float
    confidence_tier: str  # Low, Moderate, High
    features: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: Optional[str] = None


class SignalDetail(BaseModel):
    """Full signal details for Decision Room."""
    signal_id: str
    timestamp: datetime
    symbol: str
    direction: str
    signal_type: str
    
    # Trade plan
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    position_size: Optional[int] = None
    risk_amount: Optional[float] = None
    
    # Status
    status: str
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    hold_duration_minutes: Optional[float] = None
    
    # Context
    confidence: float
    reason: Optional[str] = None


class DecisionRoomResponse(BaseModel):
    """Full Decision Room data for a signal."""
    signal: SignalDetail
    evidence: SignalEvidence
    risks: SignalRisks
    ats: ATSConstraints
    ml: MLView
    notes: List[str] = Field(default_factory=list)
    
    # Current market context
    current_price: Optional[float] = None
    data_quality: DataQuality


# ---------------------------------------------------------------------------
# OHLCV Data
# ---------------------------------------------------------------------------

class OHLCVBar(BaseModel):
    """Single OHLCV bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class OHLCVResponse(BaseModel):
    """OHLCV data for charting."""
    symbol: str
    timeframe: str
    bars: List[OHLCVBar]
    
    # Optional overlays
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    exit_price: Optional[float] = None


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

class NoteRequest(BaseModel):
    """Request to save a note."""
    signal_id: str
    note: str


class NoteResponse(BaseModel):
    """Response after saving a note."""
    success: bool
    signal_id: str
    note: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

class PerformanceResponse(BaseModel):
    """Performance metrics."""
    period: str = "7d"
    total_signals: int = 0
    exited_signals: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    
    recent_exits: List[SignalSummary] = Field(default_factory=list)




