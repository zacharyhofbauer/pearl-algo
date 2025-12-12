"""
Setup script for LangGraph Multi-Agent Trading System.

Helps users configure the system with environment variables and initial setup.
"""

import sys
from pathlib import Path


def create_env_template():
    """Create .env.example template if it doesn't exist."""
    env_example = Path(__file__).parent.parent / ".env.example"

    if env_example.exists():
        print(f"✓ .env.example already exists at {env_example}")
        return

    template = """# LangGraph Multi-Agent Trading System - Environment Variables
# Copy this file to .env and fill in your API keys

# IBKR Configuration (for futures)
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1
IBKR_DATA_CLIENT_ID=2

# Bybit Configuration (for crypto perps)
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_api_secret

# Alpaca Configuration (for US futures)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_API_SECRET=your_alpaca_api_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Data Providers
POLYGON_API_KEY=your_

# LLM Configuration
GROQ_API_KEY=your_groq_api_key
OPENAI_API_KEY=your_openai_api_key

# Alerts
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
DISCORD_WEBHOOK_URL=your_discord_webhook_url

# Trading Mode
PEARLALGO_PROFILE=paper
LIVE_STARTING_BALANCE=50000.0
"""

    env_example.write_text(template)
    print(f"✓ Created .env.example at {env_example}")


def check_config():
    """Check if config.yaml exists."""
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"

    if config_path.exists():
        print(f"✓ config.yaml exists at {config_path}")
        return True
    else:
        print(f"⚠ config.yaml not found at {config_path}")
        print("  Please create config/config.yaml (see config/config.yaml.example)")
        return False


def check_dependencies():
    """Check if required dependencies are installed."""
    required = [
        "langgraph",
        "langchain",
        "ccxt",
        "vectorbt",
        "streamlit",
        "groq",
        "loguru",
    ]

    missing = []
    for dep in required:
        try:
            if dep == "groq":
                __import__("groq")
            elif dep == "loguru":
                __import__("loguru")
            else:
                __import__(dep.replace("-", "_"))
            print(f"✓ {dep} installed")
        except ImportError:
            print(f"✗ {dep} NOT installed")
            missing.append(dep)

    if missing:
        print(f"\n⚠ Missing dependencies: {', '.join(missing)}")
        print("  Run: pip install -e .")
        return False

    return True


def main():
    """Main setup function."""
    print("=" * 60)
    print("LangGraph Multi-Agent Trading System - Setup")
    print("=" * 60)
    print()

    # Check Python version
    if sys.version_info < (3, 12):
        print(
            "⚠ Python 3.12+ required (current: {}.{})".format(
                sys.version_info.major, sys.version_info.minor
            )
        )
    else:
        print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor}")

    print()
    print("Checking dependencies...")
    deps_ok = check_dependencies()

    print()
    print("Checking configuration...")
    config_ok = check_config()

    print()
    print("Creating environment template...")
    create_env_template()

    print()
    print("=" * 60)
    if deps_ok and config_ok:
        print("✓ Setup complete! Next steps:")
        print("  1. Copy .env.example to .env and fill in API keys")
        print("  2. Edit config/config.yaml with your settings")
        print("  3. Run: python -m pearlalgo.live.langgraph_trader --mode paper")
    else:
        print("⚠ Setup incomplete. Please fix the issues above.")
    print("=" * 60)


if __name__ == "__main__":
    main()
