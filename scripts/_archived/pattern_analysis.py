#!/usr/bin/env python3
"""
PearlAlgo Pattern Analysis — Option B Self-Learning Engine
Runs after every session to extract trade patterns and update knowledge base.

All timestamps in trades.db are stored as naive ET (America/New_York).
strftime('%H', exit_time) returns ET hours directly — no UTC conversion needed.
"""
import sqlite3
import json
import sys
from datetime import datetime, date
from pathlib import Path

DB = Path('/home/pearlalgo/pearl-algo-workspace/data/tradovate/paper/trades.db')
OUT = Path('/home/pearlalgo/pearl-algo-workspace/data/pattern_library.json')

def analyze():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    results = {
        "generated_at": datetime.now().isoformat(),
        "total_trades": 0,
        "overall": {},
        "by_direction": {},
        "by_hour_et": {},
        "by_regime": {},
        "direction_x_hour": {},
        "direction_x_regime": {},
        "hold_duration": {},
        "golden_hours": [],
        "kill_zones": [],
        "actionable_rules": []
    }

    # Overall
    c.execute("SELECT count(*) t, round(sum(pnl),2) pnl, round(avg(pnl),2) avg, round(100.0*sum(case when pnl>0 then 1 else 0 end)/count(*),1) wr FROM trades")
    r = dict(c.fetchone())
    results["total_trades"] = r["t"]
    results["overall"] = r

    # By direction
    c.execute("SELECT direction, count(*) t, round(sum(pnl),2) pnl, round(avg(pnl),2) avg, round(100.0*sum(case when pnl>0 then 1 else 0 end)/count(*),1) wr FROM trades GROUP BY direction")
    for row in c.fetchall():
        results["by_direction"][row["direction"]] = dict(row)

    # By hour ET (timestamps are already ET in DB)
    c.execute("SELECT strftime('%H',exit_time) hr, count(*) t, round(sum(pnl),2) pnl, round(avg(pnl),2) avg, round(100.0*sum(case when pnl>0 then 1 else 0 end)/count(*),1) wr FROM trades GROUP BY hr")
    for row in c.fetchall():
        results["by_hour_et"][row["hr"]] = dict(row)

    # By regime
    c.execute("SELECT regime, count(*) t, round(sum(pnl),2) pnl, round(avg(pnl),2) avg, round(100.0*sum(case when pnl>0 then 1 else 0 end)/count(*),1) wr FROM trades WHERE regime IS NOT NULL GROUP BY regime")
    for row in c.fetchall():
        results["by_regime"][row["regime"]] = dict(row)

    # Direction x Hour
    c.execute("SELECT direction, strftime('%H',exit_time) hr, count(*) t, round(sum(pnl),2) pnl, round(avg(pnl),2) avg, round(100.0*sum(case when pnl>0 then 1 else 0 end)/count(*),1) wr FROM trades GROUP BY direction, hr HAVING count(*)>=5")
    for row in c.fetchall():
        key = f"{row['direction']}_{row['hr']}"
        results["direction_x_hour"][key] = dict(row)

    # Direction x Regime
    c.execute("SELECT direction, regime, count(*) t, round(sum(pnl),2) pnl, round(avg(pnl),2) avg, round(100.0*sum(case when pnl>0 then 1 else 0 end)/count(*),1) wr FROM trades WHERE regime IS NOT NULL GROUP BY direction, regime HAVING count(*)>=5")
    for row in c.fetchall():
        key = f"{row['direction']}_{row['regime']}"
        results["direction_x_regime"][key] = dict(row)

    # Golden hours (WR >= 55%, avg >= 15, >= 15 trades)
    c.execute("SELECT strftime('%H',exit_time) hr, direction, count(*) t, round(avg(pnl),2) avg, round(100.0*sum(case when pnl>0 then 1 else 0 end)/count(*),1) wr FROM trades GROUP BY hr, direction HAVING count()>=15 AND wr>=55 AND avg>=15 ORDER BY avg DESC")
    results["golden_hours"] = [dict(r) for r in c.fetchall()]

    # Kill zones (WR < 35%, avg < -10, >= 10 trades)
    c.execute("SELECT strftime('%H',exit_time) hr, direction, count(*) t, round(avg(pnl),2) avg, round(100.0*sum(case when pnl>0 then 1 else 0 end)/count(*),1) wr FROM trades GROUP BY hr, direction HAVING count()>=10 AND wr<35 AND avg<-10 ORDER BY avg ASC")
    results["kill_zones"] = [dict(r) for r in c.fetchall()]

    # Generate rules
    rules = []

    # Shorts losing badly overall?
    short_data = results["by_direction"].get("short", {})
    long_data = results["by_direction"].get("long", {})
    if short_data.get("avg", 0) < -20 and short_data.get("t", 0) >= 50:
        rules.append({
            "rule": "short_moratorium",
            "reason": f"Shorts avg {short_data['avg']}/trade ({short_data['wr']}% WR) over {short_data['t']} trades — structural loser",
            "action": "Consider short_shadow_only until avg > 0",
            "priority": "HIGH"
        })

    # Kill zone hours (now in ET)
    for kz in results["kill_zones"]:
        rules.append({
            "rule": f"block_{kz['direction']}_hour_{kz['hr']}et",
            "reason": f"{kz['direction'].upper()} at {kz['hr']}ET: {kz['avg']}/trade, {kz['wr']}% WR ({kz['t']} trades)",
            "action": f"Add hour {kz['hr']} ET to session block list for {kz['direction']} signals",
            "priority": "HIGH" if kz["avg"] < -30 else "MEDIUM"
        })

    results["actionable_rules"] = rules
    conn.close()

    OUT.write_text(json.dumps(results, indent=2))
    print(f"Pattern library updated: {len(results['direction_x_hour'])} combos analyzed, {len(rules)} rules generated")
    print(f"Output: {OUT}")

    # Print summary
    print(f"\nTotal trades: {results['total_trades']} | Overall WR: {results['overall']['wr']}% | Avg: ${results['overall']['avg']}")
    print(f"Golden hours: {len(results['golden_hours'])} | Kill zones: {len(results['kill_zones'])}")
    if rules:
        print(f"\nACTIONABLE RULES ({len(rules)}):")
        for r in rules[:5]:
            print(f"  [{r['priority']}] {r['rule']}: {r['reason']}")

if __name__ == "__main__":
    analyze()
