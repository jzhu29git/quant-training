#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST_PROJECT_ROOT="${HOST_PROJECT_ROOT:-$ROOT_DIR}"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"

mkdir -p "$LOG_DIR" "$PID_DIR"

DATA_DIR="${DATA_DIR:-quant_data}"
OUTPUT_PATH="${OUTPUT_PATH:-quant_data/ml_features_ready.parquet}"
LIMIT="${LIMIT:-0}"
LABEL_THRESHOLD="${LABEL_THRESHOLD:-0.02}"
LABEL_HORIZON="${LABEL_HORIZON:-5}"
PROFILE_NAME="${PROFILE_NAME:-short_5d}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/step2_feature_engineering_${TIMESTAMP}.log"
PID_FILE="$PID_DIR/step2_feature_engineering.pid"
LOGGER_PID_FILE="$PID_DIR/step2_feature_engineering_logger.pid"
CONTAINER_NAME="aistockcn-step2-feature-engineering-${TIMESTAMP}"

ARGS=(
  "run" "-d" "--name" "$CONTAINER_NAME" "--entrypoint" "python" "data-prep" "feature_engineering.py"
  "--data-dir" "$DATA_DIR"
  "--output" "$OUTPUT_PATH"
  "--limit" "$LIMIT"
  "--label-threshold" "$LABEL_THRESHOLD"
  "--label-horizon" "$LABEL_HORIZON"
  "--profile-name" "$PROFILE_NAME"
)

cd "$ROOT_DIR"
docker compose build data-prep

CONTAINER_ID="$(docker compose "${ARGS[@]}")"
echo "$CONTAINER_ID" > "$PID_FILE"

nohup docker logs -f "$CONTAINER_NAME" > "$LOG_FILE" 2>&1 &
echo $! > "$LOGGER_PID_FILE"

echo "Step 2 feature engineering started"
echo "CONTAINER: $CONTAINER_NAME"
echo "CONTAINER_ID: $(cat "$PID_FILE")"
echo "LOGGER_PID: $(cat "$LOGGER_PID_FILE")"
echo "LOG: $LOG_FILE"
