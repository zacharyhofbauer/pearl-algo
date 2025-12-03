# Fix: Terminal Starting in .venv Directory

## Problem
Every time you open a NEW terminal, you're automatically in the `.venv` directory instead of your project root.

## Quick Fix

If you find yourself in `.venv` directory, just run:
```bash
cd ~/pearlalgo-dev-ai-agents
```

## Finding the Cause

### 1. Check IDE Terminal Settings

If you're using **VS Code** or **Cursor**:
- Open Settings (Ctrl+,)
- Search for "terminal.integrated.cwd"
- Make sure it's NOT set to `.venv`
- Should be: `"${workspaceFolder}"` or empty

### 2. Check Shell Configuration

Check for auto-cd commands:
```bash
grep -n "cd.*venv\|cd.*\.venv" ~/.bashrc ~/.zshrc ~/.bash_profile
```

### 3. Check direnv

If you have `direnv` installed:
```bash
which direnv
ls -la ~/pearlalgo-dev-ai-agents/.envrc
```

If `.envrc` exists and has a `cd` command, that's the culprit.

### 4. Check Terminal Emulator Settings

Some terminal emulators (like Tilix, Terminator) can be configured to start in a specific directory.

## Solution Script

Create a file `~/fix_terminal.sh`:
```bash
#!/bin/bash
# Always start in project root, not .venv
cd ~/pearlalgo-dev-ai-agents
```

Then add to `~/.bashrc`:
```bash
# Fix terminal start directory
if [ -f ~/fix_terminal.sh ]; then
    source ~/fix_terminal.sh
fi
```

## Verify

Open a NEW terminal and run:
```bash
pwd
```

Should show: `/home/pearlalgo/pearlalgo-dev-ai-agents`

NOT: `/home/pearlalgo/pearlalgo-dev-ai-agents/.venv`

## Note

Remember: `(.venv)` in your prompt is OK - it just means the virtual environment is active. But you should be in the project root directory, not inside the `.venv/` folder itself.


