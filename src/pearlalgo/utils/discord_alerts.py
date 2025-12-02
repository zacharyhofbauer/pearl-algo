"""
Discord Alerts - Send notifications for trades and major events.
"""
from __future__ import annotations

import logging
from typing import Optional

import aiohttp
import logging

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class DiscordAlerts:
    """Discord webhook alert sender for trading notifications."""
    
    def __init__(
        self,
        webhook_url: str,
        enabled: bool = True,
    ):
        self.webhook_url = webhook_url
        self.enabled = enabled
        
        logger.info("Discord alerts initialized" if enabled else "Discord alerts disabled")
    
    async def send_message(
        self,
        content: str,
        embed: Optional[dict] = None,
    ) -> bool:
        """Send a message to Discord webhook."""
        if not self.enabled:
            return False
        
        try:
            payload = {"content": content}
            if embed:
                payload["embeds"] = [embed]
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status == 204:
                        return True
                    else:
                        logger.warning(f"Discord webhook returned status {response.status}")
                        return False
        
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
            return False
    
    async def notify_trade(
        self,
        symbol: str,
        side: str,
        size: int,
        price: float,
        order_id: Optional[str] = None,
    ) -> None:
        """Notify about a trade execution."""
        embed = {
            "title": "Trade Executed",
            "color": 0x00ff00 if side.upper() == "BUY" else 0xff0000,
            "fields": [
                {"name": "Symbol", "value": symbol, "inline": True},
                {"name": "Side", "value": side.upper(), "inline": True},
                {"name": "Size", "value": str(size), "inline": True},
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
            ],
        }
        if order_id:
            embed["fields"].append({"name": "Order ID", "value": order_id, "inline": False})
        
        await self.send_message("", embed=embed)
    
    async def notify_risk_warning(
        self,
        message: str,
        risk_status: Optional[str] = None,
    ) -> None:
        """Notify about a risk warning."""
        embed = {
            "title": "Risk Warning",
            "color": 0xffaa00,
            "description": message,
        }
        if risk_status:
            embed["fields"] = [{"name": "Risk Status", "value": risk_status, "inline": False}]
        
        await self.send_message("", embed=embed)
    
    async def notify_daily_summary(
        self,
        daily_pnl: float,
        total_trades: int,
        win_rate: Optional[float] = None,
    ) -> None:
        """Send daily trading summary."""
        color = 0x00ff00 if daily_pnl >= 0 else 0xff0000
        embed = {
            "title": "Daily Summary",
            "color": color,
            "fields": [
                {"name": "P&L", "value": f"${daily_pnl:,.2f}", "inline": True},
                {"name": "Trades", "value": str(total_trades), "inline": True},
            ],
        }
        if win_rate is not None:
            embed["fields"].append(
                {"name": "Win Rate", "value": f"{win_rate*100:.1f}%", "inline": True}
            )
        
        await self.send_message("", embed=embed)
    
    async def notify_kill_switch(self, reason: str) -> None:
        """Notify about kill-switch activation."""
        embed = {
            "title": "KILL-SWITCH ACTIVATED",
            "color": 0xff0000,
            "description": reason,
        }
        await self.send_message("", embed=embed)

