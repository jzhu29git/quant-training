#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST_PROJECT_ROOT="${HOST_PROJECT_ROOT:-$ROOT_DIR}"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"

mkdir -p "$LOG_DIR" "$PID_DIR"

TRAIN_PATH="${TRAIN_PATH:-quant_data/ml_features_ready.parquet}"
OUTPUT_DIR="${OUTPUT_DIR:-quant_data/backtests}"
PROFILE_NAME="${PROFILE_NAME:-short_5d}"
MIN_TRAIN_DAYS="${MIN_TRAIN_DAYS:-252}"
RETRAIN_EVERY="${RETRAIN_EVERY:-20}"
REBALANCE_EVERY="${REBALANCE_EVERY:-5}"
TOP_K="${TOP_K:-5}"
THRESHOLD="${THRESHOLD:-0.5}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/step5_backtest_${TIMESTAMP}.log"
PID_FILE="$PID_DIR/step5_backtest.pid"
LOGGER_PID_FILE="$PID_DIR/step5_backtest_logger.pid"
CONTAINER_NAME="aistockcn-step5-backtest-${TIMESTAMP}"

ARGS=(
  "run" "-d" "--name" "$CONTAINER_NAME" "--entrypoint" "python" "data-prep" "backtest_profile_runner.py"
  "--profile" "$PROFILE_NAME"
  "--sync-latest"
)

cd "$ROOT_DIR"
docker compose build data-prep

CONTAINER_ID="$(docker compose "${ARGS[@]}")"
echo "$CONTAINER_ID" > "$PID_FILE"

nohup docker logs -f "$CONTAINER_NAME" > "$LOG_FILE" 2>&1 &
echo $! > "$LOGGER_PID_FILE"

echo "Backtest started"
echo "CONTAINER: $CONTAINER_NAME"
echo "CONTAINER_ID: $(cat "$PID_FILE")"
echo "LOGGER_PID: $(cat "$LOGGER_PID_FILE")"
echo "LOG: $LOG_FILE"
