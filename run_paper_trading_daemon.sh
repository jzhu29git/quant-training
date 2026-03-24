#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOST_PROJECT_ROOT="${HOST_PROJECT_ROOT:-$ROOT_DIR}"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"
ENV_FILE="$ROOT_DIR/run/panel.env"

mkdir -p "$LOG_DIR" "$PID_DIR"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

GATEWAY_BASE_URL="${FUTU_GATEWAY_BASE_URL:-http://127.0.0.1:8080}"
GATEWAY_MARKET="${FUTU_GATEWAY_MARKET:-CN}"
GATEWAY_AGENT_ID="${FUTU_GATEWAY_AGENT_ID:-aistockcn-paper-cn}"
GATEWAY_AGENT_KEY="${FUTU_GATEWAY_AGENT_KEY:-local-dev-agent-key}"
GATEWAY_AGENT_ID_HEADER="${FUTU_GATEWAY_AGENT_ID_HEADER:-X-Agent-Id}"
GATEWAY_AGENT_KEY_HEADER="${FUTU_GATEWAY_AGENT_KEY_HEADER:-X-Agent-Key}"
GATEWAY_ACCOUNT_ID="${FUTU_GATEWAY_ACCOUNT_ID:-}"
TOP_K="${PAPER_TRADING_TOP_K:-5}"
MIN_SCORE="${PAPER_TRADING_MIN_SCORE:-0.5}"
LOT_SIZE="${PAPER_TRADING_LOT_SIZE:-100}"
CASH_BUFFER_PCT="${PAPER_TRADING_CASH_BUFFER_PCT:-0.02}"
BUY_LIMIT_BPS="${PAPER_TRADING_BUY_LIMIT_BPS:-50}"
SELL_LIMIT_BPS="${PAPER_TRADING_SELL_LIMIT_BPS:-50}"
BUDGET_TOTAL="${PAPER_TRADING_BUDGET_TOTAL:-}"
INTERVAL_SECONDS="${PAPER_TRADING_INTERVAL_SECONDS:-300}"
MAX_ORDER_QTY="${PAPER_TRADING_MAX_ORDER_QTY:-1000}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/paper_trading_daemon_${TIMESTAMP}.log"
PID_FILE="$PID_DIR/paper_trading_daemon.pid"
LOGGER_PID_FILE="$PID_DIR/paper_trading_daemon_logger.pid"
CONTAINER_NAME="aistockcn-paper-trading-daemon-${TIMESTAMP}"

ARGS=(
  "run" "-d" "--name" "$CONTAINER_NAME" "--entrypoint" "python" "data-prep" "paper_trade_daemon.py"
  "--scores-path" "quant_data/models/inference_scores_latest.parquet"
  "--state-dir" "quant_data/paper_trading"
  "--gateway-base-url" "$GATEWAY_BASE_URL"
  "--market" "$GATEWAY_MARKET"
  "--agent-id" "$GATEWAY_AGENT_ID"
  "--agent-key" "$GATEWAY_AGENT_KEY"
  "--agent-id-header" "$GATEWAY_AGENT_ID_HEADER"
  "--agent-key-header" "$GATEWAY_AGENT_KEY_HEADER"
  "--top-k" "$TOP_K"
  "--min-score" "$MIN_SCORE"
  "--lot-size" "$LOT_SIZE"
  "--cash-buffer-pct" "$CASH_BUFFER_PCT"
  "--buy-limit-bps" "$BUY_LIMIT_BPS"
  "--sell-limit-bps" "$SELL_LIMIT_BPS"
  "--interval-seconds" "$INTERVAL_SECONDS"
  "--max-order-qty" "$MAX_ORDER_QTY"
)

if [[ -n "$GATEWAY_ACCOUNT_ID" ]]; then
  ARGS+=("--account-id" "$GATEWAY_ACCOUNT_ID")
fi

if [[ -n "$BUDGET_TOTAL" ]]; then
  ARGS+=("--budget-total" "$BUDGET_TOTAL")
fi

cd "$ROOT_DIR"
docker compose build data-prep

CONTAINER_ID="$(docker compose "${ARGS[@]}")"
echo "$CONTAINER_ID" > "$PID_FILE"

nohup docker logs -f "$CONTAINER_NAME" > "$LOG_FILE" 2>&1 &
echo $! > "$LOGGER_PID_FILE"

echo "Paper-trading daemon started"
echo "CONTAINER: $CONTAINER_NAME"
echo "CONTAINER_ID: $(cat "$PID_FILE")"
echo "LOGGER_PID: $(cat "$LOGGER_PID_FILE")"
echo "LOG: $LOG_FILE"
