"""
Execution Control Flags — extracted from service.py for readability.

Contains the _check_execution_control_flags logic as a standalone async function
that operates on a MarketAgentService instance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pearlalgo.market_agent.notification_queue import Priority
from pearlalgo.utils.logger import logger

if TYPE_CHECKING:
    pass  # MarketAgentService would create a circular import


async def check_execution_control_flags(svc: "object") -> None:  # noqa: C901
    """
    Check for execution control flag files (from Telegram commands).

    Flag files:
    - arm_request.flag: Arm the execution adapter
    - disarm_request.flag: Disarm the execution adapter
    - kill_request.flag: Disarm, cancel all orders, flatten positions, and close virtual trades

    Safety features:
    - Flags older than FLAG_TTL_SECONDS are ignored and deleted (prevents stale flags)
    - Flags are always cleared even when execution_adapter is None (prevents accumulation)

    ``svc`` is the MarketAgentService instance.
    """
    FLAG_TTL_SECONDS = 300  # 5 minutes - ignore flags older than this

    def _is_flag_stale(flag_file: Path) -> bool:
        """Check if a flag file is stale (older than TTL)."""
        try:
            content = flag_file.read_text()
            # Parse timestamp from "xxx_requested_at=2025-01-01T00:00:00+00:00"
            if "requested_at=" in content:
                ts_str = content.split("requested_at=")[1].strip()
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
                return age_seconds > FLAG_TTL_SECONDS
            # If no timestamp, check file modification time
            mtime = datetime.fromtimestamp(flag_file.stat().st_mtime, tz=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - mtime).total_seconds()
            return age_seconds > FLAG_TTL_SECONDS
        except Exception as e:
            logger.warning(f"Failed to determine flag staleness in execution control: {e}")
            # If we can't determine age, treat as stale for safety
            return True

    try:
        state_dir = svc.state_manager.state_dir

        # ==========================================================================
        # Resume request (web API / manual) — checked every cycle including when paused
        # ==========================================================================
        resume_file = state_dir / "resume_request.flag"
        if resume_file.exists():
            svc.resume()
            resume_file.unlink(missing_ok=True)
            logger.info("Resumed from resume_request.flag")

        # ==========================================================================
        # Process operator requests (web UI feedback, shadow-only)
        # ==========================================================================
        try:
            await svc.operator_handler.process_operator_requests(state_dir)
        except Exception as e:
            logger.debug(f"Operator requests processing failed (non-fatal): {e}")

        # ==========================================================================
        # Ingest close-trade requests & close-all flag from web API
        # ==========================================================================
        try:
            await svc.operator_handler.process_close_trade_requests(state_dir)
        except Exception as e:
            logger.debug(f"Close-trade request ingestion failed (non-fatal): {e}")
        try:
            await svc.operator_handler.process_close_all_flag(state_dir)
        except Exception as e:
            logger.debug(f"Close-all flag ingestion failed (non-fatal): {e}")

        # Define flag files
        kill_file = state_dir / "kill_request.flag"
        disarm_file = state_dir / "disarm_request.flag"
        arm_file = state_dir / "arm_request.flag"

        # ==========================================================================
        # Always clear stale flags (prevents accumulation when adapter is disabled)
        # ==========================================================================
        for flag_file in [kill_file, disarm_file, arm_file]:
            if flag_file.exists() and _is_flag_stale(flag_file):
                logger.warning(f"Clearing stale flag file: {flag_file.name} (older than {FLAG_TTL_SECONDS}s)")
                flag_file.unlink(missing_ok=True)

        # Use last known market data for close/flatten helpers (best-effort).
        last_market_data = getattr(svc.data_fetcher, "_last_market_data", None) or {}
        if not isinstance(last_market_data, dict):
            last_market_data = {}

        # ==========================================================================
        # If execution adapter is None, clear any remaining flags and warn
        # ==========================================================================
        if svc.execution_adapter is None:
            # Kill switch still closes virtual trades even if execution is disabled.
            if kill_file.exists():
                logger.warning("🚨 KILL flag detected but execution adapter is disabled - closing virtual trades only")
                closed_virtual = 0
                close_err: Optional[str] = None
                try:
                    closed_virtual, _ = await svc._close_all_virtual_trades(
                        market_data=last_market_data,
                        reason="kill_switch",
                        notify=False,
                    )
                except Exception as e:
                    close_err = str(e)
                    logger.error(f"Kill switch (no execution adapter): failed to close virtual trades: {e}", exc_info=True)
                finally:
                    kill_file.unlink(missing_ok=True)

                try:
                    err_note = f"\n⚠️ Close error: `{close_err[:80]}`" if close_err else ""
                    await svc.notification_queue.enqueue_raw_message(
                        "🚨 *KILL SWITCH EXECUTED*\n\n"
                        "Execution adapter: `DISABLED`\n"
                        f"Closed Trades: `{closed_virtual}` (virtual){err_note}",
                        parse_mode="Markdown",
                        priority=Priority.CRITICAL,
                        dedupe=False,
                    )
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

            # Arm/disarm are execution-only; clear + warn if requested.
            for flag_file, action in [(disarm_file, "disarm"), (arm_file, "arm")]:
                if flag_file.exists():
                    logger.warning(
                        f"Clearing {action} flag - execution adapter is disabled. "
                        f"Enable execution.enabled in config to use /arm, /disarm, /kill commands."
                    )
                    flag_file.unlink(missing_ok=True)
                    # Notify user that the command was ignored (through notification queue)
                    try:
                        await svc.notification_queue.enqueue_raw_message(
                            f"⚠️ *{action.upper()} IGNORED*\n\n"
                            f"Execution adapter is disabled.\n"
                            f"Set `execution.enabled: true` in config and restart to enable ATS.",
                            parse_mode="Markdown",
                            priority=Priority.NORMAL,
                        )
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")
            return

        # ==========================================================================
        # Process kill flag (highest priority)
        # ==========================================================================
        if kill_file.exists():
            logger.warning("🚨 KILL flag detected - cancelling orders, flattening positions, and disarming")
            cancelled_order_ids: list[str] = []
            cancel_errors: list[str] = []
            flattened_order_ids: list[str] = []
            flatten_errors: list[str] = []
            closed_virtual = 0
            close_virtual_err: Optional[str] = None
            try:
                # SAFETY: Disarm FIRST to prevent new orders while cancelling
                svc.execution_adapter.disarm()
                logger.warning("Kill switch: execution adapter disarmed")

                # Cancel all open orders
                cancel_results = await svc.execution_adapter.cancel_all()
                cancelled_order_ids = [
                    str(r.order_id) for r in cancel_results
                    if r.success and r.order_id
                ]
                cancel_errors = [r.error_message for r in cancel_results if not r.success and r.error_message]
                logger.warning(f"Kill switch: cancelled {len(cancelled_order_ids)} orders")
                if cancel_errors:
                    logger.warning(f"Kill switch: {len(cancel_errors)} cancellation errors: {cancel_errors[:3]}")

                # Flatten open broker positions (market orders)
                flatten_results = await svc.execution_adapter.flatten_all_positions()
                flattened_order_ids = [
                    str(r.order_id) for r in flatten_results
                    if r.success and r.order_id
                ]
                flatten_errors = [r.error_message for r in flatten_results if not r.success and r.error_message]
                logger.warning(f"Kill switch: submitted {len(flattened_order_ids)} flatten order(s)")
                if flatten_errors:
                    logger.warning(f"Kill switch: {len(flatten_errors)} flatten errors: {flatten_errors[:3]}")
            except Exception as e:
                logger.error(f"Error executing kill switch: {e}", exc_info=True)
                # Even if cancel_all fails, ensure we're disarmed
                try:
                    svc.execution_adapter.disarm()
                except Exception as e:
                    logger.warning(f"Critical path error: {e}", exc_info=True)
            finally:
                kill_file.unlink(missing_ok=True)
                # Also remove any pending disarm flag (kill already disarms)
                disarm_file.unlink(missing_ok=True)

            # Close all virtual trades (best-effort; uses last known market data)
            try:
                closed_virtual, _ = await svc._close_all_virtual_trades(
                    market_data=last_market_data,
                    reason="kill_switch",
                    notify=False,
                )
            except Exception as e:
                close_virtual_err = str(e)
                logger.error(f"Kill switch: failed to close virtual trades: {e}", exc_info=True)

            # Notify via Telegram (through notification queue)
            try:
                errors_total = len(cancel_errors) + len(flatten_errors) + (1 if close_virtual_err else 0)
                error_note = f"\n⚠️ Errors: {errors_total}" if errors_total else ""
                first_err = None
                if cancel_errors:
                    first_err = cancel_errors[0]
                elif flatten_errors:
                    first_err = flatten_errors[0]
                elif close_virtual_err:
                    first_err = close_virtual_err
                first_err_note = f"\n`{str(first_err)[:80]}`" if first_err else ""
                await svc.notification_queue.enqueue_raw_message(
                    f"🚨 *KILL SWITCH EXECUTED*\n\n"
                    f"Cancelled Orders: `{len(cancelled_order_ids)}`\n"
                    f"Flattened Positions: `{len(flattened_order_ids)}`\n"
                    f"Closed Trades: `{closed_virtual}` (virtual)\n"
                    f"Execution: `DISARMED`{error_note}{first_err_note}",
                    parse_mode="Markdown",
                    priority=Priority.CRITICAL,
                    dedupe=False,
                )
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
            return  # Skip arm/disarm after kill

        # ==========================================================================
        # Process disarm flag
        # ==========================================================================
        if disarm_file.exists():
            logger.info("🔒 DISARM flag detected - disarming execution adapter")
            svc.execution_adapter.disarm()
            disarm_file.unlink(missing_ok=True)
            # Persist armed-state change immediately so dashboard/API reflect it.
            svc.mark_state_dirty()
            svc._save_state(force=True)

            # Notify via Telegram (through notification queue)
            try:
                await svc.notification_queue.enqueue_raw_message(
                    "🔒 *Execution DISARMED*\n\n"
                    "No new orders will be placed.",
                    parse_mode="Markdown",
                    priority=Priority.HIGH,
                )
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
            return  # Skip arm after disarm

        # ==========================================================================
        # Process arm flag
        # ==========================================================================
        if arm_file.exists():
            logger.info("🔫 ARM flag detected - arming execution adapter")
            success = svc.execution_adapter.arm()
            arm_file.unlink(missing_ok=True)
            # Persist armed-state change immediately so dashboard/API reflect it.
            svc.mark_state_dirty()
            svc._save_state(force=True)

            if success:
                # Notify via Telegram (through notification queue)
                try:
                    mode = svc._execution_config.mode.value if svc._execution_config else "unknown"
                    await svc.notification_queue.enqueue_raw_message(
                        f"🔫 *Execution ARMED*\n\n"
                        f"Mode: `{mode}`\n"
                        f"Orders will be placed for signals.\n\n"
                        f"⚠️ Use `/disarm` to stop or `/kill` to cancel all.",
                        parse_mode="Markdown",
                        priority=Priority.HIGH,
                    )
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")
            else:
                logger.warning("Could not arm execution adapter - preconditions not met")
                try:
                    await svc.notification_queue.enqueue_raw_message(
                        "⚠️ *ARM FAILED*\n\n"
                        "Could not arm execution adapter.\n"
                        "Check that execution is enabled in config.",
                        parse_mode="Markdown",
                        priority=Priority.HIGH,
                    )
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

        # ==========================================================================
        # Process grade request (manual operator feedback log)
        # ==========================================================================
        grade_file = state_dir / "grade_request.json"
        if grade_file.exists():
            await svc.operator_handler.process_grade_request(grade_file)

    except Exception as e:
        logger.error(f"Error checking execution control flags: {e}", exc_info=True)
