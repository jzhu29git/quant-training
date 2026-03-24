#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST_PROJECT_ROOT="${HOST_PROJECT_ROOT:-$ROOT_DIR}"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"

mkdir -p "$LOG_DIR" "$PID_DIR"

DATA_DIR="${DATA_DIR:-quant_data}"
OUTPUT_PATH="${OUTPUT_PATH:-quant_data/inference_features_latest.parquet}"
LIMIT="${LIMIT:-0}"
AS_OF_DATE="${AS_OF_DATE:-}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/step4_inference_features_${TIMESTAMP}.log"
PID_FILE="$PID_DIR/step4_inference_features.pid"
LOGGER_PID_FILE="$PID_DIR/step4_inference_features_logger.pid"
CONTAINER_NAME="aistockcn-step4-inference-features-${TIMESTAMP}"

ARGS=(
  "run" "-d" "--name" "$CONTAINER_NAME" "--entrypoint" "python" "data-prep" "build_inference_features.py"
  "--data-dir" "$DATA_DIR"
  "--output" "$OUTPUT_PATH"
  "--limit" "$LIMIT"
)

if [[ -n "$AS_OF_DATE" ]]; then
  ARGS+=("--as-of-date" "$AS_OF_DATE")
fi

cd "$ROOT_DIR"
docker compose build data-prep

CONTAINER_ID="$(docker compose "${ARGS[@]}")"
echo "$CONTAINER_ID" > "$PID_FILE"

nohup docker logs -f "$CONTAINER_NAME" > "$LOG_FILE" 2>&1 &
echo $! > "$LOGGER_PID_FILE"

echo "Step 4 inference features started"
echo "CONTAINER: $CONTAINER_NAME"
echo "CONTAINER_ID: $(cat "$PID_FILE")"
echo "LOGGER_PID: $(cat "$LOGGER_PID_FILE")"
echo "LOG: $LOG_FILE"
