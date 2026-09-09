"""One download attempt in a disposable subprocess; not a public CLI."""
import io
from pathlib import Path
import sys
import urllib.request

import pandas as pd


def fetch(source: str, start: str, end: str) -> pd.DataFrame:
    if source == "VIXCLS":
        request = urllib.request.Request("https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
                                         headers={"User-Agent": "momentum-research-agent/0.1 personal-research"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return pd.read_csv(io.BytesIO(response.read()))
    if source not in {"MTUM", "SPY"}:
        raise ValueError("Unsupported proxy source")
    import yfinance as yf
    return yf.Ticker(source).history(start=start, end=end, interval="1d", auto_adjust=False,
                                     actions=True, timeout=20, raise_errors=True).reset_index()


def main() -> None:
    source, start, end, destination = sys.argv[1:]
    frame = fetch(source, start, end)
    if frame.empty:
        raise ValueError("Empty vendor response")
    frame.to_parquet(Path(destination), index=False)


if __name__ == "__main__":
    main()
