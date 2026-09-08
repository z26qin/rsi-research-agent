"""Optional issuer-data sidecar. Immutable run directories; bounded subprocess I/O."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.crowding_metrics import PRODUCTS, VERSION, concentration, flow, normalize, overlap
from momentum_research_agent.proxy_data import save_json

TOTAL_TIMEOUT = 120.


def product_url(symbol: str) -> str:
    if symbol not in PRODUCTS:
        raise ValueError("Unsupported issuer fund")
    return "https://www.ishares.com/us/products/" + PRODUCTS[symbol]


def fetch(symbol: str, checkpoint: Path | None = None) -> dict:
    url = product_url(symbol)
    def read(address):
        request = urllib.request.Request(address, headers={"User-Agent": "momentum-research-agent/0.1 personal-research"})
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(8_000_001)
            if len(body) > 8_000_000:
                raise ValueError("Issuer response too large")
            return body.decode("utf-8-sig")
    result = {"holdings_csv": read(url + "/latest-holdings.csv")}
    if checkpoint is not None:
        save_json(checkpoint, result)
    try:
        result["product_html"] = read(url)
    except (OSError, ValueError) as exc:
        result["page_error"] = type(exc).__name__
    return result


def worker_command(symbol: str, destination: Path) -> list[str]:
    return [sys.executable, "-m", "momentum_research_agent.crowding_data", symbol, str(destination)]


def run_worker(symbol: str, destination: Path, timeout: float):
    return subprocess.run(worker_command(symbol, destination), timeout=min(20., timeout), check=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def checked(root: Path, relative: str, digest: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()) or sha256_file(path) != digest:
        raise ValueError("Issuer snapshot integrity failure")
    return path


def load_fund(root: Path, entry: dict) -> dict:
    raw = checked(root, entry["raw_path"], entry["raw_sha256"])
    saved = checked(root, entry["normalized_path"], entry["normalized_sha256"])
    actual = normalize(json.loads(raw.read_text()), entry["symbol"], date.fromisoformat(entry["target_date"]))
    if actual != json.loads(saved.read_text()):
        raise ValueError("Issuer normalization cannot be reproduced")
    return actual


def archive(root: Path, raw_path: Path, symbol: str, target: date, normalized_name: str) -> dict:
    normalized = normalize(json.loads(raw_path.read_text()), symbol, target)
    path = root / "normalized" / normalized_name
    save_json(path, normalized)
    return {"symbol": symbol, "target_date": target.isoformat(), "status": "ok",
            "source": product_url(symbol), "holdings_url": product_url(symbol) + "/latest-holdings.csv",
            "as_of": normalized["as_of"], "raw_path": str(raw_path.relative_to(root)), "raw_sha256": sha256_file(raw_path),
            "normalized_path": str(path.relative_to(root)), "normalized_sha256": sha256_file(path)}


def import_prior(root: Path, previous: Path) -> dict:
    report = json.loads(previous.read_text())
    if (report["schema_version"] != "etf_proxy_brief_v1" or
            report["calculation_version"] != "etf_proxy_metrics_v1" or report["crowding"]["version"] != VERSION):
        raise ValueError("Incompatible previous report")
    origin = previous.parent / "crowding"
    manifest_path = checked(origin, "manifest.json", report["crowding"]["manifest_sha256"])
    manifest = json.loads(manifest_path.read_text())
    if manifest["version"] != VERSION:
        raise ValueError("Incompatible previous issuer manifest")
    entry = manifest["sources"]["MTUM"]
    load_fund(origin, entry)
    raw = checked(origin, entry["raw_path"], entry["raw_sha256"])
    destination = root / "vendor" / "MTUM-prior.json"
    # Preserve bytes and pin lineage: replay must not depend on a mutable prior directory.
    destination.write_bytes(raw.read_bytes())
    result = archive(root, destination, "MTUM", date.fromisoformat(entry["target_date"]), "MTUM-prior.json")
    result["origin_manifest_sha256"] = sha256_file(manifest_path)
    result["fetched_at"] = entry["fetched_at"]
    return result


def build(root: Path, target: date, previous: Path | None, prices) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    (root / "vendor").mkdir()
    (root / "normalized").mkdir()
    start = time.monotonic()
    manifest = {"version": VERSION, "target_date": target.isoformat(), "sources": {}, "attempts": [],
                "started_at": datetime.now(timezone.utc).isoformat(),
                "request_semantics": "latest issuer files; reject future observations; not historical/PIT retrieval"}
    for symbol in PRODUCTS:
        manifest["sources"][symbol] = {"status": "unavailable", "source": product_url(symbol)}
        for number in (1, 2):
            remaining = TOTAL_TIMEOUT - (time.monotonic() - start)
            if remaining <= 0:
                manifest["sources"][symbol]["error"] = "total_deadline"
                break
            tick = time.monotonic()
            attempt = {"symbol": symbol, "number": number, "status": "running"}
            manifest["attempts"].append(attempt)
            save_json(root / "manifest.json", manifest)
            path = root / "vendor" / f"{symbol}-{number}.json"
            try:
                try:
                    run_worker(symbol, path, remaining)
                except subprocess.TimeoutExpired:
                    if not path.is_file():
                        raise
                    attempt["warning"] = "Worker timed out; validating checkpointed holdings; NAV may be unavailable"
                entry = archive(root, path, symbol, target, f"{symbol}.json")
                entry["fetched_at"] = datetime.now(timezone.utc).isoformat()
                manifest["sources"][symbol] = entry
                attempt["status"] = "ok"
            except Exception as exc:
                attempt.update(status="failed", error=type(exc).__name__)
            finally:
                attempt["elapsed_s"] = round(time.monotonic() - tick, 3)
                save_json(root / "manifest.json", manifest)
            if attempt["status"] == "ok":
                break
    if previous is not None:
        try:
            manifest["prior"] = import_prior(root, previous)
        except (OSError, ValueError, KeyError, TypeError):
            manifest["prior_error"] = "Incompatible or corrupt prior issuer snapshot; flow withheld"
    save_json(root / "manifest.json", manifest)
    return replay(root, prices)


def replay(root: Path, prices) -> dict:
    """Offline recomputation. MTUM split observations come from the checked core price snapshot."""
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["version"] != VERSION:
        raise ValueError("Unsupported issuer snapshot")
    target = manifest["target_date"]
    result = {"version": VERSION, "status": "unavailable", "target_date": target,
              "manifest_sha256": sha256_file(root / "manifest.json"), "funds": {}, "overlaps": {},
              "flow": {"status": "unavailable", "reason": manifest.get("prior_error", "Need compatible prior-session MTUM shares, NAV and split coverage")},
              "limitations": ["Partial crowding evidence, not a crowding score or proof of crowded positioning.",
                              "Three selected long-only ETFs from one issuer; not market-wide ownership or independent investors.",
                              "Concentration and overlap use reported equity weights, not renormalized; cash/derivatives excluded.",
                              "Exact listing matches may undercount overlap; share classes are separate; no fund look-through.",
                              "Weight totals must be 98–102% (rounding tolerance); this cannot certify complete holdings.",
                              "ETF net creations can reflect arbitrage/in-kind activity; not investor cash subscriptions.",
                              "Observation dates are not historical publication timestamps; no PIT certification."]}
    funds = {}
    for symbol, entry in manifest["sources"].items():
        try:
            if entry["status"] != "ok":
                raise ValueError("Source unavailable")
            item = load_fund(root, entry)
            if entry["target_date"] != target:
                raise ValueError("Issuer manifest date mismatch")
            funds[symbol] = item
            result["funds"][symbol] = {"status": "ok", "as_of": item["as_of"], "stale": item["as_of"] < target,
                                       "shares_outstanding": item["shares_outstanding"], "nav": item["nav"],
                                       "net_assets": item["net_assets"], "reported_weight_total": item["reported_weight_total"],
                                       "concentration": concentration(item), "source": entry["source"],
                                       "fetched_at": entry["fetched_at"], "warnings": item["warnings"]}
        except (OSError, ValueError, KeyError, TypeError):
            result["funds"][symbol] = {"status": "unavailable", "reason": "Missing or invalid issuer snapshot"}
    if "MTUM" in funds:
        result["status"] = "partial"
        for peer in ("QUAL", "IVV"):
            try:
                result["overlaps"][f"MTUM/{peer}"] = {"status": "ok", **overlap(funds["MTUM"], funds[peer])}
            except (ValueError, KeyError):
                result["overlaps"][f"MTUM/{peer}"] = {"status": "unavailable", "reason": "Need same-date, valid and unambiguous holdings"}
        if "prior" in manifest and prices is not None:
            try:
                prior = load_fund(root, manifest["prior"])
                if funds["MTUM"]["as_of"] != target:
                    raise ValueError("Stale current shares")
                result["flow"] = {"status": "ok", **flow(prior, funds["MTUM"], prices)}
            except (OSError, ValueError, KeyError, TypeError):
                result["flow"]["reason"] = "Incompatible dates, missing NAV/splits, or invalid prior snapshot"
    return result


def render(result: dict) -> str:
    lines = ["## Crowding indicators — partial evidence", "", f"Status: {result['status']}", ""]
    if "funds" not in result:
        return "\n".join(lines + [result.get("reason", "Unavailable")])
    lines += ["Concentration is not proof of crowding. IVV is the holdings benchmark; SPY remains the return benchmark.", "",
              "| Fund | Holdings date | Top-10 equity weight | Equity HHI | Equity coverage |",
              "| --- | --- | ---: | ---: | ---: |"]
    for symbol, item in result["funds"].items():
        if item["status"] != "ok":
            lines.append(f"| {symbol} | unavailable | — | — | — |")
            continue
        c = item["concentration"]
        lines.append(f"| {symbol} | {item['as_of']}{' (stale)' if item['stale'] else ''} | "
                     f"{c['top10_weight']:.2%} | {c['equity_hhi']:.4f} | {c['equity_weight']:.2%} |")
    lines.append("")
    for symbol, item in result["funds"].items():
        if item["status"] == "ok":
            sectors = "; ".join(f"{sector} {weight:.2%}" for sector, weight in item["concentration"]["sector_weights"].items())
            lines += [f"- {symbol} sectors (fund equity weights): {sectors}.",
                      f"- {symbol}: {item['shares_outstanding']:,.0f} shares outstanding as of {item['as_of']}; "
                      f"retrieved {item['fetched_at']}; [issuer]({item['source']})."]
            for label in ("nav", "net_assets"):
                value = item[label]
                lines.append(f"- {symbol} {label}: " + (f"USD {value['value']:,.2f} as of {value['as_of']}" if value else "unavailable"))
    lines += ["", "### Shared equity exposures", ""]
    for pair, item in result["overlaps"].items():
        if item["status"] == "ok":
            lines.append(f"- {pair}: Weighted overlap {item['weighted_overlap']:.2%}; {item['shared_listings']} shared listings; "
                         f"date {item['as_of']}. Overlap = sum of minimum reported weights across exact matched listings.")
        else:
            lines.append(f"- {pair}: unavailable — {item['reason']}.")
    f = result["flow"]
    lines += ["", "### MTUM estimated net creations/redemptions", ""]
    if f["status"] == "ok":
        lines.append(f"{f['from_date']} → {f['to_date']}: USD {f['estimated_net_creation_usd']:+,.2f}; "
                     f"split-adjusted share change {f['share_change_pct']:+.2%}; split ratio {f['split_ratio']:g}. {f['method']}.")
    else:
        lines.append(f"Unavailable — {f['reason']}. Not zero flows.")
    lines += ["", *[f"- {item}" for item in result["limitations"]], "", f"Version: {result['version']}; "
              f"issuer manifest SHA256: {result['manifest_sha256']}."]
    return "\n".join(lines)


if __name__ == "__main__":
    destination = Path(sys.argv[2])
    save_json(destination, fetch(sys.argv[1], destination))
