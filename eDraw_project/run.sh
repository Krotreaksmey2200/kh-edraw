#!/usr/bin/env bash
# run.sh - ចុចដំណើរការ eDraw ភ្លាមៗ (Quick Launcher for eDraw)

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# ពិនិត្យមើល virtual environment
if [ -f "$DIR/venv/bin/python" ]; then
    PYTHON="$DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "រកមិនឃើញ Python! សូមតម្លើង Python 3.10+ ជាមុនសិន។"
    exit 1
fi

echo "កំពុងបើកដំណើរការ eDraw..."
exec "$PYTHON" main.py "$@"
