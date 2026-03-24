FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY download_data.py .
COPY feature_engineering.py .
COPY build_inference_features.py .
COPY train_lightgbm.py .
COPY backtest_walk_forward.py .
COPY batch_download_all_a.py .
COPY paper_trade_futu.py .
COPY paper_trade_daemon.py .

ENTRYPOINT ["python", "download_data.py"]
