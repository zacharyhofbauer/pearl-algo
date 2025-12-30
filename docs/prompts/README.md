# Prompts Directory

This directory contains reusable AI prompts for daily development tasks with the PearlAlgo codebase.

## Purpose

These prompts are designed to be copied and used with AI coding assistants (Cursor, Continue.dev, etc.) to provide consistent, high-quality guidance for common development workflows.

## Available Prompts

### `project_cleanup.md`
Comprehensive prompt for codebase cleanup, consolidation, and validation tasks. Use this when:
- Cleaning up technical debt
- Consolidating duplicate code
- Removing unused files and references
- Validating code/test/documentation alignment
- Refining project structure

**When to use:** Periodic codebase hygiene sessions, after major feature additions, or when technical debt becomes noticeable.

### `project_building.md`
Forward-looking prompt for architectural evolution and continuous improvement. Use this when:
- Exploring improvement opportunities
- Proposing enhancements to existing functionality
- Discussing architectural evolution
- Identifying long-term opportunities
- Challenging assumptions and constraints

**When to use:** When the codebase is clean and stable, and you're ready to evolve and improve the system. Complements project_cleanup.md - use cleanup first, then building.

### `full_testing.md`
Comprehensive testing and verification strategy for validating system reliability. Use this when:
- Designing comprehensive test strategies
- Discovering edge cases and failure modes
- Stress-testing critical paths
- Validating correctness and reliability
- Proving system behavior under various conditions

**When to use:** When you need to validate reliability, discover edge cases, or design comprehensive test coverage. Works alongside cleanup and building prompts - test what you build and clean.

## Usage

1. Open the relevant prompt file
2. Copy the entire contents
3. Paste into your AI assistant's prompt/chat interface
4. The prompt will guide the AI through the task with appropriate context and constraints

## Adding New Prompts

When adding prompts from other tools (e.g., Continue.dev):

1. Create a new `.md` file with a descriptive name (use underscores: `prompt_name.md`)
2. Keep prompts focused on specific tasks or workflows
3. Include:
   - Clear purpose and authority level
   - Project context specific to PearlAlgo
   - Structured instructions
   - Required output format (if applicable)
4. Update this README to list the new prompt

## Prompt Maintenance

Prompts are reviewed and refined during codebase cleanup sessions (see `project_cleanup.md` section 8). They should:
- Stay aligned with current project structure
- Reference correct file paths and conventions
- Remain clear and actionable
- Avoid redundancy and contradiction

Only update prompts when there's a clear issue or outdated reference. Don't change working prompts for style preferences.

## Best Practices

- **Keep prompts focused**: One prompt per specific workflow or task type
- **Document intent**: Include a brief description of what the prompt does and when to use it
- **Version control**: Prompts are version-controlled with the codebase
- **Test in practice**: Use prompts and refine based on actual results
- **Stay project-specific**: Include relevant PearlAlgo context (architecture, conventions, file paths)

---

**Note:** These prompts are living documents. They should evolve as the project evolves, but changes should be intentional and justified.


