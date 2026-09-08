"""Bounded FINRA position snapshots; publication-aware, offline-replayable research."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

VERSION = "finra_short_interest_v2_zero_volume"
SCHEDULE_URL = "https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest"
FILE_BASE = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt"
MAX_BYTES = 16 * 1024 * 1024
LIMITATIONS = [
    "Short interest is a twice-monthly position observation with publication lag; dates are settlement dates, not daily readings.",
    "Publication cutoff uses the official schedule, at end of publication day; no intraday availability claim.",
    "Fixed latest MTUM constituents and weights introduce look-ahead selection bias; they are not actual historical holdings.",
    "Weighted days to cover is a descriptive equity-weighted mean, not portfolio liquidation time. Any positive-weight holding with a missing position or unusable days to cover suppresses the mean.",
    "FINRA's published days to cover is preserved separately, including its minimum 1.00 convention. Zero average daily volume makes usable days to cover unavailable, including published 999.99 sentinels; no ratio is recomputed.",
    "Float denominators are unavailable: no short-float percentages. Short shares are not summed across different stocks.",
    "Splits and corporate actions can change share-count comparability; flags are retained. Constituent raw-share changes are not inferred.",
    "Short positions and days to cover do not prove long-side crowding or forced unwinding.",
    "Archives retrieved now can include subsequent revisions; this is publication-aware retrospective research, not an authenticated point-in-time vintage.",
    "Hashes detect inconsistent snapshots, not malicious replacement of every file and its hash. Public download does not imply unrestricted redistribution rights.",
]

# A separate interpreter is killed by subprocess.run on timeout, including a stalled read.
# The worker caps output and restricts redirects; exception messages never enter evidence.
_WORKER = r'''
import sys, urllib.request
class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        u = urlsplit(newurl)
        if u.scheme != "https" or u.hostname not in {"www.finra.org", "cdn.finra.org"} or u.username or u.password:
            raise ValueError("unsupported redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)
req = urllib.request.Request(sys.argv[1], headers={"User-Agent": "momentum-research-agent/0.1", "Accept-Encoding": "identity"})
with urllib.request.build_opener(Redirect()).open(req, timeout=float(sys.argv[2])) as response:
    body = response.read(int(sys.argv[3]) + 1)
    if len(body) > int(sys.argv[3]):
        raise ValueError("body too large")
    sys.stdout.buffer.write(body)
'''


def _attempt(url: str, timeout: float) -> bytes:
    if url != SCHEDULE_URL and not re.fullmatch(re.escape(FILE_BASE) + r"\d{8}\.csv", url):
        raise ValueError("Unsupported source URL")
    response = subprocess.run([sys.executable, "-c", _WORKER, url, str(timeout), str(MAX_BYTES)],
                              capture_output=True, timeout=min(timeout, 20), check=True)
    if not response.stdout or len(response.stdout) > MAX_BYTES:
        raise ValueError("Empty or oversized source")
    return response.stdout


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _write(root: Path, name: str, body: bytes) -> str:
    with (root / name).open("xb") as stream:
        stream.write(body)
    return _digest(body)


def _read(root: Path, name: str, digest: str | None = None) -> bytes:
    path = root / name
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsupported evidence path")
    if any((root / p).is_symlink() for p in [relative, *relative.parents]):
        raise ValueError("Symlink evidence is unsupported")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Oversized evidence")
    raw = path.read_bytes()
    if digest is not None and _digest(raw) != digest:
        raise ValueError("Evidence hash mismatch")
    return raw


def _date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected exact ISO date")
    return date.fromisoformat(value)


def _plain(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def parse_schedule(raw: bytes) -> list[dict]:
    """Read official year headings and settlement/publication table columns."""
    text = raw.decode("utf-8-sig")
    year, entries = None, {}
    for token in re.findall(r"<h[1-6]\b[^>]*>.*?</h[1-6]>|<table\b[^>]*>.*?</table>", text, re.I | re.S):
        if not token.lower().startswith("<table"):
            match = re.fullmatch(r"(20\d{2})\s+Short Interest Reporting Dates", _plain(token))
            year = int(match[1]) if match else None
            continue
        if year is None:
            continue
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", token, re.I | re.S)
        if not rows:
            raise ValueError("Empty reporting table")
        headers = [_plain(c) for c in re.findall(r"<th\b[^>]*>(.*?)</th>", rows[0], re.I | re.S)]
        if len(headers) != 3 or headers[0] != "Settlement Date" or headers[2] != "Publication Date":
            raise ValueError("Unexpected reporting table headers")
        for row in rows[1:]:
            cells = [_plain(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.I | re.S)]
            if len(cells) != 3:
                raise ValueError("Malformed reporting row")
            dates = []
            for cell in (cells[0], cells[2]):
                match = re.match(r"([A-Za-z]+)\s+(\d{1,2})\b", cell)
                if not match:
                    raise ValueError("Malformed reporting date")
                dates.append(datetime.strptime(f"{match[1]} {match[2]} {year}", "%B %d %Y").date())
            settlement, publication = dates
            if settlement.month == 12 and publication.month == 1:
                publication = publication.replace(year=year + 1)
            if not 0 < (publication - settlement).days <= 40 or str(settlement) in entries:
                raise ValueError("Ambiguous reporting schedule")
            entries[str(settlement)] = str(publication)
    if not entries:
        raise ValueError("No official reporting schedule found")
    return [{"settlement_date": s, "publication_date": p} for s, p in sorted(entries.items())]


def _holdings(rows: list[dict]) -> list[dict]:
    result, seen = [], set()
    for row in rows:
        symbol, weight = row["ticker"], float(row["weight"])
        if (not re.fullmatch(r"[A-Z]{1,6}(?:[-.][A-Z])?", symbol) or symbol in seen
                or symbol in {"MTUM", "SPY"} or not math.isfinite(weight) or weight < 0
                or row["currency"] != "USD"
                or row["exchange"] not in {"NASDAQ", "NYSE", "Cboe BZX", "NYSE Arca"}):
            raise ValueError("Invalid or ambiguous holdings")
        seen.add(symbol)
        result.append({k: row[k] for k in ("ticker", "exchange", "currency", "name")} | {"weight": weight})
    if sum(r["weight"] for r in result) > 1.02:
        raise ValueError("Equity weights exceed rounding tolerance")
    return result


def parse_records(raw: bytes, settlement: date, symbols: list[str]) -> tuple[dict, list[str]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="|")
    required = {"accountingYearMonthNumber", "symbolCode", "settlementDate", "currentShortPositionQuantity",
                "averageDailyVolumeQuantity", "daysToCoverQuantity", "stockSplitFlag", "revisionFlag"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames) or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("Unexpected short interest columns")
    records, seen, invalid = {}, set(), set()
    for row in reader:
        symbol = row["symbolCode"]
        if symbol not in symbols:
            continue
        if symbol in seen:
            invalid.add(symbol)
            continue
        seen.add(symbol)
        try:
            if (None in row or _date(row["settlementDate"]) != settlement
                    or row["accountingYearMonthNumber"] != settlement.strftime("%Y%m%d")):
                raise ValueError("Settlement mismatch")
            integers = [row[key] for key in ("currentShortPositionQuantity", "averageDailyVolumeQuantity")]
            if not all(isinstance(n, str) and re.fullmatch(r"\d{1,18}", n) for n in integers):
                raise ValueError("Invalid position or volume")
            dtc = float(row["daysToCoverQuantity"])
            if not math.isfinite(dtc) or dtc < 0:
                raise ValueError("Invalid days to cover")
            flags = [row[key] for key in ("stockSplitFlag", "revisionFlag")]
            if not all(isinstance(f, str) and re.fullmatch(r"[A-Za-z0-9 ]{0,20}", f) for f in flags):
                raise ValueError("Invalid record flags")
            records[symbol] = dict(short_shares=int(integers[0]), average_daily_volume=int(integers[1]),
                                   days_to_cover=dtc if int(integers[1]) > 0 else None,
                                   published_days_to_cover=dtc, split_flag=flags[0], revision_flag=flags[1])
        except (ValueError, TypeError):
            invalid.add(symbol)
    for symbol in invalid:
        records.pop(symbol, None)
    return records, sorted(set(symbols) - records.keys())


def _select(schedule: list[dict], target: date, reference: date | None) -> dict:
    published = [r for r in schedule if _date(r["publication_date"]) <= target]
    return {"latest": published[-1] if published else None,
            "previous": published[-2] if len(published) > 1 else None,
            "reference": next((r for r in published if r["settlement_date"] == str(reference)), None)}


def _fetch(root: Path, key: str, url: str, name: str, deadline: float) -> dict:
    entry = {"url": url, "file": name, "sha256": None, "attempts": []}
    for _ in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            entry["error"] = "overall_deadline"
            break
        attempt = {"fetched_at": datetime.now(timezone.utc).isoformat()}
        entry["attempts"].append(attempt)
        try:
            raw = _attempt(url, min(20, remaining))
            if not raw or len(raw) > MAX_BYTES:
                raise ValueError("Invalid response size")
            entry["sha256"] = _write(root, name, raw)
            attempt["status"] = "downloaded"
            entry.pop("error", None)
            return entry
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            attempt["status"] = type(exc).__name__
            entry["error"] = type(exc).__name__
    return entry


def _derive(root: Path, manifest: dict) -> tuple[dict, dict]:
    if manifest["version"] != VERSION:
        raise ValueError("Unsupported calculation version")
    target = _date(manifest["target_date"])
    reference = _date(manifest["reference_date"]) if manifest["reference_date"] else None
    holdings = _holdings(manifest["holdings"])
    symbols = sorted({"MTUM", "SPY", *(r["ticker"] for r in holdings)})
    sources = manifest["sources"]
    schedule_entry = sources["schedule"]
    if schedule_entry["url"] != SCHEDULE_URL or schedule_entry["file"] != "raw/schedule.html":
        raise ValueError("Unexpected schedule identity")
    schedule, diagnostics = [], []
    if schedule_entry["sha256"]:
        raw = _read(root, "raw/schedule.html", schedule_entry["sha256"])
        try:
            schedule = parse_schedule(raw)
        except (ValueError, UnicodeError):
            diagnostics.append("Official schedule could not be parsed")
    else:
        diagnostics.append("Official schedule unavailable")
    selected = _select(schedule, target, reference)
    needed = {r["settlement_date"] for r in selected.values() if r}
    if set(sources) != {"schedule", *needed}:
        raise ValueError("Unexpected settlement sources")
    periods = {}
    for label, period in selected.items():
        if period is None:
            periods[label] = None
            if label != "reference" or reference:
                diagnostics.append(f"{label}: no exact published schedule entry")
            continue
        day = period["settlement_date"]
        filename = "raw/" + day.replace("-", "") + ".csv"
        entry = sources[day]
        if entry["file"] != filename or entry["url"] != FILE_BASE + day.replace("-", "") + ".csv":
            raise ValueError("Unexpected settlement source identity")
        records, missing = {}, symbols
        if entry["sha256"]:
            raw = _read(root, filename, entry["sha256"])
            try:
                records, missing = parse_records(raw, _date(day), symbols)
            except (ValueError, UnicodeError, csv.Error):
                diagnostics.append(f"{label}: malformed source records")
        else:
            diagnostics.append(f"{label}: download unavailable")
        unusable_dtc = sorted(symbol for symbol, record in records.items() if record["days_to_cover"] is None)
        if unusable_dtc:
            diagnostics.append(f"{label}: days to cover unavailable with zero average daily volume: {', '.join(unusable_dtc)}")
        periods[label] = {**period, "records": records, "missing": missing}
    positive = [r for r in holdings if r["weight"] > 0]
    total = sum(r["weight"] for r in positive)
    latest = periods["latest"]
    covered = [r for r in positive if latest and r["ticker"] in latest["records"]]
    means = {}
    for label, period in periods.items():
        means[label] = (sum(r["weight"] * period["records"][r["ticker"]]["days_to_cover"] for r in positive) / total
                        if total and period and all(period["records"].get(r["ticker"], {}).get("days_to_cover") is not None
                                                    for r in positive) else None)
    complete = all(p and not p["missing"] and all(r["days_to_cover"] is not None for r in p["records"].values())
                   for label, p in periods.items() if label != "reference" or reference)
    result = dict(version=VERSION, status="complete" if complete else "partial", target_date=str(target),
                  reference_date=str(reference) if reference else None,
                  latest_settlement=latest["settlement_date"] if latest else None,
                  latest_publication=latest["publication_date"] if latest else None, periods=periods,
                  basket=dict(required_count=len(positive), covered_count=len(covered), total_weight=total,
                              covered_weight=sum(r["weight"] for r in covered), weighted_days_to_cover=means),
                  diagnostics=diagnostics, limitations=LIMITATIONS)
    if not latest or not latest["records"]:
        result["status"] = "unavailable"
    return result, {"schedule": schedule, "periods": periods}


def build(root: Path, target: date, reference: date | None, holdings: list[dict]) -> dict:
    """Create a new immutable snapshot directory; never replace an existing run."""
    target = _date(str(target))
    reference = _date(str(reference)) if reference else None
    holdings = _holdings(holdings)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    deadline = time.monotonic() + 120
    sources = {"schedule": _fetch(root, "schedule", SCHEDULE_URL, "raw/schedule.html", deadline)}
    schedule = []
    if sources["schedule"]["sha256"]:
        try:
            schedule = parse_schedule(_read(root, "raw/schedule.html", sources["schedule"]["sha256"]))
        except (ValueError, UnicodeError):
            pass
    for day in sorted({p["settlement_date"] for p in _select(schedule, target, reference).values() if p}):
        stamp = day.replace("-", "")
        sources[day] = _fetch(root, day, FILE_BASE + stamp + ".csv", "raw/" + stamp + ".csv", deadline)
    manifest = dict(version=VERSION, target_date=str(target), reference_date=str(reference) if reference else None,
                    holdings=holdings, sources=sources)
    result, normalized = _derive(root, manifest)
    manifest["normalized_sha256"] = _write(root, "normalized.json", _json(normalized))
    result["manifest_sha256"] = _write(root, "manifest.json", _json(manifest))
    _write(root, "short_interest.json", _json(result))
    return result


def replay(root: Path) -> dict:
    """Verify pinned bytes and regenerate metrics without performing network requests."""
    root = Path(root)
    try:
        saved = json.loads(_read(root, "short_interest.json"))
        if not isinstance(saved["manifest_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", saved["manifest_sha256"]):
            raise ValueError("Missing manifest hash")
        manifest_bytes = _read(root, "manifest.json", saved["manifest_sha256"])
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest["normalized_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["normalized_sha256"]):
            raise ValueError("Missing normalization hash")
        result, normalized = _derive(root, manifest)
        if _read(root, "normalized.json", manifest["normalized_sha256"]) != _json(normalized):
            raise ValueError("Normalization cannot be reproduced")
        result["manifest_sha256"] = _digest(manifest_bytes)
        return result
    except (KeyError, TypeError, OSError) as exc:
        raise ValueError("Invalid short interest snapshot structure") from exc
