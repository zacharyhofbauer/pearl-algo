# Legacy Backup Directory

This directory contains backups of legacy agent files that have been replaced by the LangGraph multi-agent system.

## Backed Up Files

- `agents/automated_trading_agent.py` - Replaced by LangGraph workflow
- `agents/execution_agent.py` - Replaced by `portfolio_execution_agent.py`
- `agents/risk_agent.py` - Replaced by `risk_manager_agent.py`

## Date Backed Up

Backed up on: $(date)

## Purpose

These files are kept as reference in case any functionality needs to be migrated or referenced. They should NOT be used in production.

## Migration

All functionality has been migrated to:
- LangGraph workflow system
- New specialized agents (market_data_agent, quant_research_agent, risk_manager_agent, portfolio_execution_agent)

