"""
Quant Research Agent - Generates trading signals using strategies and LLM reasoning.

This agent is responsible for:
- Signal generation using existing strategies (momentum, mean-reversion)
- Regime detection (trending vs ranging)
- Lightweight ML (optional sklearn models)
- LLM-powered reasoning via Groq/LiteLLM
- Confidence scoring
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import logging

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.agents.langgraph_state import (
    MarketData,
    Signal,
    TradingState,
    add_agent_reasoning,
)
from pearlalgo.futures.signals import generate_signal

logger = logging.getLogger(__name__)


class QuantResearchAgent:
    """
    Quant Research Agent for LangGraph workflow.
    
    Generates trading signals using technical analysis, regime detection,
    and optional LLM reasoning.
    """
    
    def __init__(
        self,
        symbols: List[str],
        strategy: str = "sr",
        config: Optional[Dict] = None,
    ):
        self.symbols = symbols
        self.strategy = strategy
        self.config = config or {}
        
        # LLM configuration
        self.use_llm = self.config.get("agents", {}).get(
            "quant_research", {}
        ).get("use_llm_reasoning", True)
        self.llm_provider = None
        self.llm_model = None
        
        # Regime detection
        self.use_regime_detection = self.config.get("agents", {}).get(
            "quant_research", {}
        ).get("regime_detection", True)
        
        # ML models (optional)
        self.use_ml = self.config.get("agents", {}).get(
            "quant_research", {}
        ).get("ml_models", False)
        self.ml_models: Dict[str, any] = {}
        
        # Initialize LLM if enabled
        if self.use_llm:
            self._initialize_llm()
        
        # Initialize ML models if enabled
        if self.use_ml:
            self._initialize_ml_models()
        
        logger.info(
            f"QuantResearchAgent initialized: strategy={strategy}, "
            f"llm={self.use_llm}, regime={self.use_regime_detection}, ml={self.use_ml}"
        )
    
    def _initialize_llm(self) -> None:
        """Initialize LLM provider (Groq, OpenAI, Anthropic, or LiteLLM)."""
        try:
            llm_config = self.config.get("llm", {})
            provider = llm_config.get("provider", "groq")
            
            if provider == "groq":
                try:
                    from groq import Groq
                except ImportError:
                    logger.warning("groq package not installed, LLM reasoning disabled")
                    self.use_llm = False
                    return
                
                api_key = llm_config.get("groq", {}).get("api_key")
                if not api_key:
                    logger.warning("Groq API key not found, LLM reasoning disabled")
                    self.use_llm = False
                    return
                
                self.llm_provider = Groq(api_key=api_key)
                self.llm_model = llm_config.get("groq", {}).get(
                    "model", "mixtral-8x7b-32768"
                )
                logger.info(f"Groq LLM initialized: {self.llm_model}")
            
            elif provider == "openai":
                try:
                    import litellm
                except ImportError:
                    logger.warning("litellm package not installed, LLM reasoning disabled")
                    self.use_llm = False
                    return
                
                api_key = llm_config.get("openai", {}).get("api_key")
                model = llm_config.get("openai", {}).get("model", "gpt-4o")
                
                if not api_key:
                    logger.warning("OpenAI API key not found, LLM reasoning disabled")
                    self.use_llm = False
                    return
                
                # Set OpenAI API key for LiteLLM
                import os
                os.environ["OPENAI_API_KEY"] = api_key
                self.llm_provider = litellm
                # LiteLLM format: "openai/model-name"
                self.llm_model = f"openai/{model}" if not model.startswith("openai/") else model
                logger.info(f"OpenAI LLM initialized: {self.llm_model}")
            
            elif provider == "anthropic":
                try:
                    import litellm
                except ImportError:
                    logger.warning("litellm package not installed, LLM reasoning disabled")
                    self.use_llm = False
                    return
                
                api_key = llm_config.get("anthropic", {}).get("api_key")
                model = llm_config.get("anthropic", {}).get("model", "claude-3-opus-20240229")
                
                if not api_key:
                    logger.warning("Anthropic API key not found, LLM reasoning disabled")
                    self.use_llm = False
                    return
                
                # Set Anthropic API key for LiteLLM
                import os
                os.environ["ANTHROPIC_API_KEY"] = api_key
                self.llm_provider = litellm
                # LiteLLM format: "anthropic/model-name"
                self.llm_model = f"anthropic/{model}" if not model.startswith("anthropic/") else model
                logger.info(f"Anthropic LLM initialized: {self.llm_model}")
            
            elif provider == "litellm":
                import litellm
                
                api_key = llm_config.get("litellm", {}).get("api_key")
                model = llm_config.get("litellm", {}).get("model", "gpt-4o-mini")
                
                if not api_key:
                    logger.warning("LiteLLM API key not found, LLM reasoning disabled")
                    self.use_llm = False
                    return
                
                # Try to detect provider from model name
                import os
                if model.startswith("openai/"):
                    os.environ["OPENAI_API_KEY"] = api_key
                elif model.startswith("anthropic/"):
                    os.environ["ANTHROPIC_API_KEY"] = api_key
                else:
                    # Default to OpenAI if no prefix
                    os.environ["OPENAI_API_KEY"] = api_key
                
                self.llm_provider = litellm
                self.llm_model = model
                logger.info(f"LiteLLM initialized: {self.llm_model}")
            
            else:
                logger.warning(f"Unknown LLM provider: {provider}. Supported: groq, openai, anthropic, litellm")
                self.use_llm = False
        
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}", exc_info=True)
            self.use_llm = False
    
    def _initialize_ml_models(self) -> None:
        """Initialize lightweight ML models for signal enhancement."""
        try:
            # This is a placeholder - in production, you'd load trained models
            # For now, we'll use simple sklearn models if needed
            from sklearn.ensemble import RandomForestClassifier
            
            # Initialize a simple model for each symbol (placeholder)
            for symbol in self.symbols:
                # In production, load pre-trained model
                # self.ml_models[symbol] = joblib.load(f"models/{symbol}_model.pkl")
                logger.debug(f"ML model placeholder for {symbol}")
        
        except Exception as e:
            logger.warning(f"ML models not available: {e}")
            self.use_ml = False
    
    async def generate_signals(
        self, state: TradingState
    ) -> TradingState:
        """
        Generate trading signals for all symbols.
        
        This is the main entry point called by the LangGraph workflow.
        """
        logger.info("QuantResearchAgent: Generating signals for all symbols")
        
        state = add_agent_reasoning(
            state,
            "quant_research_agent",
            f"Generating {self.strategy} signals for {len(self.symbols)} symbols",
            level="info",
        )
        
        # Generate signals for each symbol
        for symbol in self.symbols:
            try:
                # Get market data
                market_data = state.market_data.get(symbol)
                if not market_data:
                    state = add_agent_reasoning(
                        state,
                        "quant_research_agent",
                        f"No market data available for {symbol}",
                        level="warning",
                    )
                    continue
                
                # Convert market data to DataFrame for signal generation
                df = self._market_data_to_dataframe(market_data, symbol)
                
                # Generate base signal using existing strategy
                signal_dict = generate_signal(
                    symbol, df, strategy_name=self.strategy, fast=20, slow=50
                )
                
                # Detect regime
                regime = None
                if self.use_regime_detection:
                    regime = self._detect_regime(df)
                    signal_dict["regime"] = regime
                
                # Enhance with ML if enabled
                if self.use_ml and symbol in self.ml_models:
                    signal_dict = self._enhance_with_ml(symbol, signal_dict, df)
                
                # Generate LLM reasoning if enabled
                reasoning = None
                if self.use_llm and signal_dict.get("side") != "flat":
                    reasoning = await self._generate_llm_reasoning(
                        symbol, signal_dict, market_data, regime
                    )
                    signal_dict["reasoning"] = reasoning
                
                # Create Signal object
                signal = Signal(
                    symbol=symbol,
                    timestamp=datetime.now(timezone.utc),
                    side=signal_dict.get("side", "flat"),
                    strategy_name=signal_dict.get("strategy_name", self.strategy),
                    confidence=signal_dict.get("confidence", 0.5),
                    entry_price=signal_dict.get("entry_price"),
                    stop_loss=signal_dict.get("stop_price"),
                    take_profit=signal_dict.get("target_price"),
                    indicators=signal_dict,
                    reasoning=reasoning,
                    regime=regime,
                    metadata=signal_dict.get("params", {}),
                )
                
                state.signals[symbol] = signal
                
                state = add_agent_reasoning(
                    state,
                    "quant_research_agent",
                    f"Generated {signal.side.upper()} signal for {symbol} "
                    f"(confidence: {signal.confidence:.2f})",
                    level="info",
                    data={
                        "symbol": symbol,
                        "side": signal.side,
                        "confidence": signal.confidence,
                        "regime": regime,
                    },
                )
            
            except Exception as e:
                error_msg = f"Error generating signal for {symbol}: {e}"
                logger.error(error_msg, exc_info=True)
                state.errors.append(error_msg)
                state = add_agent_reasoning(
                    state,
                    "quant_research_agent",
                    error_msg,
                    level="error",
                    data={"symbol": symbol, "error": str(e)},
                )
        
        logger.info(
            f"QuantResearchAgent: Generated {len(state.signals)} signals"
        )
        
        return state
    
    def _market_data_to_dataframe(
        self, market_data: MarketData, symbol: str
    ) -> pd.DataFrame:
        """
        Convert MarketData to DataFrame format expected by signal generators.
        
        For now, we create a minimal DataFrame. In production, you'd maintain
        a rolling buffer of historical bars.
        """
        # Create a simple DataFrame with the latest bar
        df = pd.DataFrame(
            {
                "Open": [market_data.open],
                "High": [market_data.high],
                "Low": [market_data.low],
                "Close": [market_data.close],
                "Volume": [market_data.volume],
            }
        )
        
        # In production, you'd append to a rolling buffer
        # For now, this is a minimal implementation
        
        return df
    
    def _detect_regime(
        self, df: pd.DataFrame
    ) -> Optional[str]:
        """
        Detect market regime: trending, ranging, or volatile.
        
        Uses ADX, ATR, and price action to determine regime.
        """
        if len(df) < 20:
            return None
        
        try:
            prices = df["Close"]
            
            # Calculate ADX (trend strength)
            # Simplified ADX calculation
            high_low = df["High"] - df["Low"]
            high_close = abs(df["High"] - df["Close"].shift())
            low_close = abs(df["Low"] - df["Close"].shift())
            
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            
            # Calculate price volatility
            returns = prices.pct_change()
            volatility = returns.rolling(20).std().iloc[-1]
            
            # Calculate trend strength (simplified)
            sma_20 = prices.rolling(20).mean()
            sma_50 = prices.rolling(50).mean() if len(prices) >= 50 else sma_20
            
            price_above_sma = (prices.iloc[-1] > sma_20.iloc[-1]) if len(sma_20) > 0 else False
            sma_trending = (
                abs(sma_20.iloc[-1] - sma_50.iloc[-1]) / sma_50.iloc[-1]
                if len(sma_50) > 0 and sma_50.iloc[-1] > 0
                else 0
            )
            
            # Classify regime
            if volatility > 0.02:  # High volatility
                return "volatile"
            elif sma_trending > 0.01:  # Strong trend
                return "trending"
            else:
                return "ranging"
        
        except Exception as e:
            logger.warning(f"Error detecting regime: {e}")
            return None
    
    def _enhance_with_ml(
        self, symbol: str, signal_dict: Dict, df: pd.DataFrame
    ) -> Dict:
        """
        Enhance signal using ML model (if available).
        
        This is a placeholder - in production, you'd use trained models.
        """
        # Placeholder implementation
        # In production, extract features and run through model
        return signal_dict
    
    async def _generate_llm_reasoning(
        self,
        symbol: str,
        signal_dict: Dict,
        market_data: MarketData,
        regime: Optional[str],
    ) -> Optional[str]:
        """
        Generate LLM reasoning for the trading signal.
        
        Uses Groq (direct), OpenAI (via LiteLLM), or Anthropic (via LiteLLM) 
        to explain why the signal was generated.
        """
        if not self.llm_provider:
            return None
        
        try:
            # Build prompt
            prompt = f"""You are a quantitative trading analyst. Analyze this trading signal and provide a brief reasoning (2-3 sentences).

Symbol: {symbol}
Signal: {signal_dict.get('side', 'flat').upper()}
Strategy: {signal_dict.get('strategy_name', 'unknown')}
Confidence: {signal_dict.get('confidence', 0.5):.2f}
Current Price: ${market_data.close:.2f}
Regime: {regime or 'unknown'}

Key Indicators:
- Fast MA: {signal_dict.get('fast_ma', 'N/A')}
- Slow MA: {signal_dict.get('slow_ma', 'N/A')}
- VWAP: {signal_dict.get('vwap', 'N/A')}
- Support: {signal_dict.get('support1', 'N/A')}
- Resistance: {signal_dict.get('resistance1', 'N/A')}

Provide a concise explanation of why this signal was generated and its risk/reward profile."""

            # Check if it's a Groq client (direct integration)
            if hasattr(self.llm_provider, "chat") and hasattr(self.llm_provider.chat, "completions"):
                # Groq (direct)
                response = self.llm_provider.chat.completions.create(
                    model=self.llm_model,
                    messages=[
                        {"role": "system", "content": "You are a quantitative trading analyst."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=200,
                )
                return response.choices[0].message.content
            
            else:
                # LiteLLM (for OpenAI, Anthropic, or other providers)
                response = await self.llm_provider.acompletion(
                    model=self.llm_model,
                    messages=[
                        {"role": "system", "content": "You are a quantitative trading analyst."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=200,
                )
                return response.choices[0].message.content
        
        except Exception as e:
            logger.warning(f"LLM reasoning generation failed: {e}")
            return None

