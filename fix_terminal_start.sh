#!/bin/bash
# Auto-fix: If terminal starts in .venv, go to project root instead

# Only run if we're in a subdirectory of the project
if [[ "$PWD" == *"pearlalgo-dev-ai-agents/.venv"* ]] || [[ "$PWD" == *"pearlalgo-dev-ai-agents"*"/.venv" ]]; then
    # We're inside .venv directory, go to project root
    cd ~/pearlalgo-dev-ai-agents 2>/dev/null || cd "$HOME/pearlalgo-dev-ai-agents" 2>/dev/null
fi


