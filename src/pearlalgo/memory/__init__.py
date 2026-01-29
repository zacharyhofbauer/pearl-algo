"""
Pearl Memory - Persistent memory system for Pearl AI.

This module provides long-term memory that persists across sessions, enabling
Pearl AI to learn from experience and maintain context over time.

Memory Types:
- Episodic Memory: Specific events and learnings (trades, errors, insights)
- Semantic Memory: Accumulated knowledge (patterns, statistics, rules)
- Procedural Memory: Learned behaviors (when to apply what strategy)

Usage:
    from pearlalgo.memory import PearlMemory, Episode, Knowledge
    
    memory = PearlMemory()
    
    # Store an episode
    episode = Episode(
        event_type="trade_win",
        context={"direction": "LONG", "regime": "trending_up"},
        outcome={"pnl": 125.00},
        lesson="LONG trades in trending_up regime work well"
    )
    await memory.remember(episode)
    
    # Recall relevant memories
    memories = await memory.recall("trending_up LONG trades")
    
    # Synthesize knowledge
    insight = await memory.synthesize("session performance")
"""

from pearlalgo.memory.types import (
    Episode,
    Knowledge,
    Procedure,
    MemoryType,
    MemoryQuery,
)
from pearlalgo.memory.store import (
    PearlMemory,
    get_pearl_memory,
)

__all__ = [
    # Types
    "Episode",
    "Knowledge",
    "Procedure",
    "MemoryType",
    "MemoryQuery",
    # Store
    "PearlMemory",
    "get_pearl_memory",
]
