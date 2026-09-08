# Retrospective MTUM fixed-basket comparison

This answers: **How would a portfolio initialized with a later MTUM equity basket
have behaved from an earlier starting close?** It does not recover May 29 MTUM
holdings, measure historical investor crowding, or provide a point-in-time
backtest. The later choice of constituents **and weights** introduces look-ahead
bias. The report keeps this warning visible even when all prices are available.

## Run

From the repository root, using a previously saved, validated ETF crowding brief:

```bash
uv run momentum-research-agent --simulate-basket \
  --basket-brief reports/etf-crowding-reviewed-20260908/brief.json \
  --start-date 2026-05-29 \
  --session-dir reports/fixed-basket-may29
```

Those example report files are local research artifacts, not checked into Git.
If needed, first save a new allocation snapshot with
`--daily-brief --brief-source etf-proxy --with-crowding`.

The end date defaults to the supplied holdings snapshot's actual date, **not
today**. Optional `--as-of YYYY-MM-DD` extends the same frozen basket to a later
completed trading session. Required ordering is
`start date < holdings observation date <= end date`; endpoints must be completed
XNYS sessions. No historical issuer endpoint is called by the simulation.

It downloads daily constituent prices plus MTUM and SPY using the existing
yfinance dependency. No API key, LLM, engine run or policy changes are required.
The existing exact-date backfill and daily-brief modes retain their semantics.

## Portfolio definition

- Start with $1 of hypothetical wealth at the starting close. Apply the issuer's
  reported positive equity weights without renormalization. Fractional positions
  are allowed. Any residual below 100% is zero-interest cash, **not** a replication
  of the issuer's cash, derivatives or other non-equity assets. Weights above
  100% are rejected rather than creating implicit leverage.
- Use fixed positions between endpoints, no rebalancing. Individual positions
  and portfolio weights drift with prices.
- Use Yahoo's split-adjusted `Close` and same-basis `Dividends`. Units are expressed
  on that split-adjusted basis, so multiplying them by split ratios again would
  double-count splits. Retain and display split events. This relies on the
  vendor's corporate-action adjustment being correct.
- Dividends after the starting close accumulate as cash/receivables on the
  **ex-date**, not the payment date. There is no dividend reinvestment, cash
  interest, tax, trading cost or execution model. Starting-date dividends are
  excluded because the hypothetical purchase happens at that day's close.
- `Adj Close` is retained and validated but deliberately not used for basket
  valuation: dividend-reinvested returns would not match this cash convention.
  SPY and actual MTUM market-price benchmarks use the **same** cash-dividend
  calculation. These are not their conventional dividend-reinvested returns.

For symbol `i`, starting weight `w_i`, split-adjusted close `C_i(t)` and
split-adjusted dividend `D_i(t)`:

```text
units_i = w_i / C_i(start)
equity_i(t) = units_i * C_i(t)
cash(t) = 1 - sum(w_i) + sum_i units_i * sum_{start < s <= t} D_i(s)
wealth(t) = cash(t) + sum_i equity_i(t)
weight_i(t) = equity_i(t) / wealth(t)
```

Reported metrics:

- Interval return: `wealth(end) / wealth(start) - 1`.
- Relative wealth change: `(1 + basket_return) / (1 + benchmark_return) - 1`,
  not a percentage-point subtraction.
- Maximum drawdown: minimum daily `wealth / running_max(wealth) - 1` within the
  simulation interval. This is **not** the daily brief's 252-close drawdown.
- Volatility: sample standard deviation of daily wealth returns times
  `sqrt(252)` over this interval; unavailable with fewer than two returns.
- Start/end equity top-10 weight, HHI and frozen-classification sector weights,
  all divided by total wealth including cash. These are simulated price-driven
  concentration measures, not historical issuer observations or investor flows.

For context on the download options and adjusted prices, see the
[yfinance download documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
and [Yahoo adjusted-close explanation](https://help.yahoo.com/kb/SLN28256.html).

## Data limits and failure behavior

Every positive-weight holding needs all expected trading sessions between the
endpoints, finite positive Close and Adj Close, and valid nonnegative dividend
and split fields. Duplicate dates, gaps, missing tickers or invalid actions
withhold **the entire basket**, with coverage and missing-symbol reasons. There
is no forward fill, dropped-stock renormalization or replacement security.
Missing benchmarks only withhold their own comparisons.

Ticker matching is literal for supported US USD listings. There is no fuzzy
aliasing or historical security master. Mergers, spin-offs, symbol changes and
unsupported distribution types may require a separately validated adapter.
Current-sector classifications are not reconstructed historically.

Calculation version `fixed_basket_cash_dividends_v2` automatically accepts only
integer forward and reciprocal-integer reverse splits (numerical tolerance
`1e-8` on the integer). Other ratios withhold that security and the full basket
pending corporate-action review. This is intentionally conservative: even a
genuine 3-for-2 split needs review. It is **not** comprehensive spin-off detection.

During the September 8 live acceptance run, all 125 constituent price histories
were downloaded, but FDX carried a Yahoo split ratio of `1.241` on June 1.
[FedEx confirms this was its Freight spin-off](https://investor.fedex.com/news-and-events/investor-news/investor-news-details/2026/FedEx-Completes-Spin-Off-of-FedEx-Freight/default.aspx),
not a simple change in share count. Accordingly, the May 29 basket result is
withheld under v2 until the distributed security and price basis are modeled.
The preliminary v1 result is superseded and must not be used as a valid
fixed-position return. Moving the starting date or excluding/reweighting FDX
would change the user's experiment and is not done automatically.

Two download batches at most, eight download threads, 20-second library request
timeouts, a killable 55-second subprocess per batch and a 120-second overall
collection budget. Local validation/serialization is additional. Retries do not
splice data vintages together: retain the best single returned batch by complete
equity allocation coverage, then complete symbol count. Failed response files
and exception types are retained when available.

Exit 0 means the basket was calculated with research limitations (`partial`).
Exit 2 means unavailable basket data or invalid invocation. No output directory
is reused or overwritten. Partial benchmark results are not a complete basket.

## Evidence and offline replay

Each run retains `simulation.md`, `simulation.json`, a hash manifest, the copied
issuer evidence in `reference/crowding/`, selected vendor-returned prices in
`prices.parquet`, normalized prices in `normalized.parquet`, and download
request/attempt diagnostics. The saved vendor table is reshaped to long form,
not described as a raw HTTP response. A `Capital Gains Present` marker preserves
whether that optional field existed for each ticker before concatenation. Its
absence for equities is not mistaken for an invalid ETF distribution; supplied
nonzero or malformed distributions remain unsupported.

Replay checks manifest/file hashes, re-normalizes both holdings and prices and
recomputes results, rather than trusting editable report metrics. It works even
if the original brief directory or imported price file is subsequently moved.

```bash
uv run python -c 'import json,sys; from pathlib import Path; from momentum_research_agent.fixed_basket import replay; print(json.dumps(replay(Path(sys.argv[1])), indent=2))' reports/fixed-basket-may29
```

To run offline into a **new** directory, pass
`--basket-prices /absolute/path/to/prices.parquet`. The table requires `Ticker`,
`Date`, `Close`, `Adj Close`, `Volume`, `Dividends`, and `Stock Splits` columns in
the yfinance convention above. Imported tables are labeled user-supplied, not
independently authenticated; hashes provide integrity, not source authenticity.

## Future monthly portfolios

Monthly construction/rebalancing is deliberately not implemented here. The next
extension should store each allocation's decision/publication time and effective
trading time, then apply it only prospectively. Do not use this retrospective
command to claim a monthly point-in-time strategy test. Keeping allocation
snapshots and price evidence separate prepares that extension without a new
database or scheduling framework.
