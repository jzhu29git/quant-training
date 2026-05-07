#!/usr/bin/env python3
"""Score latest inference features with an already-trained LightGBM model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def encode_categorical(series: pd.Series, categories: list[str]) -> np.ndarray:
    normalized = series.fillna("UNKNOWN").astype("string")
    return pd.Categorical(normalized, categories=categories).codes.astype(np.int32, copy=False)


def build_category_mappings(
    train_path: Path,
    inference_df: pd.DataFrame,
    categorical_cols: list[str],
) -> dict[str, list[str]]:
    mappings: dict[str, list[str]] = {}
    if not categorical_cols:
        return mappings
    train_df = pd.read_parquet(train_path, columns=categorical_cols)
    for col in categorical_cols:
        seen = {"UNKNOWN"}
        for frame in (train_df, inference_df):
            if col not in frame.columns:
                continue
            for value in frame[col].dropna().unique().tolist():
                text = str(value)
                if text:
                    seen.add(text)
        mappings[col] = ["UNKNOWN"] + sorted(value for value in seen if value != "UNKNOWN")
    return mappings


def build_feature_frame(
    inference_df: pd.DataFrame,
    feature_cols: list[str],
    categorical_cols: list[str],
    category_mappings: dict[str, list[str]],
) -> pd.DataFrame:
    feature_data: dict[str, np.ndarray] = {}
    for col in feature_cols:
        if col not in inference_df.columns:
            feature_data[col] = np.full(len(inference_df), np.nan, dtype=np.float32)
            continue
        if col in categorical_cols:
            feature_data[col] = encode_categorical(inference_df[col], category_mappings.get(col, ["UNKNOWN"]))
        else:
            feature_data[col] = pd.to_numeric(inference_df[col], errors="coerce").to_numpy(dtype=np.float32)
    return pd.DataFrame(feature_data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score inference features using a saved LightGBM model.")
    parser.add_argument("--model-dir", required=True, help="Directory containing lightgbm_model.txt and training_metadata.json.")
    parser.add_argument("--train-path", required=True, help="Training feature parquet, used only for categorical encoding.")
    parser.add_argument("--inference-path", required=True, help="Latest inference feature parquet.")
    parser.add_argument("--output", required=True, help="Output scored parquet path.")
    parser.add_argument("--top-k", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model_dir = Path(args.model_dir)
    train_path = Path(args.train_path)
    inference_path = Path(args.inference_path)
    output_path = Path(args.output)

    metadata = read_json(model_dir / "training_metadata.json")
    feature_cols = [str(col) for col in metadata["feature_cols"]]
    categorical_cols = [str(col) for col in metadata.get("categorical_cols", [])]

    inference_df = pd.read_parquet(inference_path)
    mappings = build_category_mappings(train_path, inference_df, categorical_cols)
    X = build_feature_frame(inference_df, feature_cols, categorical_cols, mappings)

    booster = lgb.Booster(model_file=str(model_dir / "lightgbm_model.txt"))
    scored = inference_df.copy()
    scored["score"] = booster.predict(X)
    scored = scored.sort_values("score", ascending=False).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(output_path, index=False)

    preview_cols = [col for col in ["date", "code", "name", "industry", "score", "close"] if col in scored.columns]
    print(f"scored {len(scored)} rows -> {output_path}")
    print(scored[preview_cols].head(args.top_k).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
