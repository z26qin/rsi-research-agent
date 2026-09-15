from datetime import date

import numpy as np
import pandas as pd
import pytest

from momentum_research_agent import proxy_data
from momentum_research_agent.proxy_metrics import sessions


@pytest.fixture
def provider(monkeypatch):
    dates = sessions(date(2024, 1, 1), date(2026, 9, 4))
    panels = {
        symbol: pd.DataFrame(
            {
                "Date": dates,
                "Close": 200.0,
                "Adj Close": 100 * 1.001 ** np.arange(len(dates)),
                "Volume": 1000,
                "Dividends": 0.0,
                "Stock Splits": 0.0,
            }
        )
        for symbol in ("MTUM", "SPY")
    }

    def worker(source, start, end, destination, **kwargs):
        frame = (
            panels[source]
            if source != "VIXCLS"
            else pd.DataFrame({"observation_date": ["2026-09-03"], "VIXCLS": [20.0]})
        )
        frame.to_parquet(destination, index=False)

    monkeypatch.setattr(proxy_data, "run_worker", worker)
    return panels
