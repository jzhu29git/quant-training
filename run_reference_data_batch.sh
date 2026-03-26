#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST_PROJECT_ROOT="${HOST_PROJECT_ROOT:-$ROOT_DIR}"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"

mkdir -p "$LOG_DIR" "$PID_DIR"

START_DATE="${START_DATE:-20200101}"
END_DATE="${END_DATE:-$(date -u +%Y%m%d)}"
SLEEP_SECONDS="${SLEEP_SECONDS:-0.2}"
LIMIT="${LIMIT:-0}"
SKIP_INDUSTRY="${SKIP_INDUSTRY:-0}"
OVERWRITE="${OVERWRITE:-0}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/reference_data_${TIMESTAMP}.log"
PID_FILE="$PID_DIR/reference_data.pid"
LOGGER_PID_FILE="$PID_DIR/reference_data_logger.pid"
CONTAINER_NAME="aistockcn-reference-data-${TIMESTAMP}"

ARGS=(
  "run" "-d" "--name" "$CONTAINER_NAME" "--entrypoint" "python" "data-prep" "refresh_reference_data.py"
  "--start-date" "$START_DATE"
  "--end-date" "$END_DATE"
  "--sleep" "$SLEEP_SECONDS"
)

if [[ "$LIMIT" != "0" ]]; then
  ARGS+=("--limit" "$LIMIT")
fi

if [[ "$SKIP_INDUSTRY" == "1" ]]; then
  ARGS+=("--skip-industry")
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

echo "Reference batch started"
echo "CONTAINER: $CONTAINER_NAME"
echo "CONTAINER_ID: $(cat "$PID_FILE")"
echo "LOGGER_PID: $(cat "$LOGGER_PID_FILE")"
echo "LOG: $LOG_FILE"
echo "STATE: $ROOT_DIR/quant_data/batch_state/reference_data_state.json"
echo "REFERENCE_STATUS: $ROOT_DIR/quant_data/reference/reference_status.json"
