# System Manual

## End-to-End Workflow

### Data Prepare

`batch_download_all_a.py` coordinates the full-market data refresh.

Outputs include:

- active stock universe snapshots
- canonical stock registry history
- per-symbol daily kline parquet files
- per-symbol daily valuation parquet files

### Training Features

`feature_engineering.py` merges raw artifacts into a model-ready training table and derives labels such as forward return and binary classification targets.

### Inference Features

`build_inference_features.py` creates the latest scoring snapshot with the same stable feature schema but without future labels.

### Training And Scoring

`train_lightgbm.py` trains the current model, saves metadata, and writes ranked inference scores for the latest snapshot.

### Backtesting

`backtest_walk_forward.py` runs expanding-window walk-forward backtests and writes comparable run artifacts for later review.

### Paper Trading

`paper_trade_futu.py` converts ranked signals into target holdings and simulated orders for an external Futu gateway.

`paper_trade_daemon.py` keeps watching for new score snapshots and only reconciles when a new signal set appears.

## Operational Scripts

The repository includes dedicated runner scripts for stable container naming, log capture, and PID/state artifacts:

- `run_a_share_3y_batch.sh`
- `run_full_market_3y_batch.sh`
- `run_step2_feature_engineering.sh`
- `run_step3_inference_features.sh`
- `run_step4_train_score.sh`
- `run_step5_backtest.sh`
- `run_paper_trading_daemon.sh`

## Artifact Philosophy

This project relies on simple, inspectable artifacts instead of hiding state behind multiple services:

- parquet datasets for core pipeline outputs
- JSON metadata for model and runtime state
- log files for batch and daemon visibility

That choice makes the system easier to debug, demo, and operate in a small-team environment.
