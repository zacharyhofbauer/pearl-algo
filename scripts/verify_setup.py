"""
Verify System Setup

Verifies that all components are properly configured and ready to run.
"""

from __future__ import annotations

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

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def check_file_exists(path: str, description: str) -> bool:
    """Check if a file exists."""
    if Path(path).exists():
        print(f"✅ {description}: {path}")
        return True
    else:
        print(f"❌ {description}: {path} - NOT FOUND")
        return False


def check_env_var(var: str, description: str, required: bool = False) -> bool:
    """Check if environment variable is set."""
    value = os.getenv(var)
    if value:
        masked = value[:10] + "..." if len(value) > 10 else value
        print(f"✅ {description}: {var} = {masked}")
        return True
    else:
        if required:
            print(f"❌ {description}: {var} - REQUIRED BUT NOT SET")
        else:
            print(f"⚠️  {description}: {var} - Not set (optional)")
        return not required


def check_python_import(module: str, description: str) -> bool:
    """Check if a Python module can be imported."""
    try:
        __import__(module)
        print(f"✅ {description}: {module}")
        return True
    except ImportError:
        print(f"❌ {description}: {module} - NOT INSTALLED")
        return False


def main():
    """Main verification function."""
    print("=" * 70)
    print("System Setup Verification")
    print("=" * 70)
    print()

    all_ok = True

    # Check configuration files
    print("Configuration Files:")
    print("-" * 70)
    all_ok &= check_file_exists("config/config.yaml", "Main config")
    all_ok &= check_file_exists(".env", "Environment variables")
    print()

    # Check required environment variables
    print("Required Environment Variables:")
    print("-" * 70)
    all_ok &= check_env_var("IBKR_HOST", "IBKR Host", required=True)
    all_ok &= check_env_var("IBKR_PORT", "IBKR Port", required=True)
    all_ok &= check_env_var("PEARLALGO_PROFILE", "Trading Profile", required=True)
    print()

    # Check optional environment variables
    print("Optional Environment Variables (LLM Providers):")
    print("-" * 70)
    check_env_var("GROQ_API_KEY", "Groq API Key")
    check_env_var("OPENAI_API_KEY", "OpenAI API Key")
    check_env_var("ANTHROPIC_API_KEY", "Anthropic API Key")
    print()

    print("Optional Environment Variables (Alerts):")
    print("-" * 70)
    check_env_var("TELEGRAM_BOT_TOKEN", "Telegram Bot Token")
    check_env_var("TELEGRAM_CHAT_ID", "Telegram Chat ID")
    check_env_var("DISCORD_WEBHOOK_URL", "Discord Webhook URL")
    print()

    # Check Python packages
    print("Required Python Packages:")
    print("-" * 70)
    all_ok &= check_python_import("langgraph", "LangGraph")
    all_ok &= check_python_import("langchain", "LangChain")
    all_ok &= check_python_import("pydantic", "Pydantic")
    all_ok &= check_python_import("pandas", "Pandas")
    all_ok &= check_python_import("ib_insync", "IB Insync")
    print()

    print("Optional Python Packages:")
    print("-" * 70)
    check_python_import("groq", "Groq")
    check_python_import("litellm", "LiteLLM")
    check_python_import("ccxt", "CCXT")
    check_python_import("vectorbt", "VectorBT")
    check_python_import("streamlit", "Streamlit")
    print()

    # Check core modules
    print("Core Modules:")
    print("-" * 70)
    try:
        from pearlalgo.agents.langgraph_state import TradingState

        print("✅ LangGraph State")
    except ImportError as e:
        print(f"❌ LangGraph State: {e}")
        all_ok = False

    try:
        from pearlalgo.agents.langgraph_workflow import TradingWorkflow

        print("✅ LangGraph Workflow")
    except ImportError as e:
        print(f"❌ LangGraph Workflow: {e}")
        all_ok = False

    try:
        from pearlalgo.brokers.factory import get_broker

        print("✅ Broker Factory")
    except ImportError as e:
        print(f"❌ Broker Factory: {e}")
        all_ok = False
    print()

    # Final summary
    print("=" * 70)
    if all_ok:
        print("✅ SYSTEM SETUP VERIFIED - Ready to run!")
    else:
        print("❌ SYSTEM SETUP INCOMPLETE - Please fix issues above")
    print("=" * 70)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
