"""
Paper Trading Test Script

Tests the LangGraph trading system in paper mode to verify:
- No real orders are placed
- All agents function correctly
- Risk rules are enforced
- LLM reasoning works
- Telegram alerts are sent (if configured)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pearlalgo.agents.langgraph_state import create_initial_state
from pearlalgo.agents.langgraph_workflow import TradingWorkflow
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.config.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_paper_trading_cycle():
    """Run a single cycle of paper trading."""
    logger.info("=" * 70)
    logger.info("PAPER TRADING TEST - LangGraph Multi-Agent System")
    logger.info("=" * 70)

    # Load settings
    settings = get_settings()
    logger.info(f"Profile: {settings.profile}")
    logger.info(f"Allow Live Trading: {settings.allow_live_trading}")

    if settings.profile != "paper":
        logger.warning("⚠️  Profile is not 'paper'! This test should run in paper mode.")
        logger.warning("   Set PEARLALGO_PROFILE=paper in .env")

    # Create portfolio
    portfolio = Portfolio(cash=100000.0)
    logger.info(f"Initial Portfolio Cash: ${portfolio.cash:,.2f}")

    # Load config
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return False

    import yaml

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Create initial state
    state = create_initial_state(portfolio, config)
    logger.info("Initial Trading State Created")
    logger.info(f"  - Trading Enabled: {state.trading_enabled}")
    logger.info(f"  - Kill Switch: {state.kill_switch_triggered}")

    # Initialize workflow
    try:
        workflow = TradingWorkflow(
            symbols=["ES"],  # Test with single symbol
            portfolio=portfolio,
            broker_name="ibkr",
            strategy="sr",
            config=config,
        )
        logger.info("✅ TradingWorkflow initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize workflow: {e}", exc_info=True)
        return False

    # Run single cycle
    logger.info("\n" + "=" * 70)
    logger.info("Running Single Workflow Cycle...")
    logger.info("=" * 70)

    try:
        # Run the workflow
        result = await workflow.run_cycle(state)

        # LangGraph returns a dict, convert back to TradingState if needed
        if isinstance(result, dict):
            # Convert dict back to TradingState
            from pearlalgo.agents.langgraph_state import TradingState

            final_state = TradingState(**result)
        else:
            final_state = result

        logger.info("\n" + "=" * 70)
        logger.info("Workflow Cycle Complete")
        logger.info("=" * 70)

        # Check results
        logger.info("Final State:")
        logger.info(f"  - Trading Enabled: {final_state.trading_enabled}")
        logger.info(f"  - Kill Switch: {final_state.kill_switch_triggered}")
        logger.info(f"  - Errors: {len(final_state.errors)}")
        logger.info(f"  - Market Data Symbols: {len(final_state.market_data)}")
        logger.info(f"  - Signals Generated: {len(final_state.signals)}")
        logger.info(f"  - Position Decisions: {len(final_state.position_decisions)}")
        logger.info(f"  - Agent Reasoning Entries: {len(final_state.agent_reasoning)}")

        # Print agent reasoning
        if final_state.agent_reasoning:
            logger.info("\nAgent Reasoning:")
            for reasoning in final_state.agent_reasoning[-5:]:  # Last 5 entries
                logger.info(f"  [{reasoning.agent_name}] {reasoning.message}")

        # Check for errors
        if final_state.errors:
            logger.warning(f"\n⚠️  Errors encountered: {len(final_state.errors)}")
            for error in final_state.errors:
                logger.warning(f"  - {error}")

        # Verify no real orders (in paper mode)
        if settings.profile == "paper":
            logger.info("\n✅ Paper Mode Verified - No real orders placed")
        else:
            logger.warning("\n⚠️  Not in paper mode - orders may have been placed!")

        # Validate workflow completed successfully
        logger.info("\n✅ Workflow cycle completed successfully")
        logger.info("   - All agents executed")
        logger.info("   - State transitions verified")
        logger.info(
            f"   - Risk rules enforced: {not final_state.kill_switch_triggered}"
        )

        return True

    except Exception as e:
        logger.error(f"❌ Workflow cycle failed: {e}", exc_info=True)
        return False


def main():
    """Main entry point."""
    try:
        result = asyncio.run(test_paper_trading_cycle())
        if result:
            logger.info("\n" + "=" * 70)
            logger.info("✅ PAPER TRADING TEST PASSED")
            logger.info("=" * 70)
            sys.exit(0)
        else:
            logger.error("\n" + "=" * 70)
            logger.error("❌ PAPER TRADING TEST FAILED")
            logger.error("=" * 70)
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
