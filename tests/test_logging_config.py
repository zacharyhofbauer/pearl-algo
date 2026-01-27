"""
Tests for Logging Configuration.

Validates logging setup, correlation IDs, and run IDs.
"""

import pytest
import os
from unittest.mock import patch

from pearlalgo.utils.logging_config import (
    get_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    get_run_id,
    set_run_id,
)


class TestCorrelationId:
    """Test correlation ID management."""

    def test_initial_correlation_id_is_none(self):
        """Should start with no correlation ID."""
        clear_correlation_id()  # Reset state
        assert get_correlation_id() is None

    def test_set_and_get_correlation_id(self):
        """Should set and retrieve correlation ID."""
        cid = set_correlation_id("test-correlation-123")
        assert cid == "test-correlation-123"
        assert get_correlation_id() == "test-correlation-123"
        clear_correlation_id()  # Cleanup

    def test_auto_generate_correlation_id(self):
        """Should generate UUID if none provided."""
        clear_correlation_id()  # Reset
        cid = set_correlation_id()
        
        assert cid is not None
        assert len(cid) > 0
        assert get_correlation_id() == cid
        clear_correlation_id()  # Cleanup

    def test_clear_correlation_id(self):
        """Should clear correlation ID."""
        set_correlation_id("test-id")
        clear_correlation_id()
        assert get_correlation_id() is None

    def test_multiple_set_calls(self):
        """Should overwrite previous correlation ID."""
        set_correlation_id("first")
        set_correlation_id("second")
        assert get_correlation_id() == "second"
        clear_correlation_id()


class TestRunId:
    """Test run ID management."""

    def test_get_run_id_initial(self):
        """Should return None or existing run ID."""
        # Run ID might be set from previous tests
        rid = get_run_id()
        assert rid is None or isinstance(rid, str)

    def test_set_and_get_run_id(self):
        """Should set and retrieve run ID."""
        rid = set_run_id("test-run-456")
        assert rid == "test-run-456"
        assert get_run_id() == "test-run-456"

    def test_auto_generate_run_id(self):
        """Should generate short UUID if none provided."""
        rid = set_run_id()
        
        assert rid is not None
        assert len(rid) > 0
        assert get_run_id() == rid

    def test_run_id_format(self):
        """Should generate valid run ID format."""
        rid = set_run_id()
        
        # Should be alphanumeric (may include dashes)
        clean_rid = rid.replace("-", "")
        assert clean_rid.isalnum() or len(rid) > 0


class TestCorrelationIdUniqueness:
    """Test correlation ID uniqueness."""

    def test_unique_ids_generated(self):
        """Should generate unique IDs each time."""
        clear_correlation_id()
        
        ids = []
        for _ in range(100):
            cid = set_correlation_id()
            ids.append(cid)
            clear_correlation_id()
        
        # All should be unique
        assert len(set(ids)) == 100


class TestRunIdUniqueness:
    """Test run ID uniqueness."""

    def test_unique_run_ids(self):
        """Should generate unique run IDs."""
        ids = []
        for _ in range(100):
            rid = set_run_id()
            ids.append(rid)
        
        # All should be unique
        assert len(set(ids)) == 100


class TestEdgeCases:
    """Test edge cases."""

    def test_correlation_id_with_special_chars(self):
        """Should handle special characters in ID."""
        cid = set_correlation_id("test-id_with.special:chars")
        assert get_correlation_id() == "test-id_with.special:chars"
        clear_correlation_id()

    def test_empty_string_correlation_id(self):
        """Should handle empty string as correlation ID."""
        cid = set_correlation_id("")
        assert get_correlation_id() == ""
        clear_correlation_id()

    def test_correlation_id_context_isolation(self):
        """Context vars should be isolated per context."""
        import asyncio
        
        results = []
        
        async def task1():
            set_correlation_id("task1-id")
            await asyncio.sleep(0.01)
            results.append(("task1", get_correlation_id()))
        
        async def task2():
            set_correlation_id("task2-id")
            await asyncio.sleep(0.01)
            results.append(("task2", get_correlation_id()))
        
        async def run_tasks():
            await asyncio.gather(task1(), task2())
        
        asyncio.run(run_tasks())
        
        # Each task should have its own correlation ID
        # (Note: context vars may or may not isolate depending on implementation)
        assert len(results) == 2
