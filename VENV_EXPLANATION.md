# Virtual Environment Explanation

## What's Happening?

When you see commands like:
```bash
cd ~/pearlalgo-dev-ai-agents && source .venv/bin/activate
```

**You are NOT being put into the `.venv` directory!**

## What Actually Happens:

1. **`cd ~/pearlalgo-dev-ai-agents`**
   - Changes to your project directory
   - You're now in: `/home/pearlalgo/pearlalgo-dev-ai-agents/`

2. **`source .venv/bin/activate`**
   - Activates the Python virtual environment
   - **You STAY in the project root directory**
   - Your prompt changes to show `(.venv)` but you're still in the project root
   - This just tells Python to use packages from `.venv/` instead of system Python

## Directory Structure:

```
/home/pearlalgo/pearlalgo-dev-ai-agents/    ← YOU ARE HERE (project root)
├── .venv/                                  ← Virtual environment (just a folder)
│   ├── bin/
│   │   └── activate                        ← Script we run
│   ├── lib/                                ← Python packages installed here
│   └── ...
├── src/                                    ← Your code
├── config/                                 ← Config files
└── ...

```

## Why Activate the Virtual Environment?

- **Isolation**: Keeps project dependencies separate from system Python
- **Version Control**: Ensures everyone uses the same package versions
- **Clean Environment**: No conflicts with other projects

## What the `(.venv)` Prompt Means:

When you see `(.venv)` in your prompt:
```
(.venv) pearlalgo@px-core:~/pearlalgo-dev-ai-agents$
```

This means:
- ✅ You're in the project directory: `~/pearlalgo-dev-ai-agents`
- ✅ Virtual environment is active (Python uses packages from `.venv/`)
- ❌ You're NOT in the `.venv/` directory itself

## To Verify:

```bash
# Check current directory
pwd
# Should show: /home/pearlalgo/pearlalgo-dev-ai-agents

# Check if venv is active
echo $VIRTUAL_ENV
# Should show: /home/pearlalgo/pearlalgo-dev-ai-agents/.venv

# You're still in project root, not in .venv!
```

## If You Want to Work WITHOUT Activating:

You can also run Python directly:
```bash
# Without activation
~/pearlalgo-dev-ai-agents/.venv/bin/python your_script.py

# Or use the full path
python -m pearlalgo.live.langgraph_trader
```

But activating is easier because then you can just use `python` instead of the full path.

## Summary:

- **You're always in the project root** (`~/pearlalgo-dev-ai-agents`)
- **Activating venv** just tells Python where to find packages
- **The `(.venv)` prompt** is just a reminder that venv is active
- **You're NOT in the `.venv/` directory** - you're in the project root!


