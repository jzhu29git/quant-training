#!/usr/bin/env python3
"""Generate profile-specific training features and run a labeled backtest."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CATALOG = "run/model_profiles.json"
DEFAULT_PROFILE = "short_5d"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a backtest for a named model profile.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="Profile name from run/model_profiles.json.")
    parser.add_argument("--catalog-path", default=DEFAULT_CATALOG, help="Profile catalog JSON path.")
    parser.add_argument("--data-dir", default="quant_data", help="Quant data root directory.")
    parser.add_argument("--sync-latest", action="store_true", help="Also update quant_data/backtests/latest artifacts.")
    return parser.parse_args()


def read_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"profile catalog not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"failed to load profile catalog {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"profile catalog must be a JSON object: {path}")
    return payload


def resolve_profile(catalog: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = catalog.get("profiles")
    if not isinstance(profiles, list):
        raise SystemExit("profile catalog is missing a profiles array")
    target = (profile_name or "").strip()
    for item in profiles:
        if isinstance(item, dict) and str(item.get("name") or "").strip() == target:
            return item
    available = ", ".join(
        str(item.get("name"))
        for item in profiles
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    )
    raise SystemExit(f"profile {profile_name!r} not found. Available profiles: {available}")


def run_command(args: list[str]) -> None:
    print(f"+ {' '.join(args)}", flush=True)
    subprocess.run(args, check=True)


def copy_latest_artifacts(*, run_dir: Path, backtest_root: Path) -> None:
    for name in ["summary.json", "equity_curve.parquet", "trade_log.parquet", "oos_predictions.parquet"]:
        source = run_dir / name
        if not source.exists():
            continue
        shutil.copy2(source, backtest_root / name)


def main() -> int:
    args = parse_args()
    root_dir = Path.cwd()
    catalog = read_catalog(root_dir / args.catalog_path)
    profile = resolve_profile(catalog, args.profile)
    data_dir = Path(args.data_dir)
    model_profile_root = data_dir / "model_profiles" / str(profile["name"])
    feature_path = model_profile_root / "ml_features_ready.parquet"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}__{profile['name']}"
    backtest_root = data_dir / "backtests"
    run_dir = backtest_root / "runs" / run_id

    model_profile_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    backtest_root.mkdir(parents=True, exist_ok=True)

    run_command(
        [
            sys.executable,
            "feature_engineering.py",
            "--data-dir",
            str(data_dir),
            "--output",
            str(feature_path),
            "--limit",
            "0",
            "--label-threshold",
            str(profile.get("label_threshold", 0.02)),
            "--label-horizon",
            str(profile.get("label_horizon", 5)),
            "--profile-name",
            str(profile["name"]),
        ]
    )
    run_command(
        [
            sys.executable,
            "backtest_walk_forward.py",
            "--train-path",
            str(feature_path),
            "--output-dir",
            str(run_dir),
            "--min-train-days",
            str(profile.get("backtest_min_train_days", 252)),
            "--retrain-every",
            str(profile.get("backtest_retrain_every", 20)),
            "--rebalance-every",
            str(profile.get("backtest_rebalance_every", 5)),
            "--top-k",
            str(profile.get("backtest_top_k", 5)),
            "--threshold",
            str(profile.get("score_threshold", 0.5)),
            "--profile-name",
            str(profile["name"]),
            "--profile-label",
            str(profile.get("label") or profile["name"]),
            "--label-horizon",
            str(profile.get("label_horizon", 5)),
            "--label-threshold",
            str(profile.get("label_threshold", 0.02)),
        ]
    )

    if args.sync_latest:
        copy_latest_artifacts(run_dir=run_dir, backtest_root=backtest_root)

    summary_path = run_dir / "summary.json"
    print(f"Backtest run completed: {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
