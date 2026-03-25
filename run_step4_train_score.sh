#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST_PROJECT_ROOT="${HOST_PROJECT_ROOT:-$ROOT_DIR}"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"

mkdir -p "$LOG_DIR" "$PID_DIR"

TRAIN_PATH="${TRAIN_PATH:-quant_data/ml_features_ready.parquet}"
INFERENCE_PATH="${INFERENCE_PATH:-quant_data/inference_features_latest.parquet}"
MODEL_DIR="${MODEL_DIR:-quant_data/models}"
VALID_DAYS="${VALID_DAYS:-60}"
THRESHOLD="${THRESHOLD:-0.5}"
TOP_K="${TOP_K:-20}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/step4_train_score_${TIMESTAMP}.log"
PID_FILE="$PID_DIR/step4_train_score.pid"
LOGGER_PID_FILE="$PID_DIR/step4_train_score_logger.pid"
CONTAINER_NAME="aistockcn-step4-train-score-${TIMESTAMP}"

ARGS=(
  "run" "-d" "--name" "$CONTAINER_NAME" "--entrypoint" "python" "data-prep" "train_lightgbm.py"
  "--train-path" "$TRAIN_PATH"
  "--inference-path" "$INFERENCE_PATH"
  "--model-dir" "$MODEL_DIR"
  "--valid-days" "$VALID_DAYS"
  "--threshold" "$THRESHOLD"
  "--top-k" "$TOP_K"
)

cd "$ROOT_DIR"
docker compose build data-prep

CONTAINER_ID="$(docker compose "${ARGS[@]}")"
echo "$CONTAINER_ID" > "$PID_FILE"

nohup docker logs -f "$CONTAINER_NAME" > "$LOG_FILE" 2>&1 &
echo $! > "$LOGGER_PID_FILE"

echo "Step 4 train-and-score started"
echo "CONTAINER: $CONTAINER_NAME"
echo "CONTAINER_ID: $(cat "$PID_FILE")"
echo "LOGGER_PID: $(cat "$LOGGER_PID_FILE")"
echo "LOG: $LOG_FILE"
