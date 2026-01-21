"""
PearlAlgo Learning Layer

Provides a multi-layered machine learning system for adaptive trading:

Layer 1 - Feature Engineering:
    Extract 50+ predictive features from market data

Layer 2 - Contextual Bandits:
    Thompson sampling with market context awareness

Layer 3 - Ensemble Scoring:
    Combine multiple ML models (LogReg, GBM, Bandit)

Layer 4 - Regime Detection:
    HMM/heuristic market regime classification

Layer 5 - Meta-Learning:
    Experience replay and adaptive exploration

Plus:
- Risk metrics and virtual P&L tracking
- Persistent trade database for queryable history
"""

# Original bandit policy
from pearlalgo.learning.bandit_policy import BanditPolicy, BanditConfig, BanditDecision
from pearlalgo.learning.policy_state import PolicyState, SignalTypeStats

# Feature engineering (Layer 1)
from pearlalgo.learning.feature_engineer import (
    FeatureEngineer,
    FeatureConfig,
    FeatureVector,
)

# Contextual bandits (Layer 2)
from pearlalgo.learning.contextual_bandit import (
    ContextualBanditPolicy,
    ContextualBanditConfig,
    ContextualDecision,
    ContextFeatures,
    ContextualArmStats,
)

# Ensemble scoring (Layer 3)
from pearlalgo.learning.ensemble_scorer import (
    EnsembleScorer,
    EnsembleConfig,
    EnsemblePrediction,
)

# Trade database
from pearlalgo.learning.trade_database import (
    TradeDatabase,
    TradeRecord,
)

__all__ = [
    # Original
    "BanditPolicy",
    "BanditConfig",
    "BanditDecision",
    "PolicyState",
    "SignalTypeStats",
    
    # Layer 1: Features
    "FeatureEngineer",
    "FeatureConfig",
    "FeatureVector",
    
    # Layer 2: Contextual Bandits
    "ContextualBanditPolicy",
    "ContextualBanditConfig",
    "ContextualDecision",
    "ContextFeatures",
    "ContextualArmStats",
    
    # Layer 3: Ensemble
    "EnsembleScorer",
    "EnsembleConfig",
    "EnsemblePrediction",
    
    # Database
    "TradeDatabase",
    "TradeRecord",
]
