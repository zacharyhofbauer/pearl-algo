"""
Streamlit Dashboard - Live trading dashboard with equity curve, positions, and agent reasoning.
"""
import asyncio
import yaml
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import streamlit as st
from loguru import logger

# Set page config
st.set_page_config(
    page_title="LangGraph Trading Dashboard",
    page_icon="📈",
    layout="wide",
)

# Load configuration
@st.cache_data
def load_config(config_path: Optional[str] = None) -> Dict:
    """Load configuration."""
    if config_path:
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    
    default_config = Path(__file__).parent.parent / "config" / "config.yaml"
    if default_config.exists():
        with open(default_config, "r") as f:
            return yaml.safe_load(f)
    
    return {}


def main():
    """Main dashboard function."""
    st.title("📈 LangGraph Multi-Agent Trading Dashboard")
    
    # Sidebar
    st.sidebar.header("Configuration")
    config_path = st.sidebar.text_input("Config Path", value="config/config.yaml")
    config = load_config(config_path)
    
    # Main content
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Current Equity", "$100,000.00", delta="$1,234.56")
    
    with col2:
        st.metric("Daily P&L", "$1,234.56", delta="1.23%")
    
    with col3:
        st.metric("Open Positions", "3", delta="1")
    
    # Equity Curve
    st.subheader("Equity Curve")
    
    # Generate sample equity curve (replace with real data)
    import numpy as np
    dates = pd.date_range(start="2024-01-01", periods=100, freq="D")
    equity = 100000 + np.cumsum(np.random.randn(100) * 1000)
    equity_df = pd.DataFrame({"Equity": equity}, index=dates)
    
    st.line_chart(equity_df)
    
    # Positions
    st.subheader("Current Positions")
    
    positions_data = {
        "Symbol": ["ES", "NQ", "GC"],
        "Size": [2, -1, 1],
        "Entry Price": [4500.0, 15000.0, 2000.0],
        "Current Price": [4510.0, 14950.0, 2005.0],
        "P&L": [20.0, -50.0, 5.0],
    }
    positions_df = pd.DataFrame(positions_data)
    st.dataframe(positions_df, use_container_width=True)
    
    # Agent Reasoning
    st.subheader("Agent Reasoning")
    
    reasoning_data = {
        "Agent": ["Market Data", "Quant Research", "Risk Manager", "Portfolio/Execution"],
        "Timestamp": ["2024-01-01 10:00:00"] * 4,
        "Message": [
            "Fetched market data for ES, NQ, GC",
            "Generated LONG signal for ES (confidence: 0.75)",
            "Risk-approved position: 2 contracts, 1.5% risk",
            "Order submitted: ES LONG 2 @ $4500.00",
        ],
        "Level": ["info", "info", "info", "info"],
    }
    reasoning_df = pd.DataFrame(reasoning_data)
    st.dataframe(reasoning_df, use_container_width=True)
    
    # Risk Metrics
    st.subheader("Risk Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Max Risk Per Trade", "2.0%")
    
    with col2:
        st.metric("Current Drawdown", "1.5%")
    
    with col3:
        st.metric("Risk Status", "OK", delta="Normal")
    
    with col4:
        st.metric("Daily Loss Limit", "$2,500.00")
    
    # Performance Metrics
    st.subheader("Performance Metrics")
    
    perf_data = {
        "Metric": ["Total Return", "Sharpe Ratio", "Max Drawdown", "Win Rate"],
        "Value": ["12.5%", "1.85", "5.2%", "58.3%"],
    }
    perf_df = pd.DataFrame(perf_data)
    st.dataframe(perf_df, use_container_width=True)
    
    # Auto-refresh
    if st.sidebar.checkbox("Auto-refresh", value=True):
        refresh_interval = st.sidebar.slider("Refresh Interval (seconds)", 1, 60, 5)
        st.rerun()


if __name__ == "__main__":
    main()

