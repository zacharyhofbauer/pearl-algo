from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from pearlalgo.agentic.memory_store import MemoryStore
from pearlalgo.utils.logger import logger

# Optional OpenAI client (already used for /ai_patch)
try:
    from pearlalgo.utils.openai_client import OpenAIClient
except Exception:
    OpenAIClient = None  # type: ignore[assignment]


@dataclass
class AgenticConfig:
    enabled: bool = False
    llm_reasoning_enabled: bool = False
    llm_reasoning_max_signals_per_cycle: int = 1
    llm_reasoning_timeout_seconds: int = 20
    autopilot_enabled: bool = False
    autopilot_mode: str = "shadow"  # shadow|live
    autopilot_min_interval_minutes: int = 60
    autopilot_allow_files: list[str] = None  # type: ignore[assignment]
    autopilot_auto_apply: bool = False
    autopilot_restart_after_apply: bool = False

    @classmethod
    def from_service_config(cls, service_config: Dict[str, Any]) -> "AgenticConfig":
        raw = (service_config.get("agentic", {}) or {}) if isinstance(service_config, dict) else {}
        allow_files = raw.get("autopilot_allow_files") if isinstance(raw, dict) else None
        if not isinstance(allow_files, list):
            allow_files = ["config/config.yaml"]
        return cls(
            enabled=bool(raw.get("enabled", False)),
            llm_reasoning_enabled=bool(raw.get("llm_reasoning_enabled", False)),
            llm_reasoning_max_signals_per_cycle=int(raw.get("llm_reasoning_max_signals_per_cycle", 1) or 1),
            llm_reasoning_timeout_seconds=int(raw.get("llm_reasoning_timeout_seconds", 20) or 20),
            autopilot_enabled=bool(raw.get("autopilot_enabled", False)),
            autopilot_mode=str(raw.get("autopilot_mode", "shadow") or "shadow").lower(),
            autopilot_min_interval_minutes=int(raw.get("autopilot_min_interval_minutes", 60) or 60),
            autopilot_allow_files=[str(x) for x in allow_files],
            autopilot_auto_apply=bool(raw.get("autopilot_auto_apply", False)),
            autopilot_restart_after_apply=bool(raw.get("autopilot_restart_after_apply", False)),
        )


class AgenticHub:
    """
    Agent-level integration point for:
    - durable memory
    - optional LLM reasoning
    - future news/ML modules

    This object is owned by the running agent service and can be passed to strategies.
    """

    def __init__(self, *, state_dir: Path, service_config: Dict[str, Any]):
        self.state_dir = Path(state_dir)
        self.config = AgenticConfig.from_service_config(service_config)
        self.memory = MemoryStore(self.state_dir / "agent_memory.json")

        self._last_autopilot_at: Optional[datetime] = None

    def build_system_snapshot(self, *, market_data: Dict[str, Any], metrics: Optional[Dict[str, Any]] = None) -> str:
        latest_bar = market_data.get("latest_bar") if isinstance(market_data, dict) else None
        px = None
        ts = None
        data_level = None
        if isinstance(latest_bar, dict):
            px = latest_bar.get("close")
            ts = latest_bar.get("timestamp")
            data_level = latest_bar.get("_data_level")

        parts = [
            f"symbol={market_data.get('symbol') or market_data.get('cfg_symbol') or 'MNQ'}",
            f"latest_price={px}" if px is not None else "latest_price=NA",
            f"latest_ts={ts}" if ts is not None else "latest_ts=NA",
            f"data_level={data_level}" if data_level is not None else "data_level=NA",
        ]
        if metrics and isinstance(metrics, dict):
            for k in ("win_rate", "total_pnl", "exited_signals", "stop_loss_count", "take_profit_count"):
                if k in metrics:
                    parts.append(f"{k}={metrics.get(k)}")
        return "\n".join(parts)

    async def maybe_add_llm_reasoning(
        self,
        *,
        signal: Dict[str, Any],
        market_data: Dict[str, Any],
        metrics: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.config.enabled:
            return
        if not self.config.llm_reasoning_enabled:
            return
        if OpenAIClient is None:
            return

        snapshot = self.build_system_snapshot(market_data=market_data, metrics=metrics)
        prompt = (
            "TASK: Explain the trade decision.\n"
            "Output format:\n"
            "FACTS:\n"
            "- ...\n"
            "DECISION:\n"
            "- ...\n"
            "RISKS:\n"
            "- ...\n"
            "VALIDATION:\n"
            "- ...\n\n"
            f"SYSTEM SNAPSHOT:\n{snapshot}\n\n"
            f"SIGNAL:\n{signal}"
        )

        # Hard timeout to avoid blocking the scan loop indefinitely.
        timeout_s = max(1, int(self.config.llm_reasoning_timeout_seconds))
        try:
            client = OpenAIClient()
            text = await asyncio.wait_for(asyncio.to_thread(client.generate_response, prompt), timeout=timeout_s)
        except Exception:
            return

        if not text:
            return

        # Attach as extra reasoning without destroying existing structured reason text.
        existing = str(signal.get("reason") or "").strip()
        block = str(text).strip()
        if existing:
            signal["reason"] = existing + "\n\n" + block
        else:
            signal["reason"] = block

    def autopilot_due(self) -> bool:
        if not self.config.enabled:
            return False
        if not self.config.autopilot_enabled:
            return False
        if self._last_autopilot_at is None:
            return True
        delta = timedelta(minutes=int(self.config.autopilot_min_interval_minutes))
        return datetime.now(timezone.utc) - self._last_autopilot_at >= delta

    def mark_autopilot_ran(self) -> None:
        self._last_autopilot_at = datetime.now(timezone.utc)

    async def autopilot_tick(self, *, market_data: Dict[str, Any], metrics: Optional[Dict[str, Any]] = None) -> None:
        """
        Placeholder for self-tuning loop.

        Implementation intentionally conservative:
        - default OFF
        - no automatic writes unless explicitly enabled
        """
        if not self.autopilot_due():
            return
        self.mark_autopilot_ran()
        try:
            self.memory.append_event("autopilot_tick", {"mode": self.config.autopilot_mode})
        except Exception:
            pass

        logger.info(
            "Agentic autopilot tick (noop)",
            extra={
                "mode": self.config.autopilot_mode,
                "auto_apply": self.config.autopilot_auto_apply,
                "allow_files": self.config.autopilot_allow_files,
            },
        )

