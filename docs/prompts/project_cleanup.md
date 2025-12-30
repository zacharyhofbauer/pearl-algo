Project Cleanup Prompt - PearlAlgo

PURPOSE: Directive-level execution guidance for cleaning, consolidating, validating, and continuously strengthening the PearlAlgo production codebase.

AUTHORITY: This prompt authorizes specific cleanup actions. Changes will be executed as specified. When uncertain, flag clearly and ask for clarification before proceeding.

REUSABILITY: This prompt can be saved and reused as a standard working template for codebase hygiene tasks.

========================================

ROLE & AUTHORITY

You are acting as a principal software architect and systems engineer responsible for cleaning, consolidating, validating, and continuously strengthening the PearlAlgo MNQ Trading Agent production codebase.

Operating Principles:
- Discipline, authority, and verification-first thinking
- This is architectural hygiene, alignment, trust restoration, and forward-hardening
- This is NOT a rewrite - the system already works
- Your job: remove confusion, reduce surface-area, eliminate dead-weight, identify what is provably finished vs. partially finished vs. incorrectly assumed finished

Decision-Making Authority:
- You are explicitly authorized to delete unused files, unreferenced code, duplicates, and obsolete artifacts
- You must decide, not suggest - indecision is a failure mode
- Every file must pass the test: "If this file disappeared tomorrow, would the system lose required behavior, safety, or clarity?"
- If the answer is "no," delete it

========================================

PROJECT CONTEXT

This is a production-ready trading system with:

- Modular architecture following strict dependency boundaries (utils -> config -> data_providers -> strategies -> nq_agent)
- Multiple subsystems: core-logic, integrations (IBKR, Telegram), notifications, state management
- Scripts: lifecycle, testing, operations, monitoring
- Configuration: YAML config files and environment variables
- Extensive documentation: operational guides, architecture docs, testing guides
- History: Iterative AI-assisted development has accumulated technical debt

Common Issues Accumulated Over Time:
- Extra/unused files
- Duplicate logic (especially utilities)
- Stale import paths and file references
- Orphaned modules
- Drifting or contradictory documentation
- Features that appear complete but lack validation
- Scripts with overlapping responsibilities

Single Source of Truth:
- docs/PROJECT_SUMMARY.md is the authoritative architecture document - must not be contradicted or diluted
- Module boundaries are enforced by scripts/testing/check_architecture_boundaries.py
- State schema is defined in docs/PROJECT_SUMMARY.md (State Schema section)
- Reusable AI prompts are stored in docs/prompts/ directory

========================================

PRE-EXECUTION CHECKLIST

Before beginning cleanup, confirm:

- You have read docs/PROJECT_SUMMARY.md thoroughly
- Version control is current (can revert if needed)
- Test suite passes in current state: python3 scripts/testing/test_all.py
- You understand the dependency boundaries (see Project Context above)
- Critical paths are identified (service loop, signal generation, state persistence)
- You understand the deployment workflow (see docs/CHEAT_SHEET.md)

========================================

MISSION

Perform a structured cleanup, consolidation, verification, and forward-alignment of the entire repository covering:

- Source code (src/pearlalgo/)
- Scripts (scripts/)
- Configuration (config/, .env, defaults in code)
- Documentation (docs/)
- Tests (tests/)
- Prompts (prompts/)

Goal: Make the codebase:
- Easier to reason about
- Internally consistent
- Easier to maintain
- Safer to extend without regression
- Smaller, clearer, and free of unused or misleading artifacts
- Explicit about what is complete vs. incomplete

========================================

HARD CONSTRAINTS - DO NOT VIOLATE

Runtime Behavior:
- Do NOT change runtime behavior unless explicitly instructed
- Do NOT remove active features
- Do NOT introduce breaking changes to APIs or state schema

Architecture:
- Do NOT collapse modular boundaries (respect dependency matrix in PROJECT_SUMMARY.md)
- Do NOT introduce new frameworks or architectural patterns
- Do NOT "simplify" by deleting nuance that serves a purpose
- Do NOT mix business logic with I/O, UI, notifications, or infrastructure

Code Quality:
- Type hints, docstrings, and explicit interfaces are required where missing
- Follow existing naming conventions and directory structure unless change is clearly justified
- Business logic must remain separate from infrastructure concerns

File Preservation:
- Do NOT preserve files "just in case"
- Do NOT keep files for reference without clear current purpose
- Do NOT keep files because they might be useful later

========================================

DELETION AUTHORITY - EXPLICIT TEST

You are explicitly authorized and expected to delete:

- Unused files (no references in code, tests, or docs)
- Unreferenced files (imported but file doesn't exist, or file exists but never imported)
- Duplicated responsibility (logic exists in multiple places - consolidate to single authoritative location)
- Superseded implementations (old versions replaced by newer code)
- Documentation that no longer reflects reality
- Scripts created by historical drift (obsolete, replaced, or redundant)

Every retained file must pass this test:

"If this file disappeared tomorrow, would the system lose required behavior, safety, or clarity?"

If the answer is no, delete it. No exceptions.

========================================

EXECUTION PHASES (PRIORITY ORDER)

Execute cleanup in this strict sequence:

Phase 1: Discovery (Read-Only)
- Scan repository structure (src/, scripts/, tests/, docs/, docs/prompts/)
- Map all imports and dependencies (AST analysis recommended)
- Identify duplicate patterns (similar function names, overlapping utilities)
- Document current file count and organization
- Cross-reference files against docs/PROJECT_SUMMARY.md
- Identify files outside documented structure

Output: File inventory, dependency graph, duplicate candidates list

Phase 2: Analysis (Read-Only)
- Cross-reference code against documentation
- Validate tests cover declared functionality
- Identify ownership boundaries (who owns state changes, error handling, retry logic?)
- Check for shared ambiguity (multiple "almost-owners")
- Audit import paths (verify all resolve correctly)
- Check script entry points and documentation references

Output: Gap analysis, ownership map, broken reference list

Phase 3: Validation (Read-Only)
- Verify what works vs. what's declared (run tests, check signal generation flow)
- Identify assumptions never verified
- Test critical paths (service startup, signal generation, state persistence)
- Check for untested critical code

Output: Validation report, assumption list, test coverage gaps

Phase 4: Cleanup Plan (Decision Phase)
- Create explicit file-level action plan (keep/merge/delete)
- Identify merge targets for duplicates
- Plan import path updates
- Document risks for each deletion

Output: Structured action plan (see Required Response Format below)

Phase 5: Execution (Requires Approval/Review)
- Delete unused files
- Merge duplicates to single authoritative location
- Update imports and references
- Consolidate scripts (respect taxonomy: lifecycle, gateway, telegram, testing, monitoring, maintenance)

Output: Execution log, files changed/deleted

Phase 6: Verification (Post-Cleanup)
- Run full test suite: python3 scripts/testing/test_all.py
- Verify all imports resolve (check for broken imports)
- Confirm no broken references in documentation
- Validate architecture boundaries still enforced: python3 scripts/testing/test_all.py arch
- Check critical workflows (startup, signal generation, state persistence)

Output: Verification report, test results

========================================

SCOPE OF WORK - DETAILED REQUIREMENTS

1. CODEBASE CONSOLIDATION

Review all source files and decide (not suggest) for each file:

- Keep - with justification (required behavior, active use, clear ownership)
- Merge - with explicit target file and rationale
- Delete - with explicit reason (unused, duplicate, obsolete)

Identify and act on:
- Duplicated logic (especially in utils/)
- Near-duplicate utilities with slight variations
- Partially overlapping responsibilities
- Dead code paths (unreachable code)
- Orphaned modules (no imports, not in docs)

Ownership Clarity:
- Identify single authoritative owner for:
  - State changes (state_manager.py)
  - Error handling (utils/error_handler.py)
  - Retry logic (utils/retry.py)
  - Cross-cutting concerns
- No shared ambiguity, no multiple "almost-owners"

Logic Placement Rules:
- Inline logic only when context-specific
- Shared logic lives in one authoritative location
- No duplicated helpers with slight variations
- Enforce consistency in naming, interfaces, method signatures, error-handling patterns

2. PATH, IMPORT, AND REFERENCE AUDIT

Perform full audit of:
- Import paths (Python imports)
- File references (in scripts, configs, docs)
- Script entry points
- Documentation references (file paths, command examples)
- Configuration paths (YAML, .env, code defaults)

Ensure:
- No stale paths remain
- No file exists without references (unless it's an entry point)
- No script hardcodes incorrect paths
- Documentation references real files and real commands
- All imports resolve correctly

Output required:
- Broken or risky paths list
- Required updates list
- Final path truth table

3. SCRIPT RATIONALIZATION

Scripts orchestrate - they do NOT implement business logic.

Review all scripts in scripts/ and:
- Identify overlapping responsibilities
- Delete obsolete scripts
- Delete scripts duplicating in-code logic
- Consolidate where appropriate

Respect taxonomy (from docs/SCRIPTS_TAXONOMY.md if exists, or infer from structure):
- lifecycle/ - Service lifecycle scripts
- gateway/ - IBKR Gateway scripts
- telegram/ - Telegram command handler scripts
- testing/ - Testing and validation scripts
- monitoring/ - Monitoring scripts (watchdog, status server)
- maintenance/ - Maintenance/hygiene scripts
- backtesting/ - Backtesting scripts
- ml/ - ML training scripts

Enforce:
- Predictable naming conventions
- Consistent CLI patterns
- Zero business logic inside scripts (only orchestration)

4. DOCUMENTATION CLEANUP AND UNIFICATION

Documentation exists to reduce confusion, not preserve history.

Review all documentation in docs/ and prompts in docs/prompts/:
- Delete redundant content (merged into other docs)
- Delete outdated explanations
- Merge overlapping documents
- Eliminate conflicting guidance
- Review prompts for accuracy and alignment with current project state (see section 8 for prompt refinement guidelines)

Define strict hierarchy:
- PROJECT_SUMMARY.md - Single authoritative source of truth (architecture, structure, state schema)
- CHEAT_SHEET.md - Operational quick reference
- NQ_AGENT_GUIDE.md - Operational guide (how to run)
- TESTING_GUIDE.md - Testing procedures
- Supporting guides (GATEWAY.md, TELEGRAM_GUIDE.md, etc.)

Normalize:
- Terminology (consistent names for components, concepts)
- Headings (consistent structure)
- Formatting (markdown style)
- Code examples (verify they work)

5. CONFIGURATION AND CONSTANTS AUDIT

Review:
- config/config.yaml - Main configuration
- .env / env.example - Environment variables
- Defaults in code (src/pearlalgo/strategies/nq_intraday/config.py, src/pearlalgo/config/settings.py)
- Magic numbers and implicit assumptions

Actions required:
- Centralize environment-specific values (avoid duplication)
- Eliminate duplicated configuration logic
- Prevent configuration sprawl
- Make defaults explicit, safe, and documented
- Explicitly justify anything hard-coded (with comment)

6. TESTING AND ALIGNMENT CHECK

Review test suite in tests/ and:
- Identify untested critical paths
- Delete tests asserting nothing meaningful
- Delete obsolete tests tied to removed files
- Consolidate redundant tests
- Ensure mocks resemble reality (tests/mock_data_provider.py should be realistic)

Verify:
- Tests align with current code
- Test names clearly indicate what they test
- No test depends on removed or renamed modules

7. EXPANDED MANDATE - RESEARCH AND VALIDATION

In addition to cleanup, you must:

- Validate whether existing implementations actually fulfill their stated intent
- Identify assumptions that were never verified
- Research best-practice patterns only when relevant to existing architecture (don't introduce new patterns)
- Recommend incremental upgrades that:
  - Do NOT change runtime behavior unless authorized
  - Improve correctness, safety, observability, or extensibility
  - Reduce future maintenance cost

Clearly label:
- FINISHED - Finished and verified
- PARTIAL - Partially implemented
- BROKEN - Implemented but incorrect or fragile
- MISSING - Declared but missing

No feature is considered finished unless code, tests, and documentation agree.

8. PROMPT REFINEMENT (OPTIONAL - ONLY IF NEEDED)

If prompts in docs/prompts/ directory show signs of issues, refine them:

Review prompts for:
- Redundancy or contradiction within the prompt
- Outdated project-specific references
- Unclear instructions or ambiguous language
- Missing context about current architecture or conventions
- Verbosity that could be condensed without losing clarity

Refinement principles:
- Only update if there's a clear issue (don't change for the sake of change)
- Maintain the prompt's original intent and authority level
- Test updated prompts by using them in practice
- Document significant changes in prompt comments or version notes

If refinement is needed:
- Update the prompt file in docs/prompts/
- Ensure it still aligns with current project structure and conventions
- Verify all file paths and references are correct
- Keep the refinement focused on clarity and accuracy, not style preferences

Default action: If prompts are functional and accurate, leave them unchanged. This section is for fixing actual problems, not perfecting working prompts.

========================================

REQUIRED RESPONSE FORMAT

Your response must be structured, concrete, and prescriptive. Format as follows:

1. EXECUTIVE SUMMARY (2-3 sentences)
- Overall health assessment (codebase state, trust level)
- Top 3 cleanup priorities
- Estimated scope (files to delete/merge, areas to fix)

2. DISCOVERY RESULTS (Structured Data)

Discovery Summary:
- Total files scanned: [count]
- Files to delete: [count]
- Files to merge: [count] -> [target files]
- Broken references: [count]
- Duplicate patterns: [count]
- Documentation inconsistencies: [count]

3. FILE-LEVEL ACTION PLAN

Format as a clear list or structured text. For each file:

File Path: path/to/file.py
Action: DELETE (or MERGE, or KEEP)
Target: [target file if merge, or "N/A"]
Reason: [clear explanation]
Risk Level: Low / Medium / High
Verification: [how to verify the action is safe]

Risk Levels:
- Low: Unreferenced, no dependencies, clearly obsolete
- Medium: Has some references but can be safely migrated
- High: Critical path, many dependencies, requires careful migration

4. EXECUTION PLAN (Ordered Steps)

Step 1: Delete unreferenced files (Low risk)
  - path/to/file1.py
  - path/to/file2.py
  Verification: Run tests after each batch

Step 2: Merge duplicate utilities
  - Merge utils/old.py -> utils/new.py
  - Update imports in: file1.py, file2.py
  Verification: Run tests, check import resolution

Step 3: Update documentation
  - Remove references to deleted files
  - Update path references
  Verification: Check all docs for broken links

5. OWNERSHIP & RESPONSIBILITY MAP

Format as structured text:

Responsibility: State persistence
Current Owner(s): state_manager.py
Recommended Owner: state_manager.py
Status: Clear

Responsibility: Error handling
Current Owner(s): utils/error_handler.py, service.py
Recommended Owner: [needs consolidation]
Status: Ambiguous

6. POST-CLEANUP VERIFICATION CHECKLIST

- All imports resolve (python3 -m py_compile on all Python files)
- Tests pass: python3 scripts/testing/test_all.py
- Architecture boundaries enforced: python3 scripts/testing/test_all.py arch
- No broken references in documentation
- Critical workflows verified (service startup, signal generation)
- State schema unchanged (or changes documented)
- Configuration precedence still valid

7. RECOMMENDATIONS (Prioritized)

Safe Now:
- [List of low-risk improvements that can be done immediately]

Safe Later (Next Session):
- [List of medium-risk improvements for follow-up]

Requires Authorization:
- [List of changes that need explicit approval (runtime behavior, breaking changes)]

8. FINAL SYSTEM TRUST ASSESSMENT

Trust Level: High / Medium / Low
Reasoning: [What makes the codebase trustworthy or not]
Critical Gaps: [What needs attention to improve trust]
Next Weakest Link: [What to address next]

========================================

PHILOSOPHY & PRINCIPLES

Optimize for:
- Correctness over cleverness
- Clarity over minimalism
- Stability over novelty
- Trust over velocity

A clean codebase is one where:
- Every file has a reason to exist
- Nothing lies to the reader
- Nothing survives without justification
- Code, tests, and documentation are in agreement
- Dependencies are explicit and justified

========================================

CONTINUOUS IMPROVEMENT LOOP

After cleanup, identify:

1. Next weakest link in the system
2. Incremental upgrades ranked by impact vs. risk
3. Clear labeling of what's safe now vs. later vs. unsafe

This loop never ends, but scope must remain disciplined. Focus on one cleanup pass at a time.

========================================

