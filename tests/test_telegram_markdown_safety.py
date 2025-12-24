"""
Tests for Telegram Markdown safety utilities.

Verifies that subprocess output and dynamic text is properly escaped
to prevent Telegram Markdown parse errors.
"""

from __future__ import annotations

import pytest

from pearlalgo.utils.telegram_alerts import (
    escape_markdown,
    escape_subprocess_output,
    safe_label,
)


class TestEscapeMarkdown:
    """Tests for escape_markdown function."""
    
    def test_escapes_underscores(self):
        """Underscores should be escaped."""
        assert escape_markdown("nq_agent.pid") == "nq\\_agent.pid"
    
    def test_escapes_asterisks(self):
        """Asterisks should be escaped."""
        assert escape_markdown("**bold**") == "\\*\\*bold\\*\\*"
    
    def test_escapes_backticks(self):
        """Backticks should be escaped."""
        assert escape_markdown("`code`") == "\\`code\\`"
    
    def test_escapes_brackets(self):
        """Opening brackets should be escaped."""
        assert escape_markdown("[link]") == "\\[link]"
    
    def test_handles_empty_string(self):
        """Empty string should return empty string."""
        assert escape_markdown("") == ""
    
    def test_handles_none(self):
        """None should return empty string."""
        assert escape_markdown(None) == ""
    
    def test_preserves_regular_text(self):
        """Regular text without special chars should be unchanged."""
        assert escape_markdown("Hello World 123") == "Hello World 123"


class TestEscapeSubprocessOutput:
    """Tests for escape_subprocess_output function."""
    
    def test_escapes_underscores_in_paths(self):
        """File paths with underscores should be escaped."""
        output = "Started process from nq_agent.pid"
        escaped = escape_subprocess_output(output)
        assert "_" not in escaped or "\\_" in escaped
    
    def test_escapes_asterisks(self):
        """Asterisks in output should be escaped."""
        output = "* some bullet point *"
        escaped = escape_subprocess_output(output)
        assert "\\*" in escaped
    
    def test_strips_ansi_escape_sequences(self):
        """ANSI color codes should be stripped."""
        # Simulate colored output with ANSI escape
        output = "\x1b[32mGreen text\x1b[0m"
        escaped = escape_subprocess_output(output)
        assert "\x1b" not in escaped
        assert "Green text" in escaped
    
    def test_escapes_complex_ansi_sequences(self):
        """Complex ANSI sequences should be stripped."""
        # Cursor movement + color
        output = "\x1b[2J\x1b[H\x1b[31mRed text\x1b[0m"
        escaped = escape_subprocess_output(output)
        assert "\x1b" not in escaped
        assert "Red text" in escaped
    
    def test_escapes_brackets(self):
        """Brackets should be escaped."""
        output = "[INFO] Starting [agent]"
        escaped = escape_subprocess_output(output)
        assert "\\[" in escaped
        assert "\\]" in escaped
    
    def test_escapes_backslashes(self):
        """Backslashes should be escaped."""
        output = "Path: C:\\Users\\test"
        escaped = escape_subprocess_output(output)
        # Backslashes get double-escaped
        assert "\\\\" in escaped
    
    def test_handles_empty_string(self):
        """Empty string should return empty string."""
        assert escape_subprocess_output("") == ""
    
    def test_handles_none(self):
        """None should return empty string."""
        assert escape_subprocess_output(None) == ""
    
    def test_typical_shell_output(self):
        """Typical shell script output should be safely escaped."""
        output = """✅ Virtual environment activated
NQ Agent Service started in background
   PID: 12345
   PID File: logs/nq_agent.pid

⚠️  Note: Logs are not saved to file."""
        
        escaped = escape_subprocess_output(output)
        
        # Should have escaped underscores in "nq_agent.pid"
        assert "nq\\_agent" in escaped
        # Regular text should be present
        assert "Virtual environment activated" in escaped
        # Emojis should be preserved
        assert "✅" in escaped
        assert "⚠️" in escaped


class TestSafeLabel:
    """Tests for safe_label function."""
    
    def test_replaces_underscores_with_spaces(self):
        """Underscores should be replaced with spaces."""
        assert safe_label("nq_agent_service") == "nq agent service"
    
    def test_handles_empty_string(self):
        """Empty string should return empty string."""
        assert safe_label("") == ""
    
    def test_handles_none(self):
        """None should return empty string."""
        assert safe_label(None) == ""


class TestMarkdownSafetyRegression:
    """Regression tests for Markdown parsing issues."""
    
    def test_pid_file_path_safe(self):
        """Common PID file path patterns should be safe."""
        paths = [
            "logs/nq_agent.pid",
            "/home/user/nq_agent/logs/nq_agent.pid",
            "data/nq_agent_state/state.json",
        ]
        
        for path in paths:
            escaped = escape_subprocess_output(path)
            # After escaping, should not have unescaped underscores
            # Check that every underscore is preceded by a backslash
            for i, char in enumerate(escaped):
                if char == '_' and i > 0:
                    assert escaped[i-1] == '\\', f"Unescaped underscore in: {escaped}"
    
    def test_shell_script_output_safe(self):
        """Shell script output with various markers should be safe."""
        outputs = [
            "✅ NQ Agent Service started successfully",
            "⚠️ Warning: IBKR Gateway is not running",
            "❌ Failed to start NQ Agent Service",
            "Process PID: 12345 (nq_agent.pid)",
            "Config: config/config.yaml loaded",
        ]
        
        for output in outputs:
            escaped = escape_subprocess_output(output)
            # Should not raise and should have content
            assert len(escaped) > 0
    
    def test_combined_message_safe(self):
        """Combined message with multiple dynamic parts should be safe."""
        message_template = "✅ NQ Agent Service started successfully\n"
        details = "Agent process is running\nPID File: logs/nq_agent.pid"
        
        escaped_details = escape_subprocess_output(details)
        full_message = f"{message_template}\n{escaped_details}"
        
        # The full message should be safe
        assert "\\nq\\_agent" in full_message or "nq\\_agent" in full_message


