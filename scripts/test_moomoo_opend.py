#!/usr/bin/env python3
"""Minimal moomoo OpenD connectivity and paper-trading capability check."""

from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test moomoo OpenD connectivity.")
    parser.add_argument("--host", default="127.0.0.1", help="OpenD host.")
    parser.add_argument("--port", type=int, default=11111, help="OpenD port.")
    parser.add_argument("--market", default="CN", choices=["CN", "HK", "US"], help="Trading market to inspect.")
    parser.add_argument("--quote-symbol", default="SH.600000", help="Symbol for a quote sanity check.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        from moomoo import (
            OpenQuoteContext,
            OpenSecTradeContext,
            RET_OK,
            SecurityFirm,
            TrdEnv,
            TrdMarket,
        )
    except ImportError as exc:
        print("moomoo-api is not installed. Run: python -m pip install moomoo-api", file=sys.stderr)
        raise SystemExit(2) from exc

    market_map = {
        "CN": TrdMarket.CN,
        "HK": TrdMarket.HK,
        "US": TrdMarket.US,
    }

    print(f"Connecting to OpenD at {args.host}:{args.port} ...")
    quote_ctx = OpenQuoteContext(host=args.host, port=args.port)
    trade_ctx = OpenSecTradeContext(
        filter_trdmarket=market_map[args.market],
        host=args.host,
        port=args.port,
        security_firm=SecurityFirm.FUTUSECURITIES,
    )
    try:
        ret, data = quote_ctx.get_global_state()
        print("\n[quote] global state")
        print("ret:", ret)
        print(data)

        ret, data = quote_ctx.get_market_snapshot([args.quote_symbol])
        print(f"\n[quote] snapshot {args.quote_symbol}")
        print("ret:", ret)
        if ret == RET_OK:
            print(data.head(5).to_string(index=False))
        else:
            print(data)

        ret, data = trade_ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)
        print(f"\n[trade] simulate account info market={args.market}")
        print("ret:", ret)
        if ret == RET_OK:
            print(data.to_string(index=False))
        else:
            print(data)

        ret, data = trade_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
        print(f"\n[trade] simulate positions market={args.market}")
        print("ret:", ret)
        if ret == RET_OK:
            print(data.head(20).to_string(index=False))
        else:
            print(data)
    finally:
        quote_ctx.close()
        trade_ctx.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
