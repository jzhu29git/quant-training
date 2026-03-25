# AistockCN Quant Trading System

AistockCN is a full-stack quant research and operations project for the China A-share market. This shared source repository keeps the application code, workflow orchestration, architecture docs, and deployment setup while excluding local datasets, logs, and runtime secrets.

## Core Capabilities

- End-to-end market-data ingestion for the full A-share universe
- Feature engineering for training and inference snapshots
- LightGBM model training and scoring
- Walk-forward out-of-sample backtesting
- Automated paper-trading reconciliation through an external gateway
- A FastAPI + Next.js control panel for monitoring, inspection, and operations
- Container-first deployment and long-running batch orchestration

## Stack

- Frontend: Next.js 15, React 19, TypeScript
- Backend: FastAPI, Uvicorn, Python 3
- Data: Pandas, PyArrow, parquet artifacts
- ML: LightGBM, scikit-learn
- Market data: BaoStock plus AKShare fallback/enrichment
- Ops: Docker, Docker Compose

## Repository Layout

```text
apps/
  api/        FastAPI control and inspection API
  web/        Next.js operator dashboard
docs/         Public-facing architecture and usage docs
run/          Safe example configs and model profile definitions
*.py          Data, feature, model, backtest, and trading workflow scripts
*.sh          Operational runners for repeatable batch jobs
```

## Pipeline Overview

### Step 1. Data Prepare

- Refresh the current A-share universe and canonical stock registry
- Download or update per-symbol daily kline parquet files
- Download or update daily valuation parquet files

### Step 2. Training Features

- Merge raw market and valuation data
- Generate model-ready features plus forward-return labels

### Step 3. Inference Features

- Build the latest feature snapshot without future labels

### Step 4. Train And Score

- Train the latest LightGBM model
- Save model artifacts and training metadata
- Score the latest inference snapshot

### Step 5. Backtest

- Run expanding-window walk-forward backtests
- Compare profile variants across saved runs

### Step 6. Auto Paper Trading

- Monitor new scored snapshots
- Reconcile target holdings with an existing Futu gateway
- Persist local paper-trading state and sync history

## Run Locally

### Build images

```bash
docker compose build
```

### Start the panel

```bash
cp run/panel.env.example run/panel.env
cp run/panel_users.example.json run/panel_users.json
docker compose up -d panel-api panel-web
```

Before first start, replace the example auth secrets and password hashes in those local copies.
Generate a new hash with:

```bash
node apps/web/scripts/hash-password.mjs 'replace-with-a-real-password'
```

If you use the single-user env fallback instead of `run/panel_users.json`, set `PANEL_PASSWORD_HASH` rather than `PANEL_PASSWORD`.
The default API IP policy is `localhost` plus the local `panel-web` service only, not the whole Compose subnet.

Panel endpoints:

- Web: `http://localhost:3030`
- API: `http://localhost:8001`

### Start the major jobs

```bash
bash run_a_share_3y_batch.sh
bash run_step2_feature_engineering.sh
bash run_step3_inference_features.sh
bash run_step4_train_score.sh
bash run_step5_backtest.sh
bash run_paper_trading_daemon.sh
```

## Shared Repository Notes

This shared source snapshot excludes:

- `quant_data/`
- `logs/`
- runtime PID/state files
- real local credentials such as `run/panel.env` and `run/panel_users.json`

Safe examples are included instead:

- `run/panel.env.example`
- `run/panel_users.example.json`

## Docs

- [User Guide](docs/USER_GUIDE.md)
- [System Design Spec](docs/SYSTEM_DESIGN_SPEC.md)
- [System Manual](docs/SYSTEM_MANUAL.md)

## Engineering Scope

This codebase covers practical production-oriented engineering work, not only model experimentation:

- backend API design
- frontend dashboard implementation
- data engineering workflow design
- ML training and evaluation plumbing
- batch orchestration
- containerized deployment
- operational safety around secrets and runtime artifacts
