#!/usr/bin/env python3
"""Train a LightGBM model and score the latest inference features."""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.types as patypes
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score


DEFAULT_TRAIN_PATH = "quant_data/ml_features_ready.parquet"
DEFAULT_INFERENCE_PATH = "quant_data/inference_features_latest.parquet"
DEFAULT_MODEL_DIR = "quant_data/models"


def feature_metadata_path(train_path: Path) -> Path:
    return train_path.with_suffix(train_path.suffix + ".meta.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train LightGBM on engineered A-share features.")
    parser.add_argument("--train-path", default=DEFAULT_TRAIN_PATH, help="Training parquet path.")
    parser.add_argument("--inference-path", default=DEFAULT_INFERENCE_PATH, help="Inference parquet path.")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR, help="Directory for model outputs.")
    parser.add_argument(
        "--valid-days",
        type=int,
        default=60,
        help="Use the latest N unique trade dates in the training set as validation.",
    )
    parser.add_argument("--threshold", type=float, default=0.5, help="Classification threshold.")
    parser.add_argument("--top-k", type=int, default=20, help="Number of top inference picks to print.")
    return parser.parse_args()


def choose_feature_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    drop_cols = {
        "date",
        "code",
        "exchange",
        "name",
        "future_return",
        "label",
    }
    categorical_cols = [col for col in ["industry", "industry_classification", "universe"] if col in df.columns]
    feature_cols = [col for col in df.columns if col not in drop_cols]
    unsupported_cols = [
        col
        for col in feature_cols
        if (pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col])) and col not in categorical_cols
    ]
    feature_cols = [col for col in feature_cols if col not in unsupported_cols]
    return feature_cols, categorical_cols


def choose_feature_columns_from_schema(column_types: dict[str, object]) -> tuple[list[str], list[str]]:
    drop_cols = {
        "date",
        "code",
        "exchange",
        "name",
        "future_return",
        "label",
    }
    categorical_cols = [col for col in ["industry", "industry_classification", "universe"] if col in column_types]
    feature_cols = [col for col in column_types if col not in drop_cols]
    unsupported_cols = [
        col
        for col in feature_cols
        if (
            patypes.is_string(column_types[col])
            or patypes.is_large_string(column_types[col])
            or patypes.is_binary(column_types[col])
            or patypes.is_large_binary(column_types[col])
        )
        and col not in categorical_cols
    ]
    feature_cols = [col for col in feature_cols if col not in unsupported_cols]
    return feature_cols, categorical_cols


def load_parquet_column_types(path: Path) -> dict[str, object]:
    schema = pq.read_schema(path)
    return {field.name: field.type for field in schema}


def load_frame(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    try:
        return pd.read_parquet(path, columns=columns, dtype_backend="pyarrow")
    except TypeError:
        return pd.read_parquet(path, columns=columns)


def prepare_frame(df: pd.DataFrame, categorical_cols: list[str]) -> pd.DataFrame:
    for col in categorical_cols:
        if col in df.columns:
            df[col] = df[col].fillna("UNKNOWN").astype("category")
    return df


def split_date_masks(dates: pd.Series, valid_days: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    date_values = pd.to_datetime(dates).to_numpy()
    unique_dates = np.sort(np.unique(date_values[~pd.isna(date_values)]))
    if len(unique_dates) <= valid_days:
        raise SystemExit(f"可用交易日只有 {len(unique_dates)} 个，无法切出 {valid_days} 天验证集。")

    valid_start = unique_dates[-valid_days]
    train_mask = date_values < valid_start
    valid_mask = date_values >= valid_start

    if not train_mask.any() or not valid_mask.any():
        raise SystemExit("训练集或验证集为空，请调整 valid-days。")

    return date_values, train_mask, valid_mask


def build_category_mappings(
    train_df: pd.DataFrame,
    inference_df: pd.DataFrame,
    categorical_cols: list[str],
) -> dict[str, list[str]]:
    mappings: dict[str, list[str]] = {}
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


def encode_categorical_values(series: pd.Series, categories: list[str]) -> np.ndarray:
    normalized = series.fillna("UNKNOWN").astype("string")
    encoded = pd.Categorical(normalized, categories=categories).codes
    return encoded.astype(np.int32, copy=False)


def build_feature_frame(
    df: pd.DataFrame,
    feature_cols: list[str],
    categorical_cols: list[str],
    category_mappings: dict[str, list[str]],
    row_mask: np.ndarray | None = None,
) -> pd.DataFrame:
    feature_data: dict[str, np.ndarray] = {}
    for col in feature_cols:
        if col in categorical_cols:
            values = encode_categorical_values(df[col], category_mappings[col])
        else:
            values = df[col].to_numpy(dtype=np.float32, na_value=np.nan)
        if row_mask is not None:
            values = values[row_mask]
        feature_data[col] = values
    return pd.DataFrame(feature_data)


def build_split_feature_frames(
    df: pd.DataFrame,
    feature_cols: list[str],
    categorical_cols: list[str],
    category_mappings: dict[str, list[str]],
    train_mask: np.ndarray,
    valid_mask: np.ndarray,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_data: dict[str, np.ndarray] = {}
    valid_data: dict[str, np.ndarray] = {}
    for col in feature_cols:
        if col in categorical_cols:
            values = encode_categorical_values(df[col], category_mappings[col])
        else:
            values = df[col].to_numpy(dtype=np.float32, na_value=np.nan)
        train_data[col] = values[train_mask]
        valid_data[col] = values[valid_mask]
    return pd.DataFrame(train_data), pd.DataFrame(valid_data)


def compute_metrics(y_true: pd.Series, prob: pd.Series, threshold: float) -> dict[str, float]:
    pred = (prob >= threshold).astype(int)
    return {
        "auc": float(roc_auc_score(y_true, prob)),
        "accuracy": float(accuracy_score(y_true, pred)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "positive_rate": float(y_true.mean()),
    }


def log(message: str) -> None:
    print(message, flush=True)


def load_feature_metadata(train_path: Path) -> dict[str, object]:
    metadata_path = feature_metadata_path(train_path)
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def main() -> int:
    args = parse_args()

    train_path = Path(args.train_path)
    inference_path = Path(args.inference_path)
    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    feature_metadata = load_feature_metadata(train_path)

    train_column_types = load_parquet_column_types(train_path)
    feature_cols, categorical_cols = choose_feature_columns_from_schema(train_column_types)
    train_columns = list(dict.fromkeys(["date", "label", *feature_cols]))

    log(f"加载训练数据: {train_path}")
    log(f"训练列数: {len(train_columns)}，模型特征数: {len(feature_cols)}，类别特征: {len(categorical_cols)}")
    train_df = load_frame(train_path, columns=train_columns)

    log(f"加载打分数据: {inference_path}")
    inference_df = load_frame(inference_path)
    log(f"训练集形状: {train_df.shape}，打分集形状: {inference_df.shape}")

    train_df["date"] = pd.to_datetime(train_df["date"])
    inference_df["date"] = pd.to_datetime(inference_df["date"])

    category_mappings = build_category_mappings(train_df, inference_df, categorical_cols)
    date_values, train_mask, valid_mask = split_date_masks(train_df["date"], args.valid_days)
    train_rows = int(train_mask.sum())
    valid_rows = int(valid_mask.sum())
    log(f"训练/验证切分完成: train={train_rows:,}，valid={valid_rows:,}")

    label_values = train_df["label"].to_numpy(dtype=np.int8, na_value=0)
    y_train = label_values[train_mask]
    y_valid = label_values[valid_mask]

    log("构建训练与验证特征矩阵...")
    X_train, X_valid = build_split_feature_frames(
        train_df,
        feature_cols,
        categorical_cols,
        category_mappings,
        train_mask,
        valid_mask,
    )

    train_dates = date_values[train_mask]
    valid_dates = date_values[valid_mask]

    del train_mask
    del valid_mask
    del date_values
    del label_values
    del train_df
    gc.collect()

    log(f"特征矩阵完成: X_train={X_train.shape}，X_valid={X_valid.shape}")

    model = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=63,
        subsample=0.8,
        colsample_bytree=0.8,
        force_col_wise=True,
        random_state=42,
        class_weight="balanced",
    )

    log("开始训练 LightGBM...")
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_valid, y_valid)],
        eval_metric="auc",
        categorical_feature=categorical_cols,
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    valid_prob = pd.Series(model.predict_proba(X_valid)[:, 1])
    metrics = compute_metrics(y_valid, valid_prob, args.threshold)
    log("训练完成，开始写出模型与指标...")

    model.booster_.save_model(str(model_dir / "lightgbm_model.txt"))
    pd.DataFrame(
        {
            "feature": feature_cols,
            "importance_gain": model.booster_.feature_importance(importance_type="gain"),
            "importance_split": model.booster_.feature_importance(importance_type="split"),
        }
    ).sort_values("importance_gain", ascending=False).to_csv(
        model_dir / "feature_importance.csv",
        index=False,
        encoding="utf-8-sig",
    )

    metadata = {
        "feature_cols": feature_cols,
        "categorical_cols": categorical_cols,
        "profile_name": feature_metadata.get("profile_name"),
        "label_horizon": feature_metadata.get("label_horizon"),
        "label_threshold": feature_metadata.get("label_threshold"),
        "feature_metadata_path": str(feature_metadata_path(train_path)) if feature_metadata else None,
        "valid_days": args.valid_days,
        "threshold": args.threshold,
        "metrics": metrics,
        "train_rows": int(len(X_train)),
        "valid_rows": int(len(X_valid)),
        "train_date_min": str(pd.Timestamp(train_dates.min()).date()),
        "train_date_max": str(pd.Timestamp(train_dates.max()).date()),
        "valid_date_min": str(pd.Timestamp(valid_dates.min()).date()),
        "valid_date_max": str(pd.Timestamp(valid_dates.max()).date()),
    }
    (model_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    del X_train
    del X_valid
    del y_train
    del y_valid
    gc.collect()

    log("构建推理特征矩阵并生成分数...")
    X_inference = build_feature_frame(inference_df, feature_cols, categorical_cols, category_mappings)
    del category_mappings
    gc.collect()

    inference_scored = inference_df.copy()
    inference_scored["score"] = model.predict_proba(X_inference)[:, 1]
    inference_scored = inference_scored.sort_values("score", ascending=False).reset_index(drop=True)
    inference_scored.to_parquet(model_dir / "inference_scores_latest.parquet", index=False)

    print("训练完成。")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"模型目录: {model_dir}")
    print(inference_scored[["date", "code", "name", "industry", "score"]].head(args.top_k).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
