"""Exact-date issuer backfill and hash-checked retrospective holdings comparison."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from momentum_research_agent import crowding_data as cd
from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.crowding_metrics import PRODUCTS, VERSION
from momentum_research_agent.proxy_data import save_json
from momentum_research_agent.proxy_metrics import target_date

SCHEMA = "etf_crowding_backfill_v1"
TOTAL_TIMEOUT = 120.
NO_COMPARISON = {"status": "unavailable", "reason": "No validated newer issuer reference available; comparison withheld."}


def historical_url(symbol: str, target: date) -> str:
    return (cd.product_url(symbol) + "/1467271812596.ajax?fileType=csv&fileName="
            + symbol + "_holdings&dataType=fund&asOfDate=" + target.strftime("%Y%m%d"))


def fetch(symbol: str, target: date) -> dict:
    url = historical_url(symbol, target)
    request = urllib.request.Request(url, headers={"User-Agent": "momentum-research-agent/0.1 personal-research"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(8_000_001)
        if len(body) > 8_000_000:
            raise ValueError("Issuer response too large")
        return {"holdings_csv": body.decode("utf-8-sig"), "requested_url": url,
                "http_status": response.status, "content_type": response.headers.get("Content-Type")}


def worker_command(symbol: str, target: date, destination: Path) -> list[str]:
    return [sys.executable, "-m", "momentum_research_agent.crowding_history", symbol,
            target.isoformat(), str(destination)]


def run_worker(symbol: str, target: date, destination: Path, timeout: float):
    return subprocess.run(worker_command(symbol, target, destination), timeout=min(20., timeout), check=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def import_file(spec_path: Path, symbol: str, target: date) -> tuple[dict, dict]:
    spec = json.loads(spec_path.read_text())
    if spec["schema_version"] != "issuer_file_import_v1" or spec["as_of"] != target.isoformat():
        raise ValueError("Import manifest version/date mismatch")
    item = spec["funds"][symbol]
    url = item["source_url"]
    base = cd.product_url(symbol)
    if not (url == base or url.startswith(base + "/") or url.startswith(base + "?")):
        raise ValueError("Import must identify this fund's official issuer URL")
    fetched = datetime.fromisoformat(item["retrieved_at"].replace("Z", "+00:00"))
    if fetched.tzinfo is None or fetched > datetime.now(timezone.utc) or fetched.date() < target:
        raise ValueError("Invalid import retrieval timestamp")
    path = cd.checked(spec_path.parent, item["holdings_file"], item["sha256"])
    if path.stat().st_size > 8_000_000:
        raise ValueError("Import too large")
    raw = {"holdings_csv": path.read_text(encoding="utf-8-sig")}
    if "product_file" in item:
        page = cd.checked(spec_path.parent, item["product_file"], item["product_sha256"])
        if page.stat().st_size > 8_000_000:
            raise ValueError("Import page too large")
        raw["product_html"] = page.read_text(encoding="utf-8-sig")
    provenance = {"holdings_url": url, "fetched_at": fetched.isoformat(), "input_manifest_sha256": sha256_file(spec_path),
                  "provenance": "user-supplied issuer export; hash verifies integrity, not authenticity"}
    raw["import_provenance"] = provenance
    return raw, provenance


def collect(root: Path, target: date, spec: Path | None) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    (root / "vendor").mkdir()
    (root / "normalized").mkdir()
    started = time.monotonic()
    manifest = {"version": VERSION, "target_date": target.isoformat(), "sources": {}, "attempts": [],
                "started_at": datetime.now(timezone.utc).isoformat(), "request_semantics": "exact-date historical issuer backfill; no latest fallback"}
    for symbol in PRODUCTS:
        manifest["sources"][symbol] = {"status": "unavailable", "source": cd.product_url(symbol)}
        for attempt in range(1, 2 if spec is not None else 3):
            remaining = TOTAL_TIMEOUT - (time.monotonic() - started)
            if remaining <= 0:
                manifest["sources"][symbol]["error"] = "total_deadline"
                break
            event = {"symbol": symbol, "attempt": attempt, "status": "running", "mode": "import" if spec else "download",
                     "started_at": datetime.now(timezone.utc).isoformat()}
            manifest["attempts"].append(event)
            save_json(root / "manifest.json", manifest)
            destination = root / "vendor" / f"{symbol}-{attempt}.json"
            tick = time.monotonic()
            try:
                if spec is not None:
                    raw, provenance = import_file(spec, symbol, target)
                    save_json(destination, raw)
                else:
                    run_worker(symbol, target, destination, remaining)
                    provenance = {"holdings_url": historical_url(symbol, target), "fetched_at": datetime.now(timezone.utc).isoformat(),
                                  "provenance": "downloaded from issuer historical CSV route; response date validated"}
                entry = cd.archive(root, destination, symbol, target, f"{symbol}.json")
                if entry["as_of"] != target.isoformat():
                    raise ValueError("Exact historical date required; older data also rejected")
                manifest["sources"][symbol] = {**entry, **provenance}
                event["status"] = "ok"
            except Exception as exc:
                event.update(status="failed", error_type=type(exc).__name__)
            finally:
                if destination.is_file():
                    event.update(raw_path=str(destination.relative_to(root)), raw_sha256=sha256_file(destination))
                event["elapsed_s"] = round(time.monotonic() - tick, 3)
                save_json(root / "manifest.json", manifest)
            if event["status"] == "ok":
                break
    save_json(root / "manifest.json", manifest)
    return cd.replay(root, None)


def copy_reference(reference: Path, output: Path, earlier: date) -> dict:
    """Copy only validated evidence, never trust summary metrics from the report."""
    report = json.loads(reference.read_text())
    if report["schema_version"] == "etf_proxy_brief_v1":
        if report["calculation_version"] != "etf_proxy_metrics_v1":
            raise ValueError("Different calculation version")
        requested = report["requested_as_of"]
    elif report["schema_version"] == SCHEMA:
        requested = report["target_date"]
    else:
        raise ValueError("Not a compatible ETF report")
    if report["crowding"]["version"] != VERSION or date.fromisoformat(requested) <= earlier:
        raise ValueError("Comparison requires a newer same-version issuer report")
    origin = reference.parent / "crowding"
    manifest_path = cd.checked(origin, "manifest.json", report["crowding"]["manifest_sha256"])
    manifest = json.loads(manifest_path.read_text())
    if manifest["version"] != VERSION or manifest["target_date"] != requested:
        raise ValueError("Reference manifest version/date mismatch")
    for symbol, entry in manifest["sources"].items():
        if symbol not in PRODUCTS:
            raise ValueError("Unsupported comparison basket")
        if entry["status"] == "ok":
            fund = cd.load_fund(origin, entry)
            if entry["symbol"] != symbol or entry["target_date"] != requested or fund["as_of"] != requested:
                raise ValueError("Reference must have exact target-date observations")
    output.mkdir(parents=True, exist_ok=False)
    (output / "vendor").mkdir()
    (output / "normalized").mkdir()
    copied = {"version": VERSION, "target_date": requested, "sources": {},
              "origin_manifest_sha256": sha256_file(manifest_path)}
    for symbol, entry in manifest["sources"].items():
        cloned = dict(entry)
        if entry["status"] == "ok":
            for kind, directory in (("raw", "vendor"), ("normalized", "normalized")):
                src = cd.checked(origin, entry[kind + "_path"], entry[kind + "_sha256"])
                dest = output / directory / f"{symbol}.json"
                dest.write_bytes(src.read_bytes())
                cloned[kind + "_path"] = str(dest.relative_to(output))
        copied["sources"][symbol] = cloned
    save_json(output / "manifest.json", copied)
    return {"manifest_sha256": sha256_file(output / "manifest.json"),
            "origin_manifest_sha256": copied["origin_manifest_sha256"], "target_date": requested}


def delta(before: float, after: float) -> dict:
    return {"previous": before, "current": after, "delta": after - before}


def compare(before: dict, after: dict) -> dict:
    result = {"status": "unavailable", "from_date": before["target_date"], "to_date": after["target_date"],
              "funds": {}, "overlaps": {}, "limitations": [
                  "No flow inference across snapshots: daily shares, NAV and splits are needed.",
                  "Changes can reflect prices, reconstitution or classification changes, not necessarily capital flows.",
                  "Reported equity weights are not rescaled; compare equity coverage alongside concentration.",
                  "Retrospective issuer observations, not publication-time/PIT-certified evidence."]}
    if before["version"] != after["version"] or before["target_date"] >= after["target_date"]:
        raise ValueError("Incompatible snapshot versions or dates")
    for symbol in PRODUCTS:
        a, b = before["funds"].get(symbol, {}), after["funds"].get(symbol, {})
        if (a.get("status") != "ok" or b.get("status") != "ok" or
                a["as_of"] != before["target_date"] or b["as_of"] != after["target_date"]):
            result["funds"][symbol] = {"status": "unavailable"}
            continue
        ac, bc = a["concentration"], b["concentration"]
        result["funds"][symbol] = {"status": "ok", **{key: delta(ac[key], bc[key]) for key in
                                    ("top10_weight", "equity_hhi", "equity_weight", "equity_listings")},
                                    "sector_weights": {sector: delta(ac["sector_weights"].get(sector, 0.), bc["sector_weights"].get(sector, 0.))
                                    for sector in sorted(ac["sector_weights"].keys() | bc["sector_weights"].keys())}}
        result["status"] = "partial"
    for pair in ("MTUM/QUAL", "MTUM/IVV"):
        a, b = before["overlaps"].get(pair, {}), after["overlaps"].get(pair, {})
        result["overlaps"][pair] = ({"status": "ok", **{key: delta(a[key], b[key]) for key in
                                     ("weighted_overlap", "shared_listings", "left_shared_weight", "right_shared_weight")}}
                                    if a.get("status") == b.get("status") == "ok" else {"status": "unavailable"})
    return result


def replay(root: Path) -> dict:
    result = json.loads((root / "backfill.json").read_text())
    if result["schema_version"] != SCHEMA:
        raise ValueError("Unknown backfill report")
    cd.checked(root, "crowding/manifest.json", result["crowding"]["manifest_sha256"])
    result["crowding"] = cd.replay(root / "crowding", None)
    if result["crowding"]["target_date"] != result["target_date"]:
        raise ValueError("Backfill target mismatch")
    result["status"] = result["crowding"]["status"]
    result["comparison"] = dict(NO_COMPARISON)
    if "reference" in result:
        cd.checked(root, "reference/crowding/manifest.json", result["reference"]["manifest_sha256"])
        current = cd.replay(root / "reference/crowding", None)
        result["comparison"] = compare(result["crowding"], current)
    return result


def render(result: dict) -> str:
    lines = [f"# Historical issuer backfill — {result['target_date']}", "", f"Status: {result['status']}", "",
             cd.render(result["crowding"]), "", "## Holdings comparison", ""]
    comparison = result["comparison"]
    if comparison["status"] == "unavailable":
        lines.append(comparison.get("reason", "No compatible exact-date pair available."))
    else:
        lines += [f"{comparison['from_date']} → {comparison['to_date']}", "",
                  "| Fund | Top-10 before | Top-10 after | Change (pp) | HHI before | HHI after |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for symbol, item in comparison["funds"].items():
            if item["status"] == "ok":
                t, h = item["top10_weight"], item["equity_hhi"]
                lines.append(f"| {symbol} | {t['previous']:.2%} | {t['current']:.2%} | {100*t['delta']:+.2f} | {h['previous']:.4f} | {h['current']:.4f} |")
        lines.append("")
        for pair, item in comparison["overlaps"].items():
            if item["status"] == "ok":
                d = item["weighted_overlap"]
                lines.append(f"- {pair} weighted overlap: {d['previous']:.2%} → {d['current']:.2%} ({d['delta']*100:+.2f} pp).")
        lines += ["", "Full sector changes and equity coverage are in backfill.json."]
    lines += ["", "No flow inference across dates. No original-engine score comparison or LLM calls.",
              "Imported-file provenance is user-supplied; hashes establish integrity, not authenticity or publication time.", ""]
    return "\n".join(lines)


def run(target: date, root: Path, spec: Path | None = None, reference: Path | None = None) -> dict:
    target = target_date(target)
    root.mkdir(parents=True, exist_ok=False)
    result = {"schema_version": SCHEMA, "target_date": target.isoformat(),
              "generated_at": datetime.now(timezone.utc).isoformat(), "status": "unavailable", "llm_requests": 0,
              "crowding": collect(root / "crowding", target, spec),
              "comparison": dict(NO_COMPARISON)}
    result["status"] = result["crowding"]["status"]
    if reference is not None:
        try:
            result["reference"] = copy_reference(reference, root / "reference/crowding", target)
            result["comparison"] = compare(result["crowding"], cd.replay(root / "reference/crowding", None))
        except (OSError, ValueError, KeyError, TypeError):
            result["comparison"] = dict(NO_COMPARISON)
    save_json(root / "backfill.json", result)
    (root / "backfill.md").write_text(render(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    save_json(Path(sys.argv[3]), fetch(sys.argv[1], date.fromisoformat(sys.argv[2])))
