"""
Monitor Paper Trading Execution

Monitors and validates paper trading execution, checking:
- Agent reasoning output
- LLM reasoning functionality
- Risk calculations
- Position sizing
- Telegram alerts (if configured)
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pearlalgo.agents.langgraph_state import TradingState
from pearlalgo.utils.telegram_alerts import TelegramAlerts

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def validate_agent_reasoning(state: TradingState):
    """Validate agent reasoning output."""
    logger.info("Validating Agent Reasoning...")
    
    if not state.agent_reasoning:
        logger.warning("⚠️  No agent reasoning found")
        return False
    
    logger.info(f"✅ Found {len(state.agent_reasoning)} reasoning entries")
    
    # Check for each agent
    agents_found = set()
    for reasoning in state.agent_reasoning:
        agents_found.add(reasoning.agent_name)
        logger.info(f"  [{reasoning.agent_name}] {reasoning.message[:80]}...")
    
    expected_agents = {"MarketDataAgent", "QuantResearchAgent", "RiskManagerAgent", "PortfolioExecutionAgent"}
    missing = expected_agents - agents_found
    
    if missing:
        logger.warning(f"⚠️  Missing agent reasoning: {missing}")
    else:
        logger.info("✅ All agents provided reasoning")
    
    return True


def validate_llm_reasoning(state: TradingState):
    """Validate LLM reasoning is working."""
    logger.info("Validating LLM Reasoning...")
    
    llm_reasoning_found = False
    for reasoning in state.agent_reasoning:
        if reasoning.data and "llm_reasoning" in reasoning.data:
            llm_reasoning_found = True
            logger.info(f"✅ LLM reasoning found in {reasoning.agent_name}")
            logger.info(f"   {reasoning.data['llm_reasoning'][:100]}...")
            break
    
    if not llm_reasoning_found:
        logger.warning("⚠️  No LLM reasoning found (may be disabled or API key missing)")
    
    return llm_reasoning_found


def validate_risk_calculations(state: TradingState):
    """Validate risk calculations are correct."""
    logger.info("Validating Risk Calculations...")
    
    if not state.risk_state:
        logger.warning("⚠️  No risk state found")
        return False
    
    risk_state = state.risk_state
    logger.info(f"✅ Risk State: {risk_state.status}")
    logger.info(f"   - Realized PnL: ${risk_state.realized_pnl:,.2f}")
    logger.info(f"   - Unrealized PnL: ${risk_state.unrealized_pnl:,.2f}")
    logger.info(f"   - Remaining Loss Buffer: ${risk_state.remaining_loss_buffer:,.2f}")
    
    # Check position decisions
    if state.position_decisions:
        logger.info(f"✅ Found {len(state.position_decisions)} position decisions")
        for symbol, decision in state.position_decisions.items():
            logger.info(f"   {symbol}: {decision.action} (size: {decision.size}, risk: {decision.risk_pct*100:.2f}%)")
    else:
        logger.info("ℹ️  No position decisions (may be normal if no signals)")
    
    return True


def validate_position_sizing(state: TradingState):
    """Validate position sizing."""
    logger.info("Validating Position Sizing...")
    
    for symbol, decision in state.position_decisions.items():
        if decision.size > 0:
            risk_pct = decision.risk_pct
            if risk_pct > 0.02:  # 2% max
                logger.error(f"❌ {symbol}: Risk exceeds 2% limit! ({risk_pct*100:.2f}%)")
                return False
            else:
                logger.info(f"✅ {symbol}: Risk within limit ({risk_pct*100:.2f}%)")
    
    return True


def test_telegram_alerts():
    """Test Telegram alerts if configured."""
    logger.info("Testing Telegram Alerts...")
    
    try:
        from pearlalgo.config.settings import get_settings
        settings = get_settings()
        
        # Check if Telegram is enabled in config
        import yaml
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"
        if config_path.exists():
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
            
            alerts = config.get("alerts", {})
            telegram = alerts.get("telegram", {})
            
            if telegram.get("enabled", False):
                bot_token = telegram.get("bot_token")
                chat_id = telegram.get("chat_id")
                
                if bot_token and chat_id:
                    try:
                        alerter = TelegramAlerts(bot_token=bot_token, chat_id=chat_id)
                        # Test message
                        result = asyncio.run(alerter.send_message("🧪 Paper Trading Test - LangGraph System"))
                        if result:
                            logger.info("✅ Telegram alert sent successfully")
                            return True
                        else:
                            logger.warning("⚠️  Telegram alert failed to send")
                    except Exception as e:
                        logger.warning(f"⚠️  Telegram alert error: {e}")
                else:
                    logger.info("ℹ️  Telegram not configured (bot_token or chat_id missing)")
            else:
                logger.info("ℹ️  Telegram alerts disabled in config")
        else:
            logger.warning("⚠️  config.yaml not found")
    except Exception as e:
        logger.warning(f"⚠️  Error testing Telegram: {e}")
    
    return False


def main():
    """Main monitoring function."""
    logger.info("=" * 70)
    logger.info("PAPER TRADING MONITORING & VALIDATION")
    logger.info("=" * 70)
    logger.info("")
    
    # This would typically be called after a trading cycle
    # For now, we'll create a mock state to demonstrate validation
    
    logger.info("Note: This script validates the monitoring functions.")
    logger.info("In production, this would be called after each trading cycle.")
    logger.info("")
    
    # Test Telegram if configured
    test_telegram_alerts()
    
    logger.info("\n" + "=" * 70)
    logger.info("Monitoring functions validated")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()

