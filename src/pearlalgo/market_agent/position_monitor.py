"""
Position Monitor — extracted from service.py for readability.

Contains the _monitor_open_position logic as a standalone async function
that operates on a MarketAgentService instance.
"""

from __future__ import annotations

import logging
import time as _time_mod
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional

import pytz

from pearlalgo.execution.advanced_exit_manager import AdvancedExitManager
from pearlalgo.market_agent.notification_queue import NotificationTier, Priority
from pearlalgo.utils.logger import logger

_ET = pytz.timezone("America/New_York")

if TYPE_CHECKING:
    pass  # MarketAgentService would create a circular import


async def monitor_open_position(svc: "object", market_data: Dict) -> None:  # noqa: C901
    """Log real-time metrics for open positions: unrealized P&L, distance to stop/TP, MFE/MAE.
    Also triggers trailing stop updates when enabled.

    ``svc`` is the MarketAgentService instance (passed as first arg so
    this function can be a simple delegation target).
    """
    if svc.execution_adapter is None:
        return

    # ── Periodic REST API position sync (every 30s) ──
    # CRITICAL: WebSocket _live_positions cache can drift from reality.
    # This ensures the agent always knows the REAL position state from Tradovate.
    _now = _time_mod.monotonic()
    _sync_interval = getattr(svc, '_position_sync_interval', 30)
    _last_sync = getattr(svc, '_last_position_sync_time', 0)
    if _now - _last_sync >= _sync_interval:
        svc._last_position_sync_time = _now
        try:
            await svc.execution_adapter.get_positions(force_rest=True)
        except Exception as _sync_err:
            logging.getLogger(__name__).debug(
                f"Position sync failed (non-fatal): {_sync_err}"
            )

    # Get broker positions from adapter cache OR virtual positions from signals
    positions = getattr(svc.execution_adapter, '_live_positions', {})
    if not positions:
        # Fallback: check virtual positions (signals.jsonl status=entered)
        try:
            active = svc.virtual_trade_manager.position_tracker.get_active_virtual_trades(limit=5)
            if active:
                # Synthesize a position-like dict from the active signal
                for sig_rec in active:
                    sig = sig_rec.get('signal') or sig_rec or {}
                    d = str(sig.get('direction') or 'long').lower()
                    ep = float(sig.get('entry_price') or 0)
                    if ep > 0:
                        positions = {'virtual': {
                            'net_pos': 1 if d == 'long' else -1,
                            'net_price': ep,
                        }}
                        break
        except Exception:
            pass
    if not positions:
        # No open position — reset monitor state
        if getattr(svc, '_pos_monitor', None):
            # Clean up trailing stop state for the closed position
            if svc._trailing_stop_manager:
                for pid in list(svc._trailing_stop_manager._states.keys()):
                    svc._trailing_stop_manager.remove_position(pid)
                    logger.debug(f"Trailing stop: cleaned up state for closed position {pid}")
            if svc._runner_manager:
                for pid in list(svc._runner_manager._states.keys()):
                    svc._runner_manager.remove_position(pid)
                    logger.debug(f"Runner: cleaned up state for closed position {pid}")
            svc._pos_monitor = None
            svc._last_broker_stop = None
            svc._stop_order_miss_count = 0
        return

    # Get current price from market data
    latest_bar = market_data.get('latest_bar') or {}
    current_price = float(latest_bar.get('close') or latest_bar.get('last') or 0)
    if current_price <= 0:
        return

    for _cid, pos_info in positions.items():
        net_pos = pos_info.get('net_pos', 0)
        if net_pos == 0:
            continue

        direction = 'long' if net_pos > 0 else 'short'
        entry_price = float(pos_info.get('net_price', 0))
        if entry_price <= 0:
            continue

        # Initialize or update monitor state
        if not getattr(svc, '_pos_monitor', None) or svc._pos_monitor.get('entry_price') != entry_price:
            svc._pos_monitor = {
                'entry_price': entry_price,
                'direction': direction,
                'max_price': current_price,
                'min_price': current_price,
                'entry_time': datetime.now(_ET).replace(tzinfo=None),  # FIXED 2026-03-25: store ET not UTC
                'log_counter': 0,
            }
            # Register with trailing stop manager for new positions
            if svc._trailing_stop_manager and svc._trailing_stop_manager.enabled:
                # Try broker stop orders first, then virtual trades, then ATR-based default
                current_atr = svc._get_current_atr(market_data)
                stop_px = await svc._find_initial_stop_from_broker(direction, entry_price, current_atr)
                if stop_px == 0:
                    # Fallback to virtual trade stop if broker query failed
                    stop_px = svc._find_initial_stop_price(direction)
                if stop_px > 0:
                    svc._trailing_stop_manager.register_position(
                        position_id=str(_cid),
                        entry_price=entry_price,
                        direction=direction,
                        initial_stop=stop_px,
                    )
                    logger.info(f"✅ Registered position {_cid} with trailing stop manager: entry=${entry_price:.2f}, stop=${stop_px:.2f}")
                else:
                    logger.warning(f"⚠️ Could not find stop price for position {_cid}, trailing stop not registered")

            # Register with runner manager for new positions
            if svc._runner_manager and svc._runner_manager.enabled:
                current_atr = svc._get_current_atr(market_data)
                if current_atr > 0:
                    svc._runner_manager.register_position(
                        position_id=str(_cid),
                        entry_price=entry_price,
                        direction=direction,
                        atr=current_atr,
                    )
                    logger.info(
                        f"Runner registered: pos={_cid} entry=${entry_price:.2f} "
                        f"dir={direction} atr={current_atr:.2f}"
                    )

        mon = svc._pos_monitor
        mon['max_price'] = max(mon['max_price'], current_price)
        mon['min_price'] = min(mon['min_price'], current_price)

        # Compute unrealized P&L
        if direction == 'long':
            unrealized_pnl = (current_price - entry_price) * 2.0 * abs(net_pos)  # MNQ /pt
            mfe = mon['max_price'] - entry_price
            mae = entry_price - mon['min_price']
        else:
            unrealized_pnl = (entry_price - current_price) * 2.0 * abs(net_pos)
            mfe = entry_price - mon['min_price']
            mae = mon['max_price'] - entry_price

        # Find stop/TP from active signals via virtual trade manager
        stop_price = 0.0
        tp_price = 0.0
        try:
            active = svc.virtual_trade_manager.position_tracker.get_active_virtual_trades(limit=5)
            for sig_rec in (active or []):
                sig = sig_rec.get('signal') or sig_rec or {}
                if sig.get('direction', '').lower() == direction:
                    stop_price = float(sig.get('stop_loss') or 0)
                    tp_price = float(sig.get('take_profit') or 0)
                    break
        except Exception:
            pass

        # === Runner Mode: progressive stop management (replaces trailing stop phases) ===
        _runner_active = svc._runner_manager and svc._runner_manager.enabled
        if _runner_active:
            try:
                action, new_stop, cancel_tp = svc._runner_manager.update_position(
                    str(_cid), current_price
                )
                if action is not None:
                    # Modify stop loss on broker
                    if new_stop is not None:
                        stop_order_id = await svc._find_stop_order_id(direction)
                        if stop_order_id:
                            success = await svc.execution_adapter.modify_stop_order(
                                stop_order_id, new_stop
                            )
                            if success:
                                svc._last_broker_stop = new_stop
                                logger.info(f"Runner [{action}]: SL moved to {new_stop:.2f}")
                            else:
                                logger.warning(f"Runner [{action}]: modify_stop_order failed for order {stop_order_id}")
                        else:
                            logger.warning(f"Runner [{action}]: could not find stop order to modify")

                    # Cancel TP order if runner phase requires it
                    if cancel_tp:
                        tp_order_id = await svc._find_tp_order_id(direction)
                        if tp_order_id:
                            result = await svc.execution_adapter.cancel_order(str(tp_order_id))
                            if result.success:
                                logger.info(f"Runner: TP order {tp_order_id} cancelled — letting winner run")
                            else:
                                logger.warning(f"Runner: failed to cancel TP order {tp_order_id}")
                        else:
                            logger.debug("Runner: no TP order found to cancel (may already be cancelled)")
            except Exception as e:
                logger.warning(f"Runner mode update failed: {e}")

        # Trailing stop check (with override file IPC + regime presets)
        # Skipped when runner mode is active — runner manages SL progression
        if not _runner_active and svc._trailing_stop_manager and svc._trailing_stop_manager.enabled:
            try:
                current_atr = svc._get_current_atr(market_data)
                if current_atr > 0:
                    # Check for external override file (OpenClaw / operator)
                    svc._ingest_trailing_stop_override()

                    # Apply regime-adaptive preset if no external override
                    svc._apply_regime_trailing_preset(market_data)

                    new_stop = svc._trailing_stop_manager.check_and_update(
                        position_id=str(_cid),
                        current_price=current_price,
                        current_atr=current_atr,
                    )

                    # Also retry if broker stop is out of sync with internal stop
                    ts_state = svc._trailing_stop_manager.get_state(str(_cid))
                    if new_stop is None and ts_state and ts_state.get("current_phase"):
                        last_broker = getattr(svc, '_last_broker_stop', None)
                        internal_stop = ts_state["current_stop"]
                        if last_broker is None or abs(internal_stop - last_broker) > 0.25:
                            new_stop = internal_stop
                            logger.info(f"Trailing stop: retrying broker sync (internal={internal_stop:.2f}, last_broker={last_broker})")

                    if new_stop is not None:
                        stop_order_id = await svc._find_stop_order_id(direction)
                        if stop_order_id:
                            logger.info(f"Trailing stop: modifying order {stop_order_id} to {new_stop:.2f}")
                            success = await svc.execution_adapter.modify_stop_order(
                                stop_order_id, new_stop
                            )
                            if success:
                                svc._last_broker_stop = new_stop
                                svc._stop_order_miss_count = 0
                                logger.info(f"Trailing stop moved to {new_stop:.2f}")
                            else:
                                logger.warning(f"Trailing stop: modify_stop_order returned False for order {stop_order_id}")
                        else:
                            miss_count = getattr(svc, '_stop_order_miss_count', 0) + 1
                            svc._stop_order_miss_count = miss_count
                            if miss_count <= 3:
                                logger.warning(f"Trailing stop: could not find stop order for {direction} position to move to {new_stop:.2f} (miss {miss_count}/3)")
                            if miss_count == 3:
                                # After 3 misses, attempt to re-place the stop order
                                logger.warning(f"Trailing stop: 3 consecutive misses — attempting to re-place stop at {new_stop:.2f}")
                                try:
                                    qty = abs(net_pos)
                                    stop_action = "Sell" if direction == "long" else "Buy"
                                    placed = await svc.execution_adapter.place_stop_order(
                                        symbol=svc.config.get("symbol", "MNQ"),
                                        action=stop_action,
                                        quantity=qty,
                                        stop_price=new_stop,
                                    )
                                    if placed:
                                        svc._last_broker_stop = new_stop
                                        svc._stop_order_miss_count = 0
                                        logger.info(f"✅ Trailing stop: re-placed stop order at {new_stop:.2f}")
                                    else:
                                        logger.error(f"Trailing stop: failed to re-place stop order at {new_stop:.2f}")
                                except Exception as e_place:
                                    logger.error(f"Trailing stop: re-place attempt failed: {e_place}")
                            elif miss_count >= 6:
                                # After 6 misses, deregister to stop the error loop
                                logger.error(
                                    f"Trailing stop: 6 consecutive misses — deregistering position {_cid} "
                                    f"to prevent auto-disarm lockout. Manual stop management required."
                                )
                                svc._trailing_stop_manager.remove_position(str(_cid))
                                svc._stop_order_miss_count = 0
            except Exception as e:
                logger.warning(f"Trailing stop update failed: {e}")

        # === Advanced Exit Manager ===
        if not hasattr(svc, '_adv_exit_mgr'):
            adv_cfg = svc.config.get('advanced_exits', {})
            if adv_cfg:
                svc._adv_exit_mgr = AdvancedExitManager(adv_cfg)
                logger.info("🎯 Advanced Exit Manager initialized")
            else:
                svc._adv_exit_mgr = None

        if svc._adv_exit_mgr:
            pos_data = {
                'direction': direction,
                'entry_price': entry_price,
                'current_price': current_price,
                'unrealized_pnl': unrealized_pnl,
                'mfe_dollars': mfe * 2.0,
                'mae_dollars': mae * 2.0,
                'qty': abs(net_pos)
            }
            entry_time_dt = mon.get('entry_time', datetime.now(_ET).replace(tzinfo=None))  # FIXED 2026-03-25: naive ET
            should_exit, reason = svc._adv_exit_mgr.should_exit(pos_data, current_price, entry_time_dt)

            if should_exit:
                logger.info(f"🚪 ADVANCED EXIT: {reason}")
                try:
                    results = await svc.execution_adapter.flatten_all_positions()
                    if results and results[0].success:
                        logger.info("✅ Position closed via advanced exit")
                        if svc.notifier:
                            await svc.notifier.send(
                                f"🚪 ADVANCED EXIT\n"
                                f"{direction.upper()} @ {entry_price:.2f}\n"
                                f"Exit: {current_price:.2f}\n"
                                f"P&L: ${unrealized_pnl:.2f}\n"
                                f"{reason}",
                                tier=NotificationTier.CRITICAL
                            )
                        return
                except Exception as e:
                    logger.error(f"❌ Advanced exit failed: {e}")
        # === End Advanced Exit ===

        hold_secs = (datetime.now(_ET).replace(tzinfo=None) - mon['entry_time']).total_seconds()  # FIXED 2026-03-25: ET not UTC
        hold_min = hold_secs / 60.0

        # Log every 4th cycle (~60s at 15s cadence) to avoid spam
        mon['log_counter'] = mon.get('log_counter', 0) + 1
        if mon['log_counter'] % 4 == 1:
            dist_stop = ''
            dist_tp = ''
            if stop_price > 0:
                if direction == 'long':
                    dist_stop = f" | dist_stop={current_price - stop_price:.2f}pts"
                else:
                    dist_stop = f" | dist_stop={stop_price - current_price:.2f}pts"
            if tp_price > 0:
                if direction == 'long':
                    dist_tp = f" | dist_tp={tp_price - current_price:.2f}pts"
                else:
                    dist_tp = f" | dist_tp={current_price - tp_price:.2f}pts"

            trail_info = ''
            if svc._runner_manager:
                runner_phase = svc._runner_manager.get_phase(str(_cid))
                if runner_phase:
                    trail_info = f" | runner={runner_phase}"
            elif svc._trailing_stop_manager:
                ts = svc._trailing_stop_manager.get_state(str(_cid))
                if ts and ts.get('current_phase'):
                    trail_info = f" | trail={ts['current_phase']}"

            logger.info(
                f"📊 POSITION: {direction.upper()} {abs(net_pos)}x @ {entry_price:.2f} | "
                f"now={current_price:.2f} | PnL=${unrealized_pnl:.2f} | "
                f"MFE={mfe:.2f}pts MAE={mae:.2f}pts | hold={hold_min:.1f}min"
                f"{dist_stop}{dist_tp}{trail_info}"
            )
