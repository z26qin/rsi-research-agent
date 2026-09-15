"""Concentration from complete official CSV archives; no inferred history or flows."""

from __future__ import annotations

import base64
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from momentum_research_agent.crowding_metrics import PRODUCTS, concentration, normalize


def snapshot(data: dict) -> dict:
    url = data["url"]
    symbol = next(
        s
        for s, path in PRODUCTS.items()
        if url.startswith("https://www.ishares.com/us/products/" + path + "/")
    )
    raw = base64.b64decode(data["body_base64"], validate=True).decode("utf-8-sig")
    fund = normalize({"holdings_csv": raw}, symbol, date.today())
    for address in (url, data.get("requested_url", url)):
        requested = parse_qs(urlparse(address).query, keep_blank_values=True).get(
            "asOfDate"
        )
        if requested and (
            len(requested) != 1
            or datetime.strptime(requested[0], "%Y%m%d").date().isoformat()
            != fund["as_of"]
        ):
            raise ValueError("Requested historical date does not match file header")
    return fund


def summary(fund: dict) -> dict:
    stats = concentration(fund)
    top = sorted(
        fund["holdings"], key=lambda h: (-h["weight"], h["ticker"], h["exchange"])
    )[:10]
    return {
        "status": "ok",
        "symbol": fund["symbol"],
        "as_of": fund["as_of"],
        "top10_weight_pct": stats["top10_weight"] * 100,
        "largest": top[0],
        "top10": top,
        "sector_weights_pct": {k: v * 100 for k, v in stats["sector_weights"].items()},
        "equity_weight_pct": stats["equity_weight"] * 100,
        "equity_listings": stats["equity_listings"],
        "basis": "Original fund equity weights; share-class listings separate; full accepted CSV body, not truncated display text. Top10/sector fields in percent; individual holding weight is a fraction.",
        "limitations": [
            "Not a crowding measure or flow estimate.",
            "Reported weight coverage validates within 98-102% rounding tolerance; not a certificate of complete disclosure.",
            "No publication-time/PIT certification.",
        ],
    }


def compare(old: dict, new: dict) -> dict:
    if old["symbol"] != new["symbol"] or old["as_of"] >= new["as_of"]:
        raise ValueError("Need the same fund and strictly increasing observation dates")
    a, b = summary(old), summary(new)

    def key(h):
        return (h["ticker"], h["exchange"], h["currency"])

    before = {key(h): h for h in old["holdings"]}
    after = {key(h): h for h in new["holdings"]}
    atop, btop = {key(h) for h in a["top10"]}, {key(h) for h in b["top10"]}
    changes = []
    for identity in sorted(atop | btop):
        x, y = before.get(identity), after.get(identity)
        if x and y and x["name"] != y["name"]:
            raise ValueError("Listing name changed; identity needs review")
        old_weight, new_weight = x["weight"] if x else 0.0, y["weight"] if y else 0.0
        contribution = (new_weight if identity in btop else 0.0) - (
            old_weight if identity in atop else 0.0
        )
        changes.append(
            {
                "ticker": identity[0],
                "exchange": identity[1],
                "currency": identity[2],
                "weight_change_pp": (new_weight - old_weight) * 100,
                "top10_contribution_pp": contribution * 100,
                "in_previous_top10": identity in atop,
                "in_current_top10": identity in btop,
            }
        )
    return {
        "status": "ok",
        "from_date": old["as_of"],
        "to_date": new["as_of"],
        "top10_before_pct": a["top10_weight_pct"],
        "top10_after_pct": b["top10_weight_pct"],
        "top10_change_pp": b["top10_weight_pct"] - a["top10_weight_pct"],
        "largest_before": a["largest"],
        "largest_after": b["largest"],
        "sector_change_pp": {
            k: b["sector_weights_pct"].get(k, 0) - a["sector_weights_pct"].get(k, 0)
            for k in sorted(
                a["sector_weights_pct"].keys() | b["sector_weights_pct"].keys()
            )
        },
        "holdings_changes": sorted(
            changes, key=lambda h: -abs(h["top10_contribution_pp"])
        ),
        "basis": "Top10 contribution is current top10 weight minus previous top10 weight per listing, zero outside each top10. Entry into top10 is not necessarily a new portfolio holding.",
        "limitations": [
            "Weight shifts do not distinguish price moves, trades or reclassification.",
            "No inference of subscriptions, redemptions, crowding or causal trading activity.",
        ],
    }


def augment(
    data: dict, session_dir: Path, artifact: str | None, digest: str | None
) -> dict:
    unavailable = {
        "status": "unavailable",
        "top10_change_pp": None,
        "reason": "Need two compatible, dated, hash-validated official holdings snapshots.",
    }
    try:
        current = snapshot(data)
        result = {
            "holdings_summary": summary(current),
            "holdings_comparison": unavailable,
        }
    except (KeyError, ValueError, TypeError, StopIteration):
        return {
            "holdings_summary": {
                "status": "unavailable",
                "reason": "Not a valid complete configured issuer CSV, or historical date mismatch.",
            },
            "holdings_comparison": unavailable,
        }
    if not artifact or not digest:
        return result
    try:
        if not re.fullmatch(r"source_reads/[a-f0-9]{32}\.json", artifact):
            raise ValueError("Invalid archive path")
        path = (session_dir / artifact).resolve()
        path.relative_to(session_dir.resolve())
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Archive hash mismatch")
        previous_data = json.loads(raw)
        result["holdings_comparison"] = compare(snapshot(previous_data), current)
        result["holdings_comparison"]["previous_source"] = {
            "url": previous_data["url"],
            "artifact": artifact,
            "sha256": digest,
        }
    except (OSError, KeyError, ValueError, TypeError, StopIteration):
        pass
    return result


def retained_report(task, traces, session_dir: Path, reason: str):
    from momentum_research_agent.models.schemas import ResearchReport

    for trace in reversed(traces):
        if trace.tool != "read_url" or trace.truncated:
            continue
        try:
            observation = json.loads(trace.observation)
            artifact = observation["artifact"]
            if not re.fullmatch(r"source_reads/[a-f0-9]{32}\.json", artifact):
                continue
            path = (session_dir / artifact).resolve()
            path.relative_to(session_dir.resolve())
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != observation["sha256"]:
                continue
            data = json.loads(raw)
            computed = augment(
                data,
                session_dir,
                trace.arguments.get("compare_to_artifact"),
                trace.arguments.get("compare_to_sha256"),
            )
            current, comparison = (
                computed["holdings_summary"],
                computed["holdings_comparison"],
            )
            if current["status"] != "ok":
                continue
            rows = [
                ("Top10 weight", current["top10_weight_pct"], "%"),
                (
                    f"Largest holding {current['largest']['ticker']}",
                    current["largest"]["weight"] * 100,
                    "%",
                ),
            ]
            rows += [
                (f"Sector {name}", value, "%")
                for name, value in current["sector_weights_pct"].items()
            ]
            limitations = [reason, current["basis"], *current["limitations"]]
            if comparison["status"] == "ok":
                rows += [("Top10 change", comparison["top10_change_pp"], "pp")]
                limitations += [
                    f"Comparison: {comparison['from_date']} to {comparison['to_date']}.",
                    comparison["basis"],
                    *comparison["limitations"],
                ]
            else:
                limitations.append(
                    "Historical comparison unavailable; changes are unknown, not zero."
                )
            findings, metrics = [], []
            provenance = json.dumps(
                {
                    "current": {"artifact": artifact, "sha256": observation["sha256"]},
                    "previous": comparison.get("previous_source"),
                }
            )
            for index, (name, value, unit) in enumerate(rows):
                eid = f"{task.id}:holdings:{index}"
                claim = f"{name}: {value:.6f} {unit} as of {current['as_of']}."
                if name == "Top10 change":
                    claim += f" From {comparison['from_date']}."
                findings.append(
                    {
                        "id": eid,
                        "claim": claim,
                        "category": "other",
                        "stance": "neutral",
                        "source_url": data["url"],
                        "source_name": provenance,
                        "excerpt": claim,
                        "confidence": "medium",
                    }
                )
                metrics.append(
                    {
                        "name": name,
                        "value": value,
                        "unit": unit,
                        "as_of": current["as_of"],
                        "source_url": data["url"],
                        "evidence_id": eid,
                    }
                )
            return ResearchReport(
                task_id=task.id,
                title=task.title,
                agent_role=task.profile,
                summary="Calculated holdings observations retained; model interpretation incomplete.",
                status="partial",
                as_of=current["as_of"],
                sources=[data["url"]],
                findings=findings,
                metrics=metrics,
                limitations=limitations,
                unanswered_questions=[task.assignment],
            )
        except (OSError, KeyError, ValueError, TypeError, StopIteration):
            continue
    return None
