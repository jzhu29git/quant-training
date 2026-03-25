# System Design Spec

## Goal

Build an operator-friendly quant workflow for the China A-share market that can ingest data, train models, produce ranked signals, run backtests, and coordinate paper trading through an external gateway.

## Main Components

- `download_data.py` and `batch_download_all_a.py`
  - universe refresh and raw parquet ingestion
- `feature_engineering.py`
  - training feature generation
- `build_inference_features.py`
  - inference-only feature generation
- `train_lightgbm.py`
  - model training, metadata export, and scoring
- `backtest_walk_forward.py`
  - walk-forward historical evaluation
- `paper_trade_futu.py` and `paper_trade_daemon.py`
  - paper-trading orchestration
- `apps/api`
  - operational API layer
- `apps/web`
  - dashboard and control surface

## Architecture

The system is organized around local parquet artifacts and deterministic workflow steps.

1. Step 1 refreshes the stock universe and raw market data.
2. Step 2 converts raw data into the training panel.
3. Step 3 builds the latest inference snapshot.
4. Step 4 trains the model and writes scores.
5. Step 5 runs backtests on historical windows.
6. Step 6 consumes scored snapshots and reconciles paper-trading intent.

The API and dashboard sit on top of those artifacts and runtime logs rather than duplicating state in a separate application database.

## Deployment Model

- Docker Compose is the primary local and server deployment entry point.
- The panel API serves both inspection and workflow-control routes.
- API client IP checks should stay narrow: localhost plus explicitly trusted local services only.
- The web app reads the panel auth config from mounted runtime files.

## Security Model

- Public repos should include only example config files.
- Runtime secrets are expected to live in local `run/` files that are git-ignored.
- The panel uses signed cookies and an admin key for workflow control endpoints.
- Recent changes also redact the paper-trading agent key from generated control-panel log stubs.

## Operational Priorities

- clear artifact lineage
- restartable batch jobs
- inspectable logs and state files
- low-friction local deployment
- explicit workflow visibility for operators
