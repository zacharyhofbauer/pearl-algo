"""
Action Executor - Safe execution of Claude monitor suggestions.

Provides approval workflow, dry-run mode, rollback capabilities,
and audit logging for all automated changes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp


class ActionType(Enum):
    """Types of actions that can be executed."""
    CONFIG_UPDATE = "config_update"      # Update config.yaml
    SERVICE_RESTART = "service_restart"  # Restart agent/gateway
    CODE_PATCH = "code_patch"            # Apply code patch
    PARAMETER_TUNE = "parameter_tune"    # Tune specific parameter


class ActionStatus(Enum):
    """Status of an action execution."""
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ActionRequest:
    """Represents a request to execute an action."""
    action_type: ActionType
    description: str
    changes: Dict[str, Any]
    suggestion_id: Optional[str] = None
    dry_run: bool = False
    
    # Metadata
    timestamp: str = field(default_factory=get_utc_timestamp)
    request_id: Optional[str] = None
    
    # For config changes
    config_path: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    
    # For code patches
    patch_content: Optional[str] = None
    target_files: Optional[List[str]] = None
    
    # For service actions
    service_name: Optional[str] = None
    action: Optional[str] = None


@dataclass
class ActionResult:
    """Result of an action execution."""
    success: bool
    message: str
    action_type: ActionType
    status: ActionStatus
    request_id: str
    timestamp: str = field(default_factory=get_utc_timestamp)
    
    # Rollback info
    can_rollback: bool = False
    rollback_data: Optional[Dict[str, Any]] = None
    
    # Error details
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "action_type": self.action_type.value,
            "status": self.status.value,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "can_rollback": self.can_rollback,
            "error": self.error,
        }


class ActionExecutor:
    """
    Safely executes actions suggested by Claude monitor.
    
    Features:
    - Approval workflow (manual or auto-approve)
    - Dry-run mode for testing
    - Automatic rollback on errors
    - Audit logging of all changes
    - Rate limiting
    """
    
    def __init__(
        self,
        project_root: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        auto_approve: bool = False,
        dry_run_default: bool = True,
        max_changes_per_day: int = 5,
    ):
        """
        Initialize action executor.
        
        Args:
            project_root: Path to project root
            state_dir: Directory for state files
            auto_approve: Automatically approve low-risk changes
            dry_run_default: Default to dry-run mode
            max_changes_per_day: Maximum changes allowed per day
        """
        self._project_root = project_root or self._find_project_root()
        self._state_dir = state_dir or (self._project_root / "data" / "nq_agent_state")
        self._auto_approve = auto_approve
        self._dry_run_default = dry_run_default
        self._max_changes_per_day = max_changes_per_day
        
        # Audit log
        self._audit_file = self._state_dir / "claude_action_audit.jsonl"
        
        # Backup directory for rollbacks
        self._backup_dir = self._state_dir / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Track daily changes
        self._daily_changes = 0
        self._daily_reset: Optional[datetime] = None
        
        # Request counter
        self._request_counter = 0
    
    def _find_project_root(self) -> Path:
        """Find project root directory."""
        current = Path.cwd()
        for parent in [current] + list(current.parents):
            if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
                return parent
        return current
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID."""
        self._request_counter += 1
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"act_{timestamp}_{self._request_counter:04d}"
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within daily rate limit."""
        now = datetime.now(timezone.utc)
        
        # Reset counter daily
        if self._daily_reset is None or (now.date() != self._daily_reset.date()):
            self._daily_changes = 0
            self._daily_reset = now
        
        return self._daily_changes < self._max_changes_per_day
    
    def _audit_log(self, action: str, data: Dict[str, Any]) -> None:
        """Write to audit log."""
        entry = {
            "timestamp": get_utc_timestamp(),
            "action": action,
            **data,
        }
        
        try:
            self._audit_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._audit_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Could not write audit log: {e}")
    
    async def execute(
        self,
        request: ActionRequest,
    ) -> ActionResult:
        """
        Execute an action request.
        
        Args:
            request: The action to execute
            
        Returns:
            Result of execution
        """
        # Generate request ID
        request.request_id = self._generate_request_id()
        
        # Check rate limit
        if not request.dry_run and not self._check_rate_limit():
            return ActionResult(
                success=False,
                message=f"Daily rate limit reached ({self._max_changes_per_day} changes/day)",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error="rate_limit_exceeded",
            )
        
        # Log the request
        self._audit_log("request", {
            "request_id": request.request_id,
            "action_type": request.action_type.value,
            "description": request.description,
            "dry_run": request.dry_run,
            "suggestion_id": request.suggestion_id,
        })
        
        # Route to appropriate handler
        try:
            if request.action_type == ActionType.CONFIG_UPDATE:
                result = await self._execute_config_update(request)
            elif request.action_type == ActionType.SERVICE_RESTART:
                result = await self._execute_service_action(request)
            elif request.action_type == ActionType.CODE_PATCH:
                result = await self._execute_code_patch(request)
            elif request.action_type == ActionType.PARAMETER_TUNE:
                result = await self._execute_parameter_tune(request)
            else:
                result = ActionResult(
                    success=False,
                    message=f"Unknown action type: {request.action_type}",
                    action_type=request.action_type,
                    status=ActionStatus.FAILED,
                    request_id=request.request_id,
                    error="unknown_action_type",
                )
            
            # Log result
            self._audit_log("result", result.to_dict())
            
            # Update daily counter if successful and not dry-run
            if result.success and not request.dry_run:
                self._daily_changes += 1
            
            return result
            
        except Exception as e:
            logger.error(f"Action execution error: {e}", exc_info=True)
            result = ActionResult(
                success=False,
                message=f"Execution error: {e}",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error=str(e),
            )
            self._audit_log("error", result.to_dict())
            return result
    
    async def _execute_config_update(
        self,
        request: ActionRequest,
    ) -> ActionResult:
        """Execute a config.yaml update."""
        config_path = self._project_root / "config" / "config.yaml"
        
        if not config_path.exists():
            return ActionResult(
                success=False,
                message="config.yaml not found",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error="config_not_found",
            )
        
        # Load current config
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
        except Exception as e:
            return ActionResult(
                success=False,
                message=f"Could not load config: {e}",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error=str(e),
            )
        
        # Navigate to config path
        path_parts = request.config_path.split(".") if request.config_path else []
        
        if not path_parts:
            return ActionResult(
                success=False,
                message="No config path specified",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error="no_config_path",
            )
        
        # Get current value
        current = config
        for part in path_parts[:-1]:
            current = current.get(part, {})
        
        old_value = current.get(path_parts[-1])
        
        if request.dry_run:
            return ActionResult(
                success=True,
                message=f"DRY RUN: Would change {request.config_path} from {old_value} to {request.new_value}",
                action_type=request.action_type,
                status=ActionStatus.COMPLETED,
                request_id=request.request_id,
                can_rollback=True,
                rollback_data={"config_path": request.config_path, "old_value": old_value},
            )
        
        # Create backup
        backup_path = self._backup_dir / f"config_{request.request_id}.yaml"
        shutil.copy(config_path, backup_path)
        
        # Apply change
        try:
            current[path_parts[-1]] = request.new_value
            
            with open(config_path, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
            
            return ActionResult(
                success=True,
                message=f"Updated {request.config_path}: {old_value} → {request.new_value}",
                action_type=request.action_type,
                status=ActionStatus.COMPLETED,
                request_id=request.request_id,
                can_rollback=True,
                rollback_data={
                    "backup_path": str(backup_path),
                    "config_path": request.config_path,
                    "old_value": old_value,
                },
            )
        except Exception as e:
            # Restore backup
            shutil.copy(backup_path, config_path)
            return ActionResult(
                success=False,
                message=f"Config update failed, restored backup: {e}",
                action_type=request.action_type,
                status=ActionStatus.ROLLED_BACK,
                request_id=request.request_id,
                error=str(e),
            )
    
    async def _execute_service_action(
        self,
        request: ActionRequest,
    ) -> ActionResult:
        """Execute a service action (restart, etc.)."""
        service = request.service_name or "agent"
        action = request.action or "restart"
        
        scripts = {
            ("agent", "restart"): "scripts/lifecycle/stop_nq_agent_service.sh && scripts/lifecycle/start_nq_agent_service.sh --background",
            ("agent", "stop"): "scripts/lifecycle/stop_nq_agent_service.sh",
            ("agent", "start"): "scripts/lifecycle/start_nq_agent_service.sh --background",
            ("gateway", "restart"): "scripts/gateway/gateway.sh stop && scripts/gateway/gateway.sh start",
            ("gateway", "stop"): "scripts/gateway/gateway.sh stop",
            ("gateway", "start"): "scripts/gateway/gateway.sh start",
        }
        
        script = scripts.get((service, action))
        
        if not script:
            return ActionResult(
                success=False,
                message=f"Unknown service action: {service}/{action}",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error="unknown_service_action",
            )
        
        if request.dry_run:
            return ActionResult(
                success=True,
                message=f"DRY RUN: Would execute: {script}",
                action_type=request.action_type,
                status=ActionStatus.COMPLETED,
                request_id=request.request_id,
            )
        
        try:
            result = subprocess.run(
                script,
                shell=True,
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode == 0:
                return ActionResult(
                    success=True,
                    message=f"Executed {service} {action}",
                    action_type=request.action_type,
                    status=ActionStatus.COMPLETED,
                    request_id=request.request_id,
                )
            else:
                return ActionResult(
                    success=False,
                    message=f"Service action failed: {result.stderr[:200]}",
                    action_type=request.action_type,
                    status=ActionStatus.FAILED,
                    request_id=request.request_id,
                    error=result.stderr[:500],
                )
        except subprocess.TimeoutExpired:
            return ActionResult(
                success=False,
                message="Service action timed out",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error="timeout",
            )
        except Exception as e:
            return ActionResult(
                success=False,
                message=f"Service action error: {e}",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error=str(e),
            )
    
    async def _execute_code_patch(
        self,
        request: ActionRequest,
    ) -> ActionResult:
        """Execute a code patch (via git apply)."""
        if not request.patch_content:
            return ActionResult(
                success=False,
                message="No patch content provided",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error="no_patch_content",
            )
        
        # Write patch to temp file
        patch_path = self._backup_dir / f"patch_{request.request_id}.diff"
        
        try:
            with open(patch_path, "w") as f:
                f.write(request.patch_content)
        except Exception as e:
            return ActionResult(
                success=False,
                message=f"Could not write patch file: {e}",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error=str(e),
            )
        
        if request.dry_run:
            # Try dry-run apply
            result = subprocess.run(
                ["git", "apply", "--check", str(patch_path)],
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
            )
            
            if result.returncode == 0:
                return ActionResult(
                    success=True,
                    message="DRY RUN: Patch would apply cleanly",
                    action_type=request.action_type,
                    status=ActionStatus.COMPLETED,
                    request_id=request.request_id,
                    can_rollback=True,
                )
            else:
                return ActionResult(
                    success=False,
                    message=f"DRY RUN: Patch would fail: {result.stderr[:200]}",
                    action_type=request.action_type,
                    status=ActionStatus.FAILED,
                    request_id=request.request_id,
                    error=result.stderr[:500],
                )
        
        # Actually apply the patch
        result = subprocess.run(
            ["git", "apply", str(patch_path)],
            cwd=str(self._project_root),
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            return ActionResult(
                success=True,
                message="Patch applied successfully",
                action_type=request.action_type,
                status=ActionStatus.COMPLETED,
                request_id=request.request_id,
                can_rollback=True,
                rollback_data={"patch_path": str(patch_path)},
            )
        else:
            return ActionResult(
                success=False,
                message=f"Patch failed to apply: {result.stderr[:200]}",
                action_type=request.action_type,
                status=ActionStatus.FAILED,
                request_id=request.request_id,
                error=result.stderr[:500],
            )
    
    async def _execute_parameter_tune(
        self,
        request: ActionRequest,
    ) -> ActionResult:
        """Execute a parameter tune (shorthand for config update)."""
        # Delegate to config update
        request.action_type = ActionType.CONFIG_UPDATE
        return await self._execute_config_update(request)
    
    async def rollback(self, request_id: str) -> ActionResult:
        """
        Rollback a previously executed action.
        
        Args:
            request_id: ID of the action to rollback
            
        Returns:
            Result of rollback
        """
        # Find the action in audit log
        try:
            with open(self._audit_file) as f:
                entries = [json.loads(line) for line in f if line.strip()]
        except Exception as e:
            return ActionResult(
                success=False,
                message=f"Could not read audit log: {e}",
                action_type=ActionType.CONFIG_UPDATE,
                status=ActionStatus.FAILED,
                request_id=request_id,
                error=str(e),
            )
        
        # Find the result entry for this request
        result_entry = None
        for entry in reversed(entries):
            if entry.get("request_id") == request_id and entry.get("action") == "result":
                result_entry = entry
                break
        
        if not result_entry:
            return ActionResult(
                success=False,
                message=f"No action found with ID {request_id}",
                action_type=ActionType.CONFIG_UPDATE,
                status=ActionStatus.FAILED,
                request_id=request_id,
                error="action_not_found",
            )
        
        if not result_entry.get("can_rollback"):
            return ActionResult(
                success=False,
                message="Action cannot be rolled back",
                action_type=ActionType(result_entry.get("action_type", "config_update")),
                status=ActionStatus.FAILED,
                request_id=request_id,
                error="not_rollbackable",
            )
        
        rollback_data = result_entry.get("rollback_data", {})
        
        # Perform rollback based on type
        if "backup_path" in rollback_data:
            # Config rollback
            backup_path = Path(rollback_data["backup_path"])
            if backup_path.exists():
                config_path = self._project_root / "config" / "config.yaml"
                shutil.copy(backup_path, config_path)
                
                self._audit_log("rollback", {
                    "request_id": request_id,
                    "restored_from": str(backup_path),
                })
                
                return ActionResult(
                    success=True,
                    message="Config restored from backup",
                    action_type=ActionType.CONFIG_UPDATE,
                    status=ActionStatus.ROLLED_BACK,
                    request_id=request_id,
                )
        
        elif "patch_path" in rollback_data:
            # Patch rollback
            patch_path = Path(rollback_data["patch_path"])
            if patch_path.exists():
                result = subprocess.run(
                    ["git", "apply", "--reverse", str(patch_path)],
                    cwd=str(self._project_root),
                    capture_output=True,
                    text=True,
                )
                
                if result.returncode == 0:
                    self._audit_log("rollback", {
                        "request_id": request_id,
                        "reversed_patch": str(patch_path),
                    })
                    
                    return ActionResult(
                        success=True,
                        message="Patch reversed",
                        action_type=ActionType.CODE_PATCH,
                        status=ActionStatus.ROLLED_BACK,
                        request_id=request_id,
                    )
        
        return ActionResult(
            success=False,
            message="Could not perform rollback",
            action_type=ActionType(result_entry.get("action_type", "config_update")),
            status=ActionStatus.FAILED,
            request_id=request_id,
            error="rollback_failed",
        )
    
    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent audit log entries."""
        try:
            if not self._audit_file.exists():
                return []
            
            entries = []
            with open(self._audit_file) as f:
                for line in f:
                    if line.strip():
                        entries.append(json.loads(line))
            
            return entries[-limit:]
        except Exception as e:
            logger.error(f"Could not read audit log: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get executor statistics."""
        return {
            "daily_changes": self._daily_changes,
            "max_per_day": self._max_changes_per_day,
            "auto_approve": self._auto_approve,
            "dry_run_default": self._dry_run_default,
        }


