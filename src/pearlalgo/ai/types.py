"""
AI Types - Data structures for the AI abstraction layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class AITaskType(Enum):
    """Types of AI tasks for routing decisions."""
    REASONING = "reasoning"          # Strategy analysis, debugging, complex thinking
    CODE_GEN = "code_gen"            # Code generation, patches, scripts
    QUICK = "quick"                  # Quick lookups, status checks, simple queries
    SIGNAL_SCORING = "signal_scoring"  # ML-based signal confidence scoring
    CHAT = "chat"                    # General conversational chat
    ANALYSIS = "analysis"            # Trade analysis, performance review


class MessageRole(Enum):
    """Message roles in a conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ThinkingBlock:
    """A block of thinking/reasoning from the AI."""
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __str__(self) -> str:
        return f"[THINKING] {self.content}"


@dataclass
class ToolCall:
    """A tool call made by the AI."""
    id: str
    name: str
    arguments: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __str__(self) -> str:
        return f"[TOOL] {self.name}({self.arguments})"


@dataclass
class ToolResult:
    """Result of a tool execution."""
    tool_call_id: str
    content: str
    is_error: bool = False
    
    def __str__(self) -> str:
        prefix = "[ERROR]" if self.is_error else "[RESULT]"
        return f"{prefix} {self.content}"


@dataclass
class AIMessage:
    """A message in an AI conversation."""
    role: MessageRole
    content: str
    name: Optional[str] = None  # For tool messages
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None  # For tool result messages
    
    @classmethod
    def system(cls, content: str) -> "AIMessage":
        return cls(role=MessageRole.SYSTEM, content=content)
    
    @classmethod
    def user(cls, content: str) -> "AIMessage":
        return cls(role=MessageRole.USER, content=content)
    
    @classmethod
    def assistant(cls, content: str, tool_calls: list[ToolCall] | None = None) -> "AIMessage":
        return cls(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls or [])
    
    @classmethod
    def tool_result(cls, tool_call_id: str, content: str, is_error: bool = False) -> "AIMessage":
        return cls(
            role=MessageRole.TOOL,
            content=content,
            tool_call_id=tool_call_id,
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API calls."""
        result: dict[str, Any] = {
            "role": self.role.value,
            "content": self.content,
        }
        if self.name:
            result["name"] = self.name
        if self.tool_calls:
            result["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass
class CompletionConfig:
    """Configuration for AI completion requests."""
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    stop_sequences: list[str] = field(default_factory=list)
    
    # Thinking/reasoning options
    enable_thinking: bool = True
    thinking_budget: int = 8192  # Max tokens for thinking
    
    # Tool use options
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_choice: str = "auto"  # auto, none, required, or specific tool name
    
    # Streaming
    stream: bool = False
    
    # Provider-specific options
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIResponse:
    """Response from an AI provider."""
    content: str
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    
    # Metadata
    provider: str = ""
    model: str = ""
    finish_reason: str = ""
    
    # Usage
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    
    # Timing
    latency_ms: float = 0.0
    
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.thinking_tokens
    
    @property
    def has_thinking(self) -> bool:
        return len(self.thinking_blocks) > 0
    
    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
    
    def get_thinking_text(self) -> str:
        """Get all thinking as a single text."""
        return "\n\n".join(block.content for block in self.thinking_blocks)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "content": self.content,
            "thinking_blocks": [{"content": b.content} for b in self.thinking_blocks],
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ],
            "provider": self.provider,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "latency_ms": self.latency_ms,
        }


@dataclass
class StreamChunk:
    """A chunk of streamed response."""
    content: str = ""
    thinking_content: str = ""
    tool_call_delta: Optional[dict[str, Any]] = None
    is_final: bool = False
    
    @property
    def is_thinking(self) -> bool:
        return bool(self.thinking_content)
