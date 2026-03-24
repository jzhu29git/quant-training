#!/usr/bin/env python3
"""Run the Futu paper-trading reconciler on a fixed interval."""

from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path
from typing import Any

from paper_trade_futu import SyncConfig, build_config, now_iso, read_json, sync_once, write_json


STOP_REQUESTED = False


def signal_handler(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(f"[{now_iso()}] received signal {signum}, stopping paper-trading daemon", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interval daemon for the Futu paper-trading reconciler.")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--scores-path", default="quant_data/models/inference_scores_latest.parquet")
    parser.add_argument("--state-dir", default="quant_data/paper_trading")
    parser.add_argument("--gateway-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--market", default="CN")
    parser.add_argument("--agent-id", default="aistockcn-paper-cn")
    parser.add_argument("--agent-key", default="local-dev-agent-key")
    parser.add_argument("--agent-id-header", default="X-Agent-Id")
    parser.add_argument("--agent-key-header", default="X-Agent-Key")
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--lot-size", type=int, default=100)
    parser.add_argument("--cash-buffer-pct", type=float, default=0.02)
    parser.add_argument("--buy-limit-bps", type=float, default=50.0)
    parser.add_argument("--sell-limit-bps", type=float, default=50.0)
    parser.add_argument("--budget-total", type=float, default=None)
    parser.add_argument("--max-order-qty", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-cancel-open-orders", action="store_true")
    parser.add_argument("--no-sync-existing-orders", action="store_true")
    return parser.parse_args()


def write_daemon_state(config: SyncConfig, **updates: Any) -> None:
    state_path = Path(config.state_dir) / "state.json"
    state = read_json(state_path)
    daemon_state = dict(state.get("daemon") or {})
    daemon_state.update(updates)
    daemon_state["updated_at"] = now_iso()
    state["daemon"] = daemon_state
    write_json(state_path, state)


def main() -> int:
    args = parse_args()
    config = build_config(args)
    interval_seconds = max(int(args.interval_seconds), 30)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print(f"[{now_iso()}] paper-trading daemon booting with {interval_seconds}s interval", flush=True)
    write_daemon_state(
        config,
        is_running=True,
        interval_seconds=interval_seconds,
        started_at=now_iso(),
        last_heartbeat_at=now_iso(),
    )

    try:
        while not STOP_REQUESTED:
            write_daemon_state(config, is_running=True, last_heartbeat_at=now_iso())
            code, state = sync_once(config)
            print(
                f"[{now_iso()}] sync result: status={state.get('last_status') or state.get('status')} "
                f"message={state.get('last_message') or state.get('message')}",
                flush=True,
            )
            sleep_seconds = interval_seconds if code == 0 else min(interval_seconds, 60)
            for _ in range(sleep_seconds):
                if STOP_REQUESTED:
                    break
                time.sleep(1)
    finally:
        write_daemon_state(config, is_running=False, stopped_at=now_iso(), last_heartbeat_at=now_iso())
        print(f"[{now_iso()}] paper-trading daemon stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
