# User Guide

## What The Dashboard Is For

The web panel is built for operators and reviewers who need to inspect the current state of the quant workflow without opening files or shell logs manually.

## Main Pages

### Overview

- quick health snapshot
- latest dataset and model signals
- recent batch pulse

### Pipeline

- daily pipeline status
- per-step runtime details
- workflow control actions for admins

### Explorer

- inspect saved parquet datasets
- search, sort, and export records

### Models

- latest training metrics
- backtest summary
- feature importance

### Picks

- latest ranked inference results
- highest-scoring names in the current snapshot

### Paper

- paper-trading daemon status
- gateway health
- target holdings, live positions, and order history

### Admin

- schema and artifact alignment checks
- workflow map and runtime artifact overview

## Typical Review Flow

1. Open `Overview` for the current snapshot.
2. Inspect `Pipeline` to verify the latest workflow state.
3. Open `Picks` to review ranked signals.
4. Use `Models` to inspect validation and backtest metrics.
5. Use `Paper` when reviewing the downstream execution path.

## Login

The public repository includes only example auth files. For local use:

```bash
cp run/panel.env.example run/panel.env
cp run/panel_users.example.json run/panel_users.json
```

Update those local copies with your own values before starting the panel.

