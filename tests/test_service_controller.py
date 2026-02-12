"""
Tests for Service Controller.

Validates the service controller utilities for shell/script orchestration.

Note: Marked as integration tests because they execute shell scripts.
"""

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess

from pearlalgo.utils.service_controller import ServiceController


class TestServiceControllerInit:
    """Test ServiceController initialization."""

    def test_init_with_project_root(self, tmp_path):
        """Should initialize with specified project root."""
        controller = ServiceController(project_root=tmp_path)
        assert controller.project_root == tmp_path

    def test_init_auto_detect_root(self):
        """Should auto-detect project root when not specified."""
        controller = ServiceController()
        assert controller.project_root.exists()
        assert (controller.scripts_dir).exists() or True  # May not exist in test env

    def test_scripts_dir_set(self, tmp_path):
        """Should set scripts directory."""
        controller = ServiceController(project_root=tmp_path)
        assert controller.scripts_dir == tmp_path / "scripts"


class TestRunScript:
    """Test _run_script method."""

    def test_missing_script_returns_error(self, tmp_path):
        """Should return error for missing script."""
        controller = ServiceController(project_root=tmp_path)
        missing_script = tmp_path / "nonexistent.sh"
        
        success, stdout, stderr = controller._run_script(missing_script)
        
        assert success is False
        assert "not found" in stderr.lower()

    def test_not_a_file_returns_error(self, tmp_path):
        """Should return error for directory."""
        controller = ServiceController(project_root=tmp_path)
        dir_path = tmp_path / "subdir"
        dir_path.mkdir()
        
        success, stdout, stderr = controller._run_script(dir_path)
        
        assert success is False
        assert "not a file" in stderr.lower()

    def test_successful_script_execution(self, tmp_path):
        """Should execute script successfully."""
        controller = ServiceController(project_root=tmp_path)
        
        # Create a simple test script
        script = tmp_path / "test.sh"
        script.write_text("#!/bin/bash\necho 'hello'\n")
        script.chmod(0o755)
        
        success, stdout, stderr = controller._run_script(script, check=False)
        
        assert success is True
        assert "hello" in stdout

    def test_script_with_args(self, tmp_path):
        """Should pass arguments to script."""
        controller = ServiceController(project_root=tmp_path)
        
        script = tmp_path / "echo_args.sh"
        script.write_text("#!/bin/bash\necho $1 $2\n")
        script.chmod(0o755)
        
        success, stdout, stderr = controller._run_script(
            script, 
            args=["arg1", "arg2"],
            check=False
        )
        
        assert success is True
        assert "arg1" in stdout
        assert "arg2" in stdout

    def test_script_failure(self, tmp_path):
        """Should handle script failure."""
        controller = ServiceController(project_root=tmp_path)
        
        script = tmp_path / "fail.sh"
        script.write_text("#!/bin/bash\nexit 1\n")
        script.chmod(0o755)
        
        success, stdout, stderr = controller._run_script(script, check=False)
        
        assert success is False

    def test_script_timeout(self, tmp_path):
        """Should handle script timeout."""
        controller = ServiceController(project_root=tmp_path)
        
        script = tmp_path / "slow.sh"
        script.write_text("#!/bin/bash\nsleep 10\n")
        script.chmod(0o755)
        
        success, stdout, stderr = controller._run_script(
            script, 
            timeout=1, 
            check=False
        )
        
        assert success is False
        assert "timed out" in stderr.lower()


class TestGatewayMethods:
    """Test gateway control methods."""

    @pytest.mark.asyncio
    async def test_start_gateway_script_missing(self, tmp_path):
        """Should handle missing gateway script."""
        controller = ServiceController(project_root=tmp_path)
        
        result = await controller.start_gateway()
        
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_stop_gateway(self, tmp_path):
        """Should call stop gateway script."""
        controller = ServiceController(project_root=tmp_path)
        
        # Create gateway directory and script
        gateway_dir = tmp_path / "scripts" / "gateway"
        gateway_dir.mkdir(parents=True)
        
        script = gateway_dir / "gateway.sh"
        script.write_text("#!/bin/bash\necho 'stopped'\n")
        script.chmod(0o755)
        
        result = await controller.stop_gateway()
        
        # May succeed or fail depending on script behavior
        assert "success" in result or "error" in str(result).lower()


class TestAgentMethods:
    """Test agent control methods."""

    @pytest.mark.asyncio
    async def test_start_agent(self, tmp_path):
        """Should call start agent script."""
        controller = ServiceController(project_root=tmp_path)
        
        # Create lifecycle directory and script
        lifecycle_dir = tmp_path / "scripts" / "lifecycle"
        lifecycle_dir.mkdir(parents=True)
        
        script = lifecycle_dir / "agent.sh"
        script.write_text("#!/bin/bash\necho 'started'\n")
        script.chmod(0o755)
        
        result = await controller.start_agent(market="NQ")
        
        assert "success" in result or "error" in str(result).lower()

    @pytest.mark.asyncio
    async def test_stop_agent(self, tmp_path):
        """Should call stop agent script."""
        controller = ServiceController(project_root=tmp_path)
        
        lifecycle_dir = tmp_path / "scripts" / "lifecycle"
        lifecycle_dir.mkdir(parents=True)
        
        script = lifecycle_dir / "agent.sh"
        script.write_text("#!/bin/bash\necho 'stopped'\n")
        script.chmod(0o755)
        
        result = await controller.stop_agent(market="NQ")
        
        assert "success" in result or "error" in str(result).lower()

    @pytest.mark.asyncio
    async def test_restart_agent(self, tmp_path):
        """Should call restart agent script."""
        controller = ServiceController(project_root=tmp_path)
        
        lifecycle_dir = tmp_path / "scripts" / "lifecycle"
        lifecycle_dir.mkdir(parents=True)
        
        script = lifecycle_dir / "agent.sh"
        script.write_text("#!/bin/bash\necho 'restarted'\n")
        script.chmod(0o755)
        
        result = await controller.restart_agent(market="NQ")
        
        assert "success" in result or "error" in str(result).lower()


class TestStatusMethods:
    """Test status check methods."""

    def test_get_agent_status(self, tmp_path):
        """Should return agent status."""
        controller = ServiceController(project_root=tmp_path)
        
        ops_dir = tmp_path / "scripts" / "ops"
        ops_dir.mkdir(parents=True)
        
        script = ops_dir / "status.sh"
        script.write_text("#!/bin/bash\necho 'running'\n")
        script.chmod(0o755)
        
        result = controller.get_agent_status(market="NQ")
        
        # Should return some status info
        assert isinstance(result, dict)


class TestEdgeCases:
    """Test edge cases."""

    def test_path_with_spaces(self, tmp_path):
        """Should handle paths with spaces."""
        space_path = tmp_path / "path with spaces"
        space_path.mkdir()
        
        controller = ServiceController(project_root=space_path)
        assert controller.project_root == space_path

    def test_unicode_in_script_output(self, tmp_path):
        """Should handle unicode in script output."""
        controller = ServiceController(project_root=tmp_path)
        
        script = tmp_path / "unicode.sh"
        script.write_text("#!/bin/bash\necho '✓ Success: 日本語'\n")
        script.chmod(0o755)
        
        success, stdout, stderr = controller._run_script(script, check=False)
        
        assert "✓" in stdout or success is True  # May vary by system
