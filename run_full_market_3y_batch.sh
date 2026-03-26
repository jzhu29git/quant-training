#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST_PROJECT_ROOT="${HOST_PROJECT_ROOT:-$ROOT_DIR}"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"

mkdir -p "$LOG_DIR" "$PID_DIR"

START_DATE="${START_DATE:-20230322}"
END_DATE="${END_DATE:-20260322}"
SLEEP_SECONDS="${SLEEP_SECONDS:-1.2}"
PAUSE_MINUTES="${PAUSE_MINUTES:-15}"
MAX_PASSES="${MAX_PASSES:-5}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-6}"
RELOGIN_EVERY="${RELOGIN_EVERY:-300}"
PER_CODE_TIMEOUT_SECONDS="${PER_CODE_TIMEOUT_SECONDS:-300}"
INCLUDE_INDUSTRY="${INCLUDE_INDUSTRY:-0}"
OVERWRITE="${OVERWRITE:-0}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/full_market_3y_${TIMESTAMP}.log"
PID_FILE="$PID_DIR/full_market_3y.pid"
LOGGER_PID_FILE="$PID_DIR/full_market_3y_logger.pid"
CONTAINER_NAME="aistockcn-full-market-3y-${TIMESTAMP}"

ARGS=(
  "run" "-d" "--name" "$CONTAINER_NAME" "--entrypoint" "python" "data-prep" "batch_download_all_a.py"
  "--start-date" "$START_DATE"
  "--end-date" "$END_DATE"
  "--sleep" "$SLEEP_SECONDS"
  "--pause-minutes" "$PAUSE_MINUTES"
  "--max-passes" "$MAX_PASSES"
  "--max-attempts" "$MAX_ATTEMPTS"
  "--relogin-every" "$RELOGIN_EVERY"
  "--per-code-timeout-seconds" "$PER_CODE_TIMEOUT_SECONDS"
)

if [[ "$INCLUDE_INDUSTRY" == "1" ]]; then
  ARGS+=("--include-industry")
fi

if [[ "$OVERWRITE" == "1" ]]; then
  ARGS+=("--overwrite")
fi

cd "$ROOT_DIR"
docker compose build data-prep

CONTAINER_ID="$(docker compose "${ARGS[@]}")"
echo "$CONTAINER_ID" > "$PID_FILE"

nohup docker logs -f "$CONTAINER_NAME" > "$LOG_FILE" 2>&1 &
echo $! > "$LOGGER_PID_FILE"

echo "Batch started"
echo "CONTAINER: $CONTAINER_NAME"
echo "CONTAINER_ID: $(cat "$PID_FILE")"
echo "LOGGER_PID: $(cat "$LOGGER_PID_FILE")"
echo "LOG: $LOG_FILE"
echo "STATE: $ROOT_DIR/quant_data/batch_state/all_a_3y_state.json"
