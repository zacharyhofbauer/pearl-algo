"""
Tests for Claude LLM response parsing and API interaction.

Covers:
- _parse_response: valid, malformed, empty, tool_use, token extraction
- Initialisation and configuration
- generate / generate_with_metadata: success, API error, timeout, rate limit
- LLMResponse dataclass
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.pearl_ai.llm_claude import ClaudeLLM, LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api_response(
    content=None,
    usage=None,
    model="claude-test",
    stop_reason="end_turn",
):
    """Build a dict matching the Anthropic Messages API response shape."""
    return {
        "content": content or [],
        "usage": usage or {"input_tokens": 0, "output_tokens": 0},
        "model": model,
        "stop_reason": stop_reason,
    }


def _mock_session(status=200, json_data=None, text_data="", headers=None):
    """Create a mock aiohttp session that returns a single canned response."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data or {})
    mock_resp.text = AsyncMock(return_value=text_data)
    mock_resp.headers = headers or {}

    # async context manager for session.post(...)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post.return_value = mock_cm
    session.closed = False
    session.close = AsyncMock()
    return session


# ==========================================================================
# Initialisation
# ==========================================================================


def test_init_default_model():
    """Default model is Claude Sonnet."""
    llm = ClaudeLLM(api_key="k")
    assert llm.model == ClaudeLLM.CLAUDE_SONNET


def test_init_custom_model():
    """Custom model selection is stored correctly."""
    llm = ClaudeLLM(api_key="k", model=ClaudeLLM.CLAUDE_HAIKU)
    assert llm.model == ClaudeLLM.CLAUDE_HAIKU


def test_init_stores_config():
    """Timeout, retries, and caching flag are stored."""
    llm = ClaudeLLM(
        api_key="k",
        timeout=30,
        max_retries=5,
        enable_prompt_caching=False,
    )
    assert llm.timeout == 30
    assert llm.max_retries == 5
    assert llm.enable_prompt_caching is False


# ==========================================================================
# LLMResponse dataclass
# ==========================================================================


def test_llm_response_total_tokens():
    """total_tokens is the sum of input and output tokens."""
    r = LLMResponse(content="x", input_tokens=15, output_tokens=25)
    assert r.total_tokens == 40


def test_llm_response_defaults():
    """Default field values are sensible."""
    r = LLMResponse(content="hi")
    assert r.input_tokens == 0
    assert r.output_tokens == 0
    assert r.tool_calls is None
    assert r.model == ""
    assert r.stop_reason is None


# ==========================================================================
# _parse_response  (synchronous, no I/O)
# ==========================================================================


def test_parse_response_concatenates_text_blocks():
    """Multiple text blocks should be concatenated in order."""
    llm = ClaudeLLM(api_key="test-key")
    data = _make_api_response(
        content=[
            {"type": "text", "text": "Hello "},
            {
                "type": "tool_use",
                "id": "tool_1",
                "name": "get_regime_performance",
                "input": {"regime": "trending"},
            },
            {"type": "text", "text": "world"},
        ],
        usage={"input_tokens": 10, "output_tokens": 5},
    )

    response = llm._parse_response(data)

    assert response.content == "Hello world"
    assert response.tool_calls == [
        {
            "id": "tool_1",
            "name": "get_regime_performance",
            "input": {"regime": "trending"},
        }
    ]


def test_parse_response_text_only():
    """Response with only text blocks has tool_calls=None."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[{"type": "text", "text": "Just text"}],
        usage={"input_tokens": 5, "output_tokens": 3},
    )
    resp = llm._parse_response(data)
    assert resp.content == "Just text"
    assert resp.tool_calls is None


def test_parse_response_tool_use_only():
    """Response with only tool_use blocks has empty content string."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[
            {"type": "tool_use", "id": "t1", "name": "fn", "input": {}},
        ],
    )
    resp = llm._parse_response(data)
    assert resp.content == ""
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "fn"


def test_parse_response_empty_content():
    """Empty content array yields empty string and no tool calls."""
    llm = ClaudeLLM(api_key="k")
    resp = llm._parse_response(_make_api_response(content=[]))
    assert resp.content == ""
    assert resp.tool_calls is None


def test_parse_response_extracts_token_usage():
    """Token counts are extracted from the usage dict."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[{"type": "text", "text": "ok"}],
        usage={"input_tokens": 100, "output_tokens": 50},
    )
    resp = llm._parse_response(data)
    assert resp.input_tokens == 100
    assert resp.output_tokens == 50
    assert resp.total_tokens == 150


def test_parse_response_stop_reason_and_model():
    """stop_reason and model are carried through."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[{"type": "text", "text": "done"}],
        model="claude-sonnet-4-20250514",
        stop_reason="max_tokens",
    )
    resp = llm._parse_response(data)
    assert resp.stop_reason == "max_tokens"
    assert resp.model == "claude-sonnet-4-20250514"


def test_parse_response_malformed_blocks():
    """Blocks with missing 'text' key are handled gracefully."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[
            {"type": "text"},  # missing 'text' key
            {"type": "text", "text": "ok"},
        ],
    )
    resp = llm._parse_response(data)
    assert resp.content == "ok"


# ==========================================================================
# Async API interaction tests
# ==========================================================================


@pytest.mark.asyncio
async def test_generate_success():
    """Successful API call returns the parsed text content."""
    api_data = _make_api_response(
        content=[{"type": "text", "text": "Great session today!"}],
        usage={"input_tokens": 20, "output_tokens": 10},
    )
    llm = ClaudeLLM(api_key="k", max_retries=0)
    llm._session = _mock_session(status=200, json_data=api_data)

    result = await llm.generate("How was my day?")
    assert result == "Great session today!"


@pytest.mark.asyncio
async def test_generate_with_metadata_returns_llm_response():
    """generate_with_metadata returns a full LLMResponse with all fields."""
    api_data = _make_api_response(
        content=[{"type": "text", "text": "Analysis here"}],
        usage={"input_tokens": 30, "output_tokens": 20},
        model="claude-sonnet-4-20250514",
        stop_reason="end_turn",
    )
    llm = ClaudeLLM(api_key="k", max_retries=0)
    llm._session = _mock_session(status=200, json_data=api_data)

    resp = await llm.generate_with_metadata("Analyze")
    assert isinstance(resp, LLMResponse)
    assert resp.content == "Analysis here"
    assert resp.input_tokens == 30
    assert resp.output_tokens == 20
    assert resp.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_generate_api_error_raises():
    """A non-retryable API error (e.g. 400) raises RuntimeError."""
    llm = ClaudeLLM(api_key="k", max_retries=0)
    llm._session = _mock_session(status=400, text_data="Bad request")

    with pytest.raises(RuntimeError, match="Claude API error"):
        await llm.generate("bad")


@pytest.mark.asyncio
async def test_generate_timeout_raises():
    """Timeout on all attempts re-raises asyncio.TimeoutError."""
    llm = ClaudeLLM(api_key="k", max_retries=1)

    session = MagicMock()
    session.closed = False
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(
        side_effect=asyncio.TimeoutError("timed out")
    )
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    session.post.return_value = mock_cm
    llm._session = session

    with pytest.raises(asyncio.TimeoutError):
        await llm.generate("slow prompt")


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_generate_rate_limit_429(mock_sleep):
    """Repeated 429 responses exhaust retries and raise RuntimeError."""
    llm = ClaudeLLM(api_key="k", max_retries=1)
    llm._session = _mock_session(
        status=429,
        headers={"retry-after": "1"},
    )

    with pytest.raises(RuntimeError, match="Max retries exceeded"):
        await llm.generate("rate limited")

    # Confirm backoff sleep was invoked
    assert mock_sleep.call_count >= 1


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_generate_server_error_retries_then_raises(mock_sleep):
    """500 server errors trigger retries then raise RuntimeError."""
    llm = ClaudeLLM(api_key="k", max_retries=1)
    llm._session = _mock_session(status=500, text_data="Internal error")

    with pytest.raises(RuntimeError, match="Max retries exceeded"):
        await llm.generate("server error")

    # sleep(2^attempt) called for each retry iteration
    assert mock_sleep.call_count >= 1


# ==========================================================================
# Additional configuration tests
# ==========================================================================


def test_init_base_url():
    """Base URL defaults to Anthropic API v1 endpoint."""
    llm = ClaudeLLM(api_key="k")
    assert llm.base_url == "https://api.anthropic.com/v1"


def test_init_prompt_caching_enabled_by_default():
    """Prompt caching is enabled by default."""
    llm = ClaudeLLM(api_key="k")
    assert llm.enable_prompt_caching is True


def test_model_constants_are_distinct():
    """Each model constant is a unique string."""
    assert ClaudeLLM.CLAUDE_SONNET != ClaudeLLM.CLAUDE_HAIKU
    assert ClaudeLLM.CLAUDE_HAIKU != ClaudeLLM.CLAUDE_OPUS
    assert ClaudeLLM.CLAUDE_SONNET != ClaudeLLM.CLAUDE_OPUS


def test_init_api_key_stored():
    """The API key is stored on the instance."""
    llm = ClaudeLLM(api_key="my-secret-key")
    assert llm.api_key == "my-secret-key"


# ==========================================================================
# Additional LLMResponse tests
# ==========================================================================


def test_llm_response_with_tool_calls():
    """LLMResponse stores tool_calls correctly."""
    tools = [{"id": "t1", "name": "fn", "input": {"x": 1}}]
    r = LLMResponse(content="text", tool_calls=tools)
    assert r.tool_calls is not None
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0]["name"] == "fn"


def test_llm_response_total_tokens_zero():
    """total_tokens is 0 when no tokens are set."""
    r = LLMResponse(content="")
    assert r.total_tokens == 0


# ==========================================================================
# Additional _parse_response tests
# ==========================================================================


def test_parse_response_content_is_stripped():
    """Content is stripped of leading/trailing whitespace."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[{"type": "text", "text": "  padded  "}],
    )
    resp = llm._parse_response(data)
    assert resp.content == "padded"


def test_parse_response_multiple_tool_uses():
    """Multiple tool_use blocks are all collected."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[
            {"type": "tool_use", "id": "t1", "name": "fn1", "input": {}},
            {"type": "tool_use", "id": "t2", "name": "fn2", "input": {"a": 1}},
        ],
    )
    resp = llm._parse_response(data)
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0]["name"] == "fn1"
    assert resp.tool_calls[1]["name"] == "fn2"


def test_parse_response_unknown_block_type_ignored():
    """Unknown block types are silently skipped."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[
            {"type": "unknown_thing", "data": "??"},
            {"type": "text", "text": "visible"},
        ],
    )
    resp = llm._parse_response(data)
    assert resp.content == "visible"
    assert resp.tool_calls is None


def test_parse_response_cache_usage_tokens():
    """Cache-related usage fields don't affect input_tokens extraction."""
    llm = ClaudeLLM(api_key="k")
    data = _make_api_response(
        content=[{"type": "text", "text": "cached"}],
        usage={
            "input_tokens": 50,
            "output_tokens": 20,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 0,
        },
    )
    resp = llm._parse_response(data)
    assert resp.input_tokens == 50
    assert resp.output_tokens == 20
    assert resp.total_tokens == 70


def test_parse_response_missing_usage():
    """Missing usage dict defaults token counts to 0."""
    llm = ClaudeLLM(api_key="k")
    data = {
        "content": [{"type": "text", "text": "ok"}],
        "model": "test",
        "stop_reason": "end_turn",
    }
    resp = llm._parse_response(data)
    assert resp.input_tokens == 0
    assert resp.output_tokens == 0


# ==========================================================================
# Session management
# ==========================================================================


@pytest.mark.asyncio
async def test_close_session():
    """close() awaits session.close()."""
    llm = ClaudeLLM(api_key="k")
    llm._session = _mock_session(status=200)

    await llm.close()
    llm._session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_already_closed_session():
    """close() is a no-op when the session is already closed."""
    llm = ClaudeLLM(api_key="k")
    session = _mock_session(status=200)
    session.closed = True
    llm._session = session

    await llm.close()
    session.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_session_reuses_open_session():
    """_get_session returns the existing open session."""
    llm = ClaudeLLM(api_key="k")
    existing = MagicMock()
    existing.closed = False
    llm._session = existing

    session = await llm._get_session()
    assert session is existing


@pytest.mark.asyncio
async def test_get_session_replaces_closed_session():
    """_get_session creates a new session if the existing one is closed."""
    llm = ClaudeLLM(api_key="k")
    closed_session = MagicMock()
    closed_session.closed = True
    llm._session = closed_session

    with patch("aiohttp.ClientSession") as mock_cls:
        new_session = MagicMock()
        new_session.closed = False
        mock_cls.return_value = new_session

        session = await llm._get_session()
        assert session is new_session
        mock_cls.assert_called_once()


# ==========================================================================
# System prompt and payload tests
# ==========================================================================


@pytest.mark.asyncio
async def test_generate_system_prompt_cached_format():
    """System prompt uses cache_control wrapper when caching is enabled."""
    api_data = _make_api_response(
        content=[{"type": "text", "text": "ok"}],
    )
    llm = ClaudeLLM(api_key="k", max_retries=0, enable_prompt_caching=True)
    session = _mock_session(status=200, json_data=api_data)
    llm._session = session

    await llm.generate("test", system="sys prompt")

    payload = session.post.call_args.kwargs["json"]
    assert isinstance(payload["system"], list)
    assert payload["system"][0]["text"] == "sys prompt"
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_generate_system_prompt_plain_format():
    """System prompt is a plain string when caching is disabled."""
    api_data = _make_api_response(
        content=[{"type": "text", "text": "ok"}],
    )
    llm = ClaudeLLM(api_key="k", max_retries=0, enable_prompt_caching=False)
    session = _mock_session(status=200, json_data=api_data)
    llm._session = session

    await llm.generate("test", system="sys prompt")

    payload = session.post.call_args.kwargs["json"]
    assert payload["system"] == "sys prompt"


@pytest.mark.asyncio
async def test_generate_no_system_prompt():
    """Payload omits 'system' key when no system prompt is given."""
    api_data = _make_api_response(
        content=[{"type": "text", "text": "ok"}],
    )
    llm = ClaudeLLM(api_key="k", max_retries=0)
    session = _mock_session(status=200, json_data=api_data)
    llm._session = session

    await llm.generate("test")

    payload = session.post.call_args.kwargs["json"]
    assert "system" not in payload


@pytest.mark.asyncio
async def test_generate_with_stop_sequences():
    """Stop sequences are included in the API payload."""
    api_data = _make_api_response(
        content=[{"type": "text", "text": "stopped"}],
    )
    llm = ClaudeLLM(api_key="k", max_retries=0)
    session = _mock_session(status=200, json_data=api_data)
    llm._session = session

    await llm.generate("test", stop_sequences=["STOP", "END"])

    payload = session.post.call_args.kwargs["json"]
    assert payload["stop_sequences"] == ["STOP", "END"]


@pytest.mark.asyncio
async def test_generate_with_metadata_includes_tools():
    """Tools are included in the API payload when provided."""
    api_data = _make_api_response(
        content=[{"type": "text", "text": "ok"}],
    )
    llm = ClaudeLLM(api_key="k", max_retries=0)
    session = _mock_session(status=200, json_data=api_data)
    llm._session = session

    tools = [{"name": "test_tool", "description": "A test tool", "input_schema": {}}]
    await llm.generate_with_metadata("test", tools=tools)

    payload = session.post.call_args.kwargs["json"]
    assert payload["tools"] == tools
