"""Fetch price/volume history via yfinance."""

from __future__ import annotations

import asyncio
import json
import re

from momentum_research_agent.tools.registry import get_tool_context
from momentum_research_agent.tools.performance import calculate, archive

from momentum_research_agent.tools.registry import register_tool


def _download(ticker: str, period: str, interval: str):
    import yfinance as yf

    return yf.download(
        ticker,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=True,
    )


def _to_markdown(frame) -> str:
    if frame is None or frame.empty:
        return "No price data returned."

    if getattr(frame.columns, "nlevels", 1) > 1:
        frame = frame.copy()
        frame.columns = [
            col[0] if isinstance(col, tuple) else col for col in frame.columns
        ]

    close_col = "Close" if "Close" in frame.columns else frame.columns[0]
    work = frame[[close_col]].copy()
    if "Volume" in frame.columns:
        work["Volume"] = frame["Volume"]
    work["Return"] = work[close_col].pct_change()
    tail = work.tail(20).reset_index()
    date_col = tail.columns[0]
    tail[date_col] = tail[date_col].astype(str)
    tail[close_col] = tail[close_col].map(lambda value: f"{float(value):.2f}")
    tail["Return"] = tail["Return"].map(
        lambda value: "" if value != value else f"{float(value):.2%}"
    )
    if "Volume" in tail.columns:
        tail["Volume"] = tail["Volume"].map(
            lambda value: "" if value != value else f"{int(value):,}"
        )
    return tail.to_markdown(index=False)


@register_tool(
    name="market_data",
    description=(
        "Fetch adjusted prices. For daily data, returns archived deterministic return, "
        "annualized sample volatility and maximum drawdown over 20 common prices. "
        "Use benchmark to compare two tickers in ONE call (e.g. ticker MTUM, benchmark SPY). "
        "Other intervals return the legacy recent-price table."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Ticker symbol, e.g. NVDA."},
            "benchmark": {
                "type": "string",
                "description": "Optional comparison ticker; daily interval only.",
            },
            "period": {
                "type": "string",
                "description": "yfinance period string. Default: 3mo.",
            },
            "interval": {
                "type": "string",
                "description": "yfinance interval string. Default: 1d.",
            },
        },
        "required": ["ticker"],
    },
)
async def market_data(
    ticker: str, period: str = "3mo", interval: str = "1d", benchmark: str | None = None
) -> str:
    symbols = list(dict.fromkeys(s.upper() for s in (ticker, benchmark) if s))
    if not symbols or any(
        not re.fullmatch(r"[A-Z^][A-Z0-9.^-]{0,14}", s) for s in symbols
    ):
        return json.dumps({"status": "unavailable", "reason": "Invalid ticker"})
    if benchmark and interval != "1d":
        return json.dumps(
            {"status": "unavailable", "reason": "Comparison requires daily interval"}
        )
    try:
        frames = {}
        for symbol in symbols:
            frames[symbol] = await asyncio.to_thread(
                _download, symbol, period, interval
            )
        if interval != "1d":
            return (
                f"# {ticker.upper()} period={period} interval={interval}\n\n"
                + _to_markdown(frames[symbols[0]])
            )
        ctx = get_tool_context()
        if not ctx.session_dir:
            return json.dumps(
                {
                    "status": "unavailable",
                    "reason": "Session required for evidence retention",
                }
            )
        return json.dumps(archive(calculate(frames), ctx.session_dir), allow_nan=False)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return json.dumps(
            {
                "status": "unavailable",
                "reason": f"Price calculation unavailable ({type(exc).__name__}); missing or invalid data are not zero.",
            }
        )
