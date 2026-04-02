# Repository Layout Plan - 2026-04-01

This plan is intentionally conservative.

The trading stack is currently performing well, so the goal is to reduce path
confusion and legacy clutter without changing strategy behavior, execution
behavior, or the live process layout until a clean restart window.

## Principles

1. One canonical repo location.
2. One canonical launcher.
3. Runtime state and logs should eventually live outside the repo.
4. Backups and archives should not compete with live config/state paths.
5. Docs should clearly separate **current truth** from **historical notes**.

## Current layout

Current live code location:

- `/home/pearlalgo/projects/pearl-algo`

Current live runtime root:

- agent: `data/agent_state/MNQ/`
- some legacy readers/helpers: `data/tradovate/paper/`

Current external dependency location:

- IBKR install: `/home/pearlalgo/ibkr`

Current secrets location:

- `~/.config/pearlalgo/secrets.env`

Preparation already completed on 2026-04-01:

- created `~/projects/` as the future canonical parent for code repos
- created `~/var/pearl-algo/{state,logs,archive,backups/}` as the future runtime root
- moved config backup copies into a dated folder under `~/var/pearl-algo/backups/config/`

## Target home-directory layout

Recommended end state after a controlled migration:

```text
/home/pearlalgo/
  projects/
    pearl-algo/                 # Git repo, code only
  var/
    pearl-algo/
      state/
        MNQ/                    # live runtime state
      logs/                     # live service logs
      archive/                  # retired state roots, incident snapshots
      backups/
        config/                 # dated config backups
  ibkr/                         # external IBKR install
  .config/
    pearlalgo/
      secrets.env              # local secrets, never committed
```

Why this layout:

- `projects/` makes the code location obvious.
- `var/pearl-algo/` separates mutable runtime artifacts from source code.
- `ibkr/` stays independent because it is a third-party runtime install, not app code.
- secrets remain under `.config/pearlalgo/`, which is already a good local-only home.

## Target repo layout

Recommended repo shape after the runtime move:

```text
pearl-algo/
  src/
  tests/
  scripts/
  config/                      # live configs only
  docs/
    START_HERE.md
    PATH_TRUTH_TABLE.md
    archive/                   # historical notes and completed rollout docs
    journal/
  resources/
  apps/pearl-algo-app/
```

Repo rules:

- `config/` should contain only active config files.
- backup copies should live in `~/var/pearl-algo/backups/config/`.
- runtime state should not live under `data/` long term.
- archived scripts should remain clearly quarantined.
- non-current documentation should live under `docs/archive/`.
- `pearl.sh` is the canonical top-level control entrypoint.
- `pearlalgo.sh` should remain a compatibility alias only.

## What we can do safely before a restart

These are safe while trading remains online:

1. Update docs so they stop teaching old paths and old launcher names.
2. Keep `pearl.sh` as the canonical entrypoint everywhere.
3. Quarantine config backup files outside the live `config/` tree.
4. Define which docs are current operational truth.
5. Prepare the target home-directory folders without moving the repo yet.

## What should wait for a flat / restart window

These should happen only when you are ready for a monitored restart:

1. Repo move completed: `/home/pearlalgo/projects/pearl-algo` is now canonical, and the old `/home/pearlalgo/pearl-algo-workspace` path can be retired.
2. Move runtime state from repo-local `data/` to `~/var/pearl-algo/state/`.
3. Move service logs from repo-local `logs/` to `~/var/pearl-algo/logs/`.
4. Repoint systemd/services/env vars to the external runtime root.
5. Freeze old repo-local state under `~/var/pearl-algo/archive/`.

## Canonical references going forward

Use these as the authoritative docs:

- `docs/START_HERE.md` - operator starting point
- `docs/PATH_TRUTH_TABLE.md` - component and entrypoint map
- `docs/WORKSPACE_AUDIT_2026-04-01.md` - current live/runtime audit
- `docs/CODEBASE_BLOAT_AUDIT_2026-04-01.md` - clutter and drift audit
- `docs/REPOSITORY_LAYOUT_PLAN_2026-04-01.md` - home/repo restructure plan

## Recommended next sequence

1. Finish doc truth cleanup and quarantine backups.
2. Keep live trading untouched until a flat window.
3. During the next clean restart, align every service to one runtime root.
4. After that alignment is stable, move the repo into `~/projects/pearl-algo`.
5. Only then delete or archive the old in-repo state roots.
