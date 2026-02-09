#!/bin/bash
# Pre-commit hook for Pearl AI evaluation
#
# Install by running:
#   ln -sf ../../scripts/pre-commit-eval.sh .git/hooks/pre-commit
#
# Or add to .pre-commit-config.yaml:
#   - repo: local
#     hooks:
#       - id: pearl-eval
#         name: Pearl AI Eval
#         entry: scripts/pre-commit-eval.sh
#         language: script
#         files: ^pearl_ai/(brain|narrator|tools|config)\.py$

set -e

# Check if any prompt files are staged
PROMPT_FILES=$(git diff --cached --name-only | grep -E "^pearl_ai/(brain|narrator|tools|config)\.py$" || true)

if [ -z "$PROMPT_FILES" ]; then
    echo "No prompt files changed, skipping eval"
    exit 0
fi

echo "Prompt files changed:"
echo "$PROMPT_FILES"
echo ""
echo "Running Pearl AI evaluation..."

# Run eval in mock mode for speed (real eval runs in CI)
if command -v python3 &> /dev/null; then
    PYTHON=python3
else
    PYTHON=python
fi

# Try to use venv if available
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
fi

# Run quick eval
$PYTHON -m pearlalgo.pearl_ai.eval.ci \
    --dataset golden_core.json \
    --threshold 0.80 \
    --mock

RESULT=$?

if [ $RESULT -ne 0 ]; then
    echo ""
    echo "❌ Evaluation failed! Please review the failures above."
    echo "   Run 'python -m pearlalgo.pearl_ai.eval.ci --verbose' for more details."
    echo ""
    echo "To bypass (not recommended): git commit --no-verify"
    exit 1
fi

echo ""
echo "✓ Evaluation passed"
exit 0
