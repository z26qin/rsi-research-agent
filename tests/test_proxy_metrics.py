from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from momentum_research_agent import proxy_metrics as pm


@pytest.mark.parametrize("now,want", [
    ("2026-09-08T12:00:00+00:00", "2026-09-04"),
    ("2026-09-06T12:00:00+00:00", "2026-09-04"),
    ("2026-09-08T23:00:00+00:00", "2026-09-04"),
    ("2026-11-28T12:00:00+00:00", "2026-11-27"),
    ("2026-03-09T12:00:00+00:00", "2026-03-06"),
])
def test_default_target_is_previous_ny_session(now, want):
    assert pm.target_date(None, datetime.fromisoformat(now)) == date.fromisoformat(want)


def test_explicit_date_rejects_holiday_and_unclosed_session():
    now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    for day in [date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 9)]:
        with pytest.raises(ValueError):
            pm.target_date(day, now)


def panel():
    dates = pm.sessions(date(2024, 1, 1), date(2026, 9, 4))
    return pd.DataFrame({"Date": dates, "Close": 200.0,
                         "Adj Close": 100 * 1.001 ** np.arange(len(dates)),
                         "Volume": 1000, "Dividends": 0.0, "Stock Splits": 0.0})


def test_formulas_use_adjusted_price_and_sample_volatility():
    data = pm.normalize_prices(panel(), date(2026, 9, 4))
    metrics = pm.calculate({"MTUM": data, "SPY": data}, date(2026, 9, 4))
    assert metrics["MTUM.return_5d"] == pytest.approx(1.001 ** 5 - 1)
    assert metrics["MTUM.drawdown_252d"] == 0
    assert metrics["MTUM.volatility_21d"] == pytest.approx(0, abs=1e-12)
    assert metrics["relative.return_21d"] == 0
    changed = data.copy()
    changed.loc[changed.index[-1], "adj_close"] *= .9
    result = pm.calculate({"MTUM": changed, "SPY": data}, date(2026, 9, 4))
    expected = np.std([.001] * 20 + [-.0991], ddof=1) * np.sqrt(252)
    assert result["MTUM.volatility_21d"] == pytest.approx(expected)
    assert result["MTUM.drawdown_252d"] == pytest.approx(-.0991)
    assert result["relative.return_5d"] == pytest.approx(-.1)


def test_gap_only_invalidates_affected_windows():
    frame = pm.normalize_prices(panel(), date(2026, 9, 4))
    frame = frame.drop(frame.index[-10])
    result = pm.calculate({"MTUM": frame, "SPY": frame}, date(2026, 9, 4))
    assert result["MTUM.return_5d"] is not None
    assert result["MTUM.return_21d"] is None
    assert result["MTUM.drawdown_252d"] is None
    assert result["MTUM.volatility_21d"] is None


@pytest.mark.parametrize("problem", ["missing_adj", "duplicate", "zero", "infinity", "old"])
def test_invalid_core_is_rejected(problem):
    frame = panel()
    if problem == "missing_adj": frame = frame.drop(columns="Adj Close")
    if problem == "duplicate": frame = pd.concat([frame, frame.tail(1)])
    if problem == "zero": frame.loc[frame.index[-1], "Adj Close"] = 0
    if problem == "infinity": frame.loc[frame.index[-1], "Adj Close"] = np.inf
    if problem == "old": frame = frame.iloc[:-1]
    with pytest.raises(ValueError):
        pm.normalize_prices(frame, date(2026, 9, 4))


def test_future_rows_are_excluded():
    frame = panel()
    normalized = pm.normalize_prices(frame, date(2026, 9, 3))
    assert normalized.date.max() == pd.Timestamp("2026-09-03")
