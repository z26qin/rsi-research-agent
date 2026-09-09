"""Date-safe ETF proxy calculations. No engine scores or model calls."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd

CALCULATION_VERSION = "etf_proxy_metrics_v1"
SYMBOLS = ("MTUM", "SPY")
WINDOWS = (1, 5, 21, 63)


def sessions(start: date, end: date) -> pd.DatetimeIndex:
    calendar = xcals.get_calendar("XNYS", start=start - timedelta(days=14), end=end + timedelta(days=14))
    return calendar.sessions_in_range(str(start), str(end)).tz_localize(None)


def target_date(requested: date | None, now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    day = requested or today - timedelta(days=1)
    calendar = xcals.get_calendar("XNYS", start=day - timedelta(days=14), end=day + timedelta(days=14))
    if requested is None:
        return calendar.date_to_session(str(day), direction="previous").date()
    if not calendar.is_session(str(day)) or calendar.session_close(str(day)).to_pydatetime() > now:
        raise ValueError("Requested date is not a completed XNYS trading session")
    return day


def normalize_prices(raw: pd.DataFrame, as_of: date) -> pd.DataFrame:
    required = {"Date", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"}
    if not required.issubset(raw.columns):
        raise ValueError("Missing required vendor price/action columns")
    frame = raw.copy()
    dates = pd.to_datetime(frame["Date"], errors="raise")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert("America/New_York").dt.tz_localize(None)
    frame["Date"] = dates.dt.normalize()
    frame = frame.loc[frame.Date <= pd.Timestamp(as_of)].sort_values("Date")
    if frame.empty or frame.Date.isna().any() or frame.Date.duplicated().any():
        raise ValueError("Empty or duplicate vendor dates")
    if frame.Date.iloc[-1] != pd.Timestamp(as_of):
        raise ValueError("Required ETF has no target-session observation")
    for column in ("Close", "Adj Close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not (np.isfinite(frame[column]) & (frame[column] > 0)).all():
            raise ValueError("Invalid price; no unadjusted fallback permitted")
    allowed = sessions(frame.Date.iloc[0].date(), as_of)
    if not frame.Date.isin(allowed).all():
        raise ValueError("Vendor contains non-session observations")
    return frame[list(sorted(required))].rename(columns={
        "Date": "date", "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
        "Dividends": "dividends", "Stock Splits": "stock_splits",
    }).reset_index(drop=True)


def calculate(panels: dict[str, pd.DataFrame], as_of: date) -> dict[str, float | None]:
    dates = sessions(as_of - timedelta(days=550), as_of)
    metrics = {}
    for symbol in SYMBOLS:
        prices = panels[symbol].set_index("date")["adj_close"].reindex(dates)
        for window in WINDOWS:
            sample = prices.iloc[-window - 1:]
            metrics[f"{symbol}.return_{window}d"] = (
                float(sample.iloc[-1] / sample.iloc[0] - 1)
                if len(sample) == window + 1 and sample.notna().all() else None)
        sample = prices.iloc[-252:]
        metrics[f"{symbol}.drawdown_252d"] = (
            float(sample.iloc[-1] / sample.max() - 1)
            if len(sample) == 252 and sample.notna().all() else None)
        sample = prices.iloc[-22:]
        metrics[f"{symbol}.volatility_21d"] = (
            float(sample.pct_change(fill_method=None).iloc[1:].std(ddof=1) * np.sqrt(252))
            if len(sample) == 22 and sample.notna().all() else None)
    for window in WINDOWS:
        left, right = (metrics[f"{symbol}.return_{window}d"] for symbol in SYMBOLS)
        metrics[f"relative.return_{window}d"] = ((1 + left) / (1 + right) - 1
                                                if left is not None and right is not None else None)
    return metrics
