# Prompts Directory

This directory contains reusable AI promptbooks for daily development tasks with the PearlAlgo codebase.

## Quick Start (One-Paste Workflow)

For fast, efficient sessions, use the **Engineering Promptbook** as your single entrypoint:

1. Open `promptbook_engineering.md`
2. Edit the **RUN CONFIGURATION** block at the top:
   - Set `RUN_MODE`: `FAST`, `STANDARD`, or `DEEP`
   - Set `RUN_SCOPE`: `engineering`, `trading`, `ux`, or `all`
   - Toggle individual phases on/off
3. Copy and paste into your AI assistant
4. The promptbook orchestrates everything automatically

**Example configurations:**

```
# Quick cleanup session
RUN_MODE: FAST
RUN_SCOPE: engineering
RUN_CLEANUP: true
RUN_BUILDING: false
RUN_TESTS: false

# Full multi-domain session
RUN_MODE: STANDARD
RUN_SCOPE: all
```

## Available Promptbooks

### `promptbook_engineering.md` (Entrypoint/Orchestrator)

The main promptbook for development sessions. Handles:
- Project cleanup (dead code, duplicates, broken references)
- Project building (architectural evolution, improvements)
- Testing (coverage analysis, test additions)
- **Orchestration**: Can invoke Trading and UX promptbooks via `RUN_SCOPE`

**When to use:** Start here for any development session. Set `RUN_SCOPE=all` for comprehensive multi-domain work.

### `promptbook_trading.md`

Trading system verification and improvement. Handles:
- **Backtesting**: Signal existence, condition blocking, regime analysis
- **NQ Agent**: Lifecycle verification, state consistency, observability
- **ATS Execution**: Safety audit, kill switch verification, learning review

**When to use:** Standalone for trading-focused sessions, or invoked via Engineering promptbook with `RUN_SCOPE=trading` or `RUN_SCOPE=all`.

### `promptbook_ux.md`

User experience surfaces. Handles:
- **Telegram**: Message clarity, interaction quality, command UX
- **Charting**: Visual integrity, schema verification, trust contracts

**When to use:** Standalone for UX-focused sessions, or invoked via Engineering promptbook with `RUN_SCOPE=ux` or `RUN_SCOPE=all`.

## Run Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `FAST` | Quick scan, high-level findings, skip deep analysis | Daily checks, quick audits |
| `STANDARD` | Balanced depth, full workflow | Regular development sessions |
| `DEEP` | Thorough analysis, all verifications, longer runtime | Pre-release, comprehensive audits |

## Run Scopes (Engineering Promptbook)

| Scope | What It Runs |
|-------|--------------|
| `engineering` | Cleanup + Building + Testing only |
| `trading` | Reads and executes `promptbook_trading.md` |
| `ux` | Reads and executes `promptbook_ux.md` |
| `all` | Engineering + Trading + UX (full session) |

## Self-Healing (Prompt Drift Audit)

All promptbooks include a **Prompt Drift Audit** phase that:
- Checks for referenced file paths that don't exist
- Verifies commands match repository scripts
- Detects contradictions with `docs/PROJECT_SUMMARY.md`
- Proposes patches for approval (does NOT auto-apply)

Enable with `RUN_PROMPT_DRIFT_AUDIT: true` to keep prompts aligned with the codebase.

## Usage Patterns

### Daily Development Session
```
promptbook_engineering.md
RUN_MODE: STANDARD
RUN_SCOPE: engineering
```

### Pre-Trading Session Check
```
promptbook_trading.md
RUN_MODE: FAST
RUN_BACKTESTING: false
RUN_NQ_AGENT_VERIFICATION: true
RUN_ATS_SAFETY_AUDIT: true
```

### Comprehensive Multi-Domain Session
```
promptbook_engineering.md
RUN_MODE: STANDARD
RUN_SCOPE: all
```

### UX-Focused Improvement Session
```
promptbook_ux.md
RUN_MODE: STANDARD
RUN_TELEGRAM_AUDIT: true
RUN_CHARTING_AUDIT: true
```

## Key Concepts

### Lane A vs Lane B

All promptbooks use a two-lane system:

- **LANE A (Safe Now)**: Changes the agent can implement autonomously
  - Dead code removal, formatting fixes, test additions
  - Observability improvements, documentation fixes
  
- **LANE B (Needs Review)**: Changes requiring human approval
  - Strategy logic changes, risk parameter modifications
  - State schema changes, semantic changes to messages/charts

### Sources of Truth

1. `docs/PROJECT_SUMMARY.md` - Architecture, state schema (highest authority)
2. `promptbook_engineering.md` - Global constraints, orchestration
3. Domain promptbooks - Scope-specific constraints

### Required Outputs

Every promptbook run produces:
- Executive summary
- What changed (file-level)
- Verification results
- Domain-specific findings
- Prompt drift audit (if enabled)
- Open issues / follow-ups (prioritized)

## Best Practices

- **Start with Engineering**: Use `promptbook_engineering.md` as your entrypoint
- **Set appropriate mode**: Use `FAST` for quick checks, `STANDARD` for regular work
- **Enable drift audit**: Keep `RUN_PROMPT_DRIFT_AUDIT: true` to maintain prompt accuracy
- **Review LANE B items**: Don't skip the "needs review" items in the output
- **Apply drift patches**: When the audit proposes patches, review and apply them

## Prompt Maintenance

Prompts are self-healing via the Prompt Drift Audit. When drift is detected:

1. The audit outputs a proposed patch
2. Review the patch for correctness
3. Apply if appropriate
4. Commit the updated promptbook

This keeps prompts aligned with the evolving codebase without manual maintenance.

---

**Note:** These promptbooks are living documents. The self-healing mechanism helps them evolve with the project automatically.
