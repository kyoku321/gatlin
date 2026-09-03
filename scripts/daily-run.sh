#!/usr/bin/env bash
# Horizon daily run
# Usage: ./scripts/daily-run.sh
# Cron:  0 8 * * * /path/to/horizon/scripts/daily-run.sh >> /path/to/horizon/logs/cron.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

retry() {
    local attempt
    for attempt in 1 2 3; do
        if "$@"; then
            return 0
        fi
        if (( attempt < 3 )); then
            echo "$LOG_PREFIX Command failed (attempt $attempt/3); retrying in 15 seconds..." >&2
            sleep 15
        fi
    done
    return 1
}

cd "$PROJECT_DIR"

echo "$LOG_PREFIX Starting Horizon daily run..."

# 1. Update to the latest main without requiring a clean worktree
retry git fetch --quiet origin main
git merge --ff-only origin/main

# 2. Install/update dependencies
uv sync --quiet

# 3. Run Horizon
uv run horizon --hours 24

echo "$LOG_PREFIX Done."
