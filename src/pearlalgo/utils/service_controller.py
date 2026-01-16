"""
Service Controller for executing lifecycle scripts safely.

This module provides a secure way to start/stop services from Python,
wrapping the shell scripts with proper error handling and logging.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pearlalgo.utils.logger import logger


class ServiceController:
    """Controller for managing gateway/agent/monitor services via shell scripts."""

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize service controller.

        Args:
            project_root: Project root directory (auto-detected if None)
        """
        if project_root is None:
            # Auto-detect project root (assumes this file is in src/pearlalgo/utils/)
            project_root = Path(__file__).parent.parent.parent.parent

        self.project_root = Path(project_root).resolve()
        self.scripts_dir = self.project_root / "scripts"

    def _run_script(
        self,
        script_path: Path,
        args: Optional[list[str]] = None,
        timeout: int = 60,
        check: bool = True,
    ) -> Tuple[bool, str, str]:
        """Run a shell script safely with timeout.

        Args:
            script_path: Path to script to execute
            timeout: Maximum execution time in seconds
            check: If True, raise on non-zero exit

        Returns:
            Tuple of (success, stdout, stderr)
        """
        if not script_path.exists():
            return False, "", f"Script not found: {script_path}"

        if not script_path.is_file():
            return False, "", f"Not a file: {script_path}"

        try:
            # Make script executable
            script_path.chmod(0o755)

            # Run script with timeout
            cmd = [str(script_path)] + (args or [])
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check,
            )

            success = result.returncode == 0
            return success, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            return False, "", f"Script timed out after {timeout}s"
        except Exception as e:
            return False, "", f"Error running script: {e}"

    async def start_gateway(self) -> Dict[str, Any]:
        """Start IBKR Gateway.

        Returns:
            Dictionary with success status and message
        """
        script = self.scripts_dir / "gateway" / "gateway.sh"
        logger.info("Starting IBKR Gateway via Telegram command")

        # Gateway startup can take 60+ seconds (authentication, etc.)
        success, stdout, stderr = self._run_script(
            script,
            args=["start"],
            timeout=120,
            check=False,
        )

        if success:
            # Check if actually running
            await asyncio.sleep(5)  # Give it a moment
            is_running = self._is_gateway_running()
            if is_running:
                return {
                    "success": True,
                    "message": "✅ IBKR Gateway started successfully",
                    "details": stdout.strip() if stdout else "Gateway process is running",
                }
            else:
                return {
                    "success": False,
                    "message": "⚠️ Gateway start command executed but process not detected",
                    "details": stdout.strip() if stdout else stderr.strip(),
                }
        else:
            return {
                "success": False,
                "message": "❌ Failed to start IBKR Gateway",
                "details": stderr.strip() if stderr else stdout.strip(),
            }

    async def stop_gateway(self) -> Dict[str, Any]:
        """Stop IBKR Gateway.

        Returns:
            Dictionary with success status and message
        """
        script = self.scripts_dir / "gateway" / "gateway.sh"
        logger.info("Stopping IBKR Gateway via Telegram command")

        success, stdout, stderr = self._run_script(
            script,
            args=["stop"],
            timeout=30,
            check=False,
        )

        # Verify it's stopped
        await asyncio.sleep(2)
        is_running = self._is_gateway_running()

        if not is_running:
            return {
                "success": True,
                "message": "✅ IBKR Gateway stopped successfully",
                "details": stdout.strip() if stdout else "Gateway process stopped",
            }
        else:
            return {
                "success": False,
                "message": "⚠️ Stop command executed but Gateway still running",
                "details": stderr.strip() if stderr else stdout.strip(),
            }

    def get_gateway_status(self) -> Dict[str, Any]:
        """Get IBKR Gateway status.

        Returns:
            Dictionary with gateway status information
        """
        is_running = self._is_gateway_running()
        port_listening = self._is_port_listening(4002)

        status = "RUNNING" if is_running else "STOPPED"
        api_status = "READY" if port_listening else "NOT_READY"

        return {
            "process_running": is_running,
            "port_listening": port_listening,
            "status": status,
            "api_status": api_status,
            "message": self._format_gateway_status(is_running, port_listening),
        }

    def _is_gateway_running(self) -> bool:
        """Check if Gateway process is running."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "java.*IBC.jar"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _is_port_listening(self, port: int) -> bool:
        """Check if a port is listening."""
        try:
            result = subprocess.run(
                ["ss", "-tuln"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return f":{port}" in result.stdout
        except Exception:
            # Fallback: try netstat or just return False
            try:
                result = subprocess.run(
                    ["netstat", "-tuln"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return f":{port}" in result.stdout
            except Exception:
                return False

    def _format_gateway_status(self, is_running: bool, port_listening: bool) -> str:
        """Format gateway status message."""
        if is_running and port_listening:
            return "🟢 Gateway is RUNNING and API is READY"
        elif is_running:
            return "🟡 Gateway is RUNNING but API not ready (may be authenticating)"
        else:
            return "🔴 Gateway is NOT RUNNING"

    async def start_agent(self, background: bool = True) -> Dict[str, Any]:
        """Start NQ Agent Service.

        Args:
            background: If True, start in background mode

        Returns:
            Dictionary with success status and message
        """
        script = self.scripts_dir / "lifecycle" / "start_nq_agent_service.sh"
        logger.info("Starting NQ Agent Service via Telegram command", extra={"background": background})

        # Check if already running
        if self._is_agent_running():
            return {
                "success": False,
                "message": "⚠️ NQ Agent Service is already running",
                "details": "Use /stop_agent first if you want to restart",
            }

        # Check if gateway is running (recommended but not required)
        gateway_status = self.get_gateway_status()
        if not gateway_status["process_running"]:
            # Still allow start, but warn
            logger.warning("Starting agent without Gateway running")

        # Run start script
        args = []
        if background:
            args = ["--background"]

        try:
            script_path = str(script)
            cmd = [script_path] + args

            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            success = result.returncode == 0

            # Verify it started
            await asyncio.sleep(3)
            is_running = self._is_agent_running()

            if is_running:
                return {
                    "success": True,
                    "message": "✅ NQ Agent Service started successfully",
                    "details": result.stdout.strip() if result.stdout else "Agent process is running",
                    "background": background,
                }
            else:
                return {
                    "success": False,
                    "message": "⚠️ Start command executed but agent not detected",
                    "details": result.stderr.strip() if result.stderr else result.stdout.strip(),
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "❌ Start command timed out",
                "details": "Script took too long to execute",
            }
        except Exception as e:
            return {
                "success": False,
                "message": "❌ Failed to start NQ Agent Service",
                "details": str(e),
            }

    async def stop_agent(self) -> Dict[str, Any]:
        """Stop NQ Agent Service.

        Returns:
            Dictionary with success status and message
        """
        script = self.scripts_dir / "lifecycle" / "stop_nq_agent_service.sh"
        logger.info("Stopping NQ Agent Service via Telegram command")

        if not self._is_agent_running():
            return {
                "success": False,
                "message": "⚠️ NQ Agent Service is not running",
                "details": "Nothing to stop",
            }

        success, stdout, stderr = self._run_script(script, timeout=30, check=False)

        # Verify it's stopped
        await asyncio.sleep(2)
        is_running = self._is_agent_running()

        if not is_running:
            return {
                "success": True,
                "message": "✅ NQ Agent Service stopped successfully",
                "details": stdout.strip() if stdout else "Agent process stopped",
            }
        else:
            return {
                "success": False,
                "message": "⚠️ Stop command executed but agent still running",
                "details": stderr.strip() if stderr else stdout.strip(),
            }

    def _is_agent_running(self) -> bool:
        """Check if Agent process is running."""
        try:
            # Check PID file first
            pid_file = self.project_root / "logs" / "nq_agent.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    # Check if process exists
                    result = subprocess.run(
                        ["ps", "-p", str(pid)],
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        return True
                except Exception:
                    pass

            # Fallback: check by process name
            result = subprocess.run(
                ["pgrep", "-f", "pearlalgo.nq_agent.main"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def is_agent_process_running(self) -> bool:
        """Public wrapper: check if Agent process is running."""
        return self._is_agent_running()

    def get_agent_status(self) -> Dict[str, Any]:
        """Get NQ Agent Service status.

        Returns:
            Dictionary with agent status information
        """
        is_running = self._is_agent_running()

        return {
            "running": is_running,
            "status": "RUNNING" if is_running else "STOPPED",
            "message": "🟢 Agent is RUNNING" if is_running else "🔴 Agent is STOPPED",
        }


    async def restart_agent(self, background: bool = True) -> Dict[str, Any]:
        """Restart NQ Agent Service (stop then start).

        Args:
            background: If True, start in background mode

        Returns:
            Dictionary with success status and message/details
        """
        logger.info("Restarting NQ Agent Service via Telegram command", extra={"background": background})

        stop_result = await self.stop_agent()
        # If it wasn't running, continue to start anyway
        if not stop_result.get("success") and "not running" not in str(stop_result.get("message", "")).lower():
            return {
                "success": False,
                "message": "❌ Failed to restart agent (stop step failed)",
                "details": stop_result.get("details") or stop_result.get("message"),
            }

        await asyncio.sleep(2)
        start_result = await self.start_agent(background=background)

        overall_success = bool(start_result.get("success"))
        message = "✅ Agent restarted successfully" if overall_success else "⚠️ Agent restart attempted but service not detected"
        details = "\n".join(
            [
                f"Stop: {stop_result.get('message', 'N/A')}",
                f"Start: {start_result.get('message', 'N/A')}",
            ]
        )
        if start_result.get("details"):
            details += f"\n{start_result['details']}"

        return {"success": overall_success, "message": message, "details": details}

    async def restart_gateway(self) -> Dict[str, Any]:
        """Restart IBKR Gateway (stop then start)."""
        logger.info("Restarting IBKR Gateway via Telegram command")

        stop_result = await self.stop_gateway()
        # If it wasn't running, continue to start anyway
        if not stop_result.get("success") and "not running" not in str(stop_result.get("message", "")).lower():
            return {
                "success": False,
                "message": "❌ Failed to restart gateway (stop step failed)",
                "details": stop_result.get("details") or stop_result.get("message"),
            }

        await asyncio.sleep(2)
        start_result = await self.start_gateway()

        overall_success = bool(start_result.get("success"))
        message = "✅ Gateway restarted successfully" if overall_success else "⚠️ Gateway restart attempted but process not detected"
        details = "\n".join(
            [
                f"Stop: {stop_result.get('message', 'N/A')}",
                f"Start: {start_result.get('message', 'N/A')}",
            ]
        )
        if start_result.get("details"):
            details += f"\n{start_result['details']}"

        return {"success": overall_success, "message": message, "details": details}

    async def restart_command_handler(self) -> Dict[str, Any]:
        """Restart Telegram command handler (stop then start)."""
        logger.info("Restarting Telegram command handler via Telegram command")
        script = self.scripts_dir / "telegram" / "restart_command_handler.sh"
        success, stdout, stderr = self._run_script(
            script,
            args=["--background"],
            timeout=60,
            check=False,
        )
        if success:
            return {
                "success": True,
                "message": "✅ Telegram command handler restarted successfully",
                "details": stdout.strip() if stdout else "Command handler restart executed",
            }
        return {
            "success": False,
            "message": "❌ Failed to restart Telegram command handler",
            "details": stderr.strip() if stderr else stdout.strip(),
        }

    def tail_log(self, log_filename: str, lines: int = 200) -> Dict[str, Any]:
        """Return the last N lines of a log file under ./logs (safe, read-only)."""
        try:
            logs_dir = (self.project_root / "logs").resolve()
            target = (logs_dir / log_filename).resolve()
            if logs_dir not in target.parents and target != logs_dir:
                return {"success": False, "message": "❌ Invalid log path", "details": "Log must be under ./logs"}
            if not target.exists():
                return {"success": False, "message": "❌ Log not found", "details": str(target)}
            if not target.is_file():
                return {"success": False, "message": "❌ Not a file", "details": str(target)}

            # Read last N lines efficiently
            with open(target, "r", errors="ignore") as f:
                all_lines = f.readlines()
            tail = "".join(all_lines[-max(1, int(lines)) :])
            return {"success": True, "message": f"📄 Tail of {log_filename}", "details": tail}
        except Exception as e:
            return {"success": False, "message": "❌ Failed to tail log", "details": str(e)}

    async def check_api_ready(self) -> Dict[str, Any]:
        """Check whether IBKR Gateway API is ready (script if present, else port probe)."""
        script = self.scripts_dir / "gateway" / "gateway.sh"
        if script.exists():
            success, stdout, stderr = self._run_script(script, args=["api-ready"], timeout=30, check=False)
            return {
                "success": success,
                "message": "🟢 API READY" if success else "🔴 API NOT READY",
                "details": (stdout.strip() if stdout else stderr.strip()),
            }

        # Fallback: port check
        port_listening = self._is_port_listening(4002)
        return {
            "success": port_listening,
            "message": "🟢 API READY" if port_listening else "🔴 API NOT READY",
            "details": "Checked TCP port 4002",
        }
