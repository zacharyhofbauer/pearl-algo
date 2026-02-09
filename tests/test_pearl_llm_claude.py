"""
Tests for Claude LLM response parsing.
"""

from pearlalgo.pearl_ai.llm_claude import ClaudeLLM


def test_parse_response_concatenates_text_blocks():
    """Multiple text blocks should be concatenated in order."""
    llm = ClaudeLLM(api_key="test-key")
    data = {
        "content": [
            {"type": "text", "text": "Hello "},
            {"type": "tool_use", "id": "tool_1", "name": "get_regime_performance", "input": {"regime": "trending"}},
            {"type": "text", "text": "world"},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "model": "claude-test",
        "stop_reason": "end_turn",
    }

    response = llm._parse_response(data)

    assert response.content == "Hello world"
    assert response.tool_calls == [
        {"id": "tool_1", "name": "get_regime_performance", "input": {"regime": "trending"}}
    ]
