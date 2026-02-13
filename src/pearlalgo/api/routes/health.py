"""
Health and market-status API routes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from pearlalgo.api.server_core import _get_market_status, _market, verify_api_key

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "market": _market}


@router.get("/api/market-status")
async def get_market_status(_key: Optional[str] = Depends(verify_api_key)):
    """Get current market open/closed status."""
    return _get_market_status()
