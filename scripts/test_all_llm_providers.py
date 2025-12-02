"""
Test All LLM Providers

Tests initialization and basic functionality of all 3 LLM providers:
- Groq
- OpenAI
- Anthropic
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv not installed, that's OK
    pass

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pearlalgo.agents.quant_research_agent import QuantResearchAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_provider(provider_name: str, api_key_env: str, model: str):
    """Test a single LLM provider."""
    logger.info(f"\n{'='*70}")
    logger.info(f"Testing {provider_name.upper()} Provider")
    logger.info(f"{'='*70}")
    
    api_key = os.getenv(api_key_env)
    
    if not api_key:
        logger.warning(f"⚠️  {api_key_env} not set - skipping {provider_name}")
        return False
    
    config = {
        "llm": {
            "provider": provider_name,
            provider_name: {
                "api_key": api_key,
                "model": model,
            },
        },
        "strategy": {"default": "sr"},
    }
    
    try:
        agent = QuantResearchAgent(
            symbols=["ES"],
            strategy="sr",
            config=config,
        )
        
        if agent.use_llm:
            logger.info(f"✅ {provider_name} initialized successfully")
            logger.info(f"   Model: {agent.llm_model}")
            return True
        else:
            logger.warning(f"⚠️  {provider_name} initialized but LLM disabled")
            return False
            
    except Exception as e:
        logger.error(f"❌ {provider_name} initialization failed: {e}")
        return False


async def test_llm_reasoning(provider_name: str, api_key_env: str, model: str):
    """Test LLM reasoning with a provider."""
    logger.info(f"\nTesting {provider_name} reasoning...")
    
    api_key = os.getenv(api_key_env)
    if not api_key:
        logger.warning(f"⚠️  {api_key_env} not set - skipping reasoning test")
        return False
    
    config = {
        "llm": {
            "provider": provider_name,
            provider_name: {
                "api_key": api_key,
                "model": model,
            },
        },
        "strategy": {"default": "sr"},
    }
    
    try:
        agent = QuantResearchAgent(
            symbols=["ES"],
            strategy="sr",
            config=config,
        )
        
        if not agent.use_llm:
            logger.warning(f"⚠️  LLM not enabled for {provider_name}")
            return False
        
        # Create mock signal data
        from datetime import datetime, timezone
        from pearlalgo.agents.langgraph_state import MarketData
        
        market_data = MarketData(
            symbol="ES",
            timestamp=datetime.now(timezone.utc),
            open=4500.0,
            high=4510.0,
            low=4495.0,
            close=4505.0,
            volume=1000.0,
        )
        
        signal_dict = {
            "side": "long",
            "strategy_name": "sr",
            "confidence": 0.75,
        }
        
        # Test reasoning (may fail if API key invalid, that's OK)
        try:
            reasoning = await agent._generate_llm_reasoning(
                symbol="ES",
                signal_dict=signal_dict,
                market_data=market_data,
                regime="trending",
            )
            
            if reasoning:
                logger.info(f"✅ {provider_name} reasoning generated")
                logger.info(f"   {reasoning[:100]}...")
                return True
            else:
                logger.warning(f"⚠️  {provider_name} returned no reasoning")
                return False
        except Exception as e:
            logger.warning(f"⚠️  {provider_name} reasoning failed: {e}")
            return False
            
    except Exception as e:
        logger.error(f"❌ {provider_name} reasoning test failed: {e}")
        return False


def main():
    """Test all LLM providers."""
    logger.info("=" * 70)
    logger.info("LLM Provider Testing")
    logger.info("=" * 70)
    
    results = {}
    
    # Test Groq - use current model from config
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    groq_model = config.get("llm", {}).get("groq", {}).get("model", "llama-3.1-70b-versatile")
    openai_model = config.get("llm", {}).get("openai", {}).get("model", "gpt-4o")
    anthropic_model = config.get("llm", {}).get("anthropic", {}).get("model", "claude-3-5-sonnet-20241022")
    
    results["groq"] = test_provider("groq", "GROQ_API_KEY", groq_model)
    results["openai"] = test_provider("openai", "OPENAI_API_KEY", openai_model)
    results["anthropic"] = test_provider("anthropic", "ANTHROPIC_API_KEY", anthropic_model)
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("Test Summary")
    logger.info("=" * 70)
    
    for provider, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{provider.upper()}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        logger.info("\n✅ All LLM providers working!")
    else:
        logger.warning("\n⚠️  Some LLM providers failed (check API keys)")
    
    # Test reasoning if providers initialized
    logger.info("\n" + "=" * 70)
    logger.info("Testing LLM Reasoning")
    logger.info("=" * 70)
    
    # Use models from config
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    groq_model = config.get("llm", {}).get("groq", {}).get("model", "llama-3.1-70b-versatile")
    openai_model = config.get("llm", {}).get("openai", {}).get("model", "gpt-4o")
    anthropic_model = config.get("llm", {}).get("anthropic", {}).get("model", "claude-3-5-sonnet-20241022")
    
    if results.get("groq"):
        asyncio.run(test_llm_reasoning("groq", "GROQ_API_KEY", groq_model))
    
    if results.get("openai"):
        asyncio.run(test_llm_reasoning("openai", "OPENAI_API_KEY", openai_model))
    
    if results.get("anthropic"):
        asyncio.run(test_llm_reasoning("anthropic", "ANTHROPIC_API_KEY", anthropic_model))


if __name__ == "__main__":
    main()

