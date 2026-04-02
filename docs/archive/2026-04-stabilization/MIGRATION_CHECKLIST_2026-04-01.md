# Migration Checklist - 2026-04-01

This is the controlled cutover plan for moving PEARL from the current repo-local
runtime layout to the cleaner target layout:

- repo: `/home/pearlalgo/projects/pearl-algo`
- runtime state: `~/var/pearl-algo/state/`
- runtime logs: `~/var/pearl-algo/logs/`

Do not execute this checklist while positions are open.

## Goal

End the split-brain path situation and make the filesystem easier to reason about
without changing strategy behavior.

## Scope

This checklist is only for:

- repo relocation
- runtime state relocation
- log relocation
- launcher/service path alignment

This checklist is not for:

- strategy tuning
- execution logic changes
- risk/config experimentation

## Current known-good baseline

Before cutover, these truths should still hold:

- live agent state is under `data/agent_state/MNQ/`
- current web/API readers have been patched for next restart alignment
- `pearl.sh` is the canonical launcher
- config backups are already quarantined outside `config/`

## Pre-cutover checks

1. Confirm you are flat in Tradovate Paper.
2. Run `./pearl.sh quick` and record the result.
3. Run `python3 scripts/ops/audit_runtime_paths.py` and save the output.
4. Snapshot the live state tree:
   - `data/agent_state/MNQ/`
   - `data/tradovate/paper/`
5. Snapshot the current logs:
   - `logs/agent_MNQ.log`
   - `logs/api_TV_PAPER.log`
   - other current PEARL logs
6. Confirm `python3 scripts/testing/check_doc_references.py` passes.

## Filesystem prep

1. Ensure the target folders exist:
   - `~/projects/`
   - `~/var/pearl-algo/state/`
   - `~/var/pearl-algo/logs/`
   - `~/var/pearl-algo/archive/`
2. Pick the target state root:
   - recommended: `~/var/pearl-algo/state/MNQ/`
3. Pick the target log root:
   - recommended: `~/var/pearl-algo/logs/`

## Repo relocation

1. Stop PEARL services only once you are flat and ready.
2. Move the repo:
   - from: `/home/pearlalgo/pearl-algo-workspace` (historical pre-migration path)
   - to: `/home/pearlalgo/projects/pearl-algo`
3. Verify the repo opens cleanly from the new path.
4. Verify `.venv` activation and imports still work from the new repo root.

## Runtime state relocation

1. Copy current live state into the new runtime root.
2. Preserve timestamps and permissions.
3. Keep the old repo-local state trees untouched until validation is complete.
4. Mark these old trees as rollback sources:
   - `data/agent_state/MNQ/`
   - `data/tradovate/paper/`

## Launcher and service alignment

1. Set the canonical state directory for all PEARL services.
2. Ensure agent, API, monitoring, and health tooling all read the same root.
3. Ensure systemd unit files point at the new repo path.
4. Ensure PID/log handling points at `~/var/pearl-algo/logs/`.
5. Restart only after all path references are aligned.

## Post-cutover validation

1. Run `./pearl.sh quick`.
2. Run `python3 scripts/ops/audit_runtime_paths.py`.
3. Confirm agent and API report the same runtime root.
4. Confirm `performance.json`, `signals.jsonl`, and `tradovate_fills.json` are updating in the new runtime root.
5. Confirm the web app and API show current data.
6. Confirm health tooling does not point back to repo-local paths.
7. Confirm no process still depends on `/home/pearlalgo/pearl-algo-workspace`.

## Rollback plan

If validation fails:

1. Stop PEARL services.
2. Restore the previous repo path or switch services back to it.
3. Point runtime env/service config back to the previous repo-local state root.
4. Restart from the last known-good layout.
5. Re-run `python3 scripts/ops/audit_runtime_paths.py` to confirm the rollback.

## After the cutover is stable

Only after a stable run:

1. Archive the old repo-local state trees into `~/var/pearl-algo/archive/`.
2. Remove stale repo-local logs.
3. Delete or archive the old `data/tradovate/paper/` tree if no longer needed.
4. Remove the old `/home/pearlalgo/pearl-algo-workspace` link after all active tooling has been updated.

## Classification notes

- `config/accounts/tradovate_paper.yaml` is the canonical active account overlay.
- `config/accounts/tradovate_paper_eval.yaml` should be treated as a preserved alternate overlay, not the default live control path, unless you explicitly promote it later.
