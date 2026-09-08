"""Five daily research questions over replayed evidence; no policy or engine mutation."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from momentum_research_agent import crowding_data, proxy_brief
from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.react_loop import react_loop_detailed
from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.config import make_client, sub_agent_model
from momentum_research_agent.models.schemas import UsageSummary
from momentum_research_agent.proxy_data import save_json
from momentum_research_agent.proxy_metrics import calculate, sessions

VERSION = "market_research_brief_v1"
TITLES = {"momentum": "动量在增强还是走弱？", "concentration": "多头暴露是否集中？",
          "short_interest": "空头持仓压力如何变化？", "volatility": "波动率如何变化？",
          "crowding": "现在能否判断 momentum 拥挤？"}


class Focus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: list[Literal["momentum", "concentration", "short_interest", "volatility", "crowding"]] = Field(min_length=1, max_length=3)


class MarketBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["market_research_brief_v1"] = VERSION
    status: Literal["partial", "unavailable"]
    facts: dict
    short_interest: dict
    answers: dict[str, str]
    interpretation: dict
    inputs_sha256: str


def price_facts(root: Path, reference: date | None) -> tuple[dict, list[dict]]:
    report = proxy_brief.ProxyBrief.model_validate_json((root / "brief.json").read_text())
    target = report.requested_as_of
    if reference is not None and (reference >= target or reference not in sessions(reference, reference).date):
        raise ValueError("Reference must be an earlier XNYS session")
    facts = {"target_date": target.isoformat(), "status": report.status, "metrics": {}, "comparisons": {},
             "price_dates": {}, "price_coverage_start": {}, "fetched_at": {}, "split_safe": {}, "crowding": {},
             "comparison_method": "Same-vintage retrospective adjusted-price comparison, not historical/PIT knowledge.",
             "reference_date": reference.isoformat() if reference else None}
    holdings = []
    if report.status == "partial":
        proxy_brief.checked_path(root, "manifest.json", report.manifest_sha256)
        manifest, panels = proxy_brief.load_snapshot(root)
        if manifest["target_date"] != target.isoformat():
            raise ValueError("Core report date mismatch")
        facts["metrics"] = calculate(panels, target)
        prior = sessions(target - timedelta(days=14), target)[-2].date()
        for label, day in (("previous_session", prior), ("reference", reference)):
            if day is not None:
                facts["comparisons"][label] = {"date": day.isoformat(), "metrics": calculate(panels, day)}
        for symbol, panel in panels.items():
            facts["price_dates"][symbol] = panel.date.iloc[-1].date().isoformat()
            start = panel.date.iloc[0].date()
            facts["price_coverage_start"][symbol] = start.isoformat()
            facts["fetched_at"][symbol] = manifest["sources"][symbol]["fetched_at"]
            # Conservative: any split/invalid action anywhere in the saved window withholds SI share deltas.
            values = panel.stock_splits
            complete = panel.date.tolist() == sessions(start, target).tolist()
            facts["split_safe"][symbol] = bool(complete and np.isfinite(values).all() and (values == 0).all())
    if report.crowding.get("manifest_sha256"):
        try:
            facts["crowding"] = proxy_brief.replay_crowding(root)
            manifest = json.loads((root / "crowding/manifest.json").read_text())
            fund = crowding_data.load_fund(root / "crowding", manifest["sources"]["MTUM"])
            holdings = fund["holdings"]
            facts["holdings_date"] = fund["as_of"]
        except (OSError, ValueError, KeyError, TypeError):
            facts["crowding"] = {"status": "unavailable", "reason": "Issuer evidence failed replay"}
    return facts, holdings


def pct(value) -> str:
    return "不可用" if value is None else f"{value:.2%}"


def movement(current, previous) -> str:
    if current is None or previous is None:
        return "不可比较"
    delta = current - previous
    return "基本不变" if abs(delta) < 1e-10 else ("上升" if delta > 0 else "下降")


def answers(facts: dict, si: dict) -> dict[str, str]:
    metrics = facts.get("metrics", {})
    comparisons = facts.get("comparisons", {})
    relative = metrics.get("relative.return_21d")
    momentum = ("证据不足：核心价格或收益窗口不可用。" if relative is None else
                f"MTUM 近21日相对 SPY {relative:+.2%}（{'跑赢' if relative > 0 else '跑输' if relative < 0 else '持平'}），"
                f"近63日相对表现 {pct(metrics.get('relative.return_63d'))}；252日高点回撤 {pct(metrics.get('MTUM.drawdown_252d'))}。")
    volatility = f"21日年化实现波动率：MTUM {pct(metrics.get('MTUM.volatility_21d'))}，SPY {pct(metrics.get('SPY.volatility_21d'))}。"
    for label, item in comparisons.items():
        name = "上一交易日" if label == "previous_session" else "参考日"
        old = item["metrics"]
        momentum += f" 相对{name} {item['date']}，21日相对表现{movement(relative, old.get('relative.return_21d'))}（当时 {pct(old.get('relative.return_21d'))}）。"
        for symbol in ("MTUM", "SPY"):
            key = f"{symbol}.volatility_21d"
            volatility += f" {symbol} 对比{name} {item['date']}：{pct(old.get(key))} → {pct(metrics.get(key))}，{movement(metrics.get(key), old.get(key))}。"
    crowding = facts.get("crowding", {})
    fund = crowding.get("funds", {}).get("MTUM", {})
    concentration = "证据不足：未取得可验证的 MTUM 持仓。"
    if fund.get("status") == "ok":
        c = fund["concentration"]
        sector, weight = max(c["sector_weights"].items(), key=lambda pair: pair[1])
        concentration = (f"持仓日 {fund['as_of']}{'（滞后）' if fund['stale'] else ''}：Top10 {c['top10_weight']:.2%}，"
                         f"权益 HHI {c['equity_hhi']:.4f}，最大行业 {sector} {weight:.2%}，权益覆盖 {c['equity_weight']:.2%}。")
        peer = crowding.get("funds", {}).get("IVV", {})
        if peer.get("status") == "ok" and peer["as_of"] == fund["as_of"]:
            concentration += f" 同日 IVV Top10 {peer['concentration']['top10_weight']:.2%}。"
        concentration += " 集中度不等于真实拥挤；没有真实历史持仓不能判断集中度从参考日如何变化。"
    periods = si.get("periods", {})
    latest = (periods.get("latest") or {}).get("records", {}).get("MTUM")
    short = "证据不足：MTUM 最新公开 short interest 不可用。"
    if latest:
        dtc = "不可用" if latest["days_to_cover"] is None else f"{latest['days_to_cover']:.2f}"
        short = (f"MTUM ETF 空头股数 {latest['short_shares']:,}；结算日 {si['latest_settlement']}，"
                 f"公布日 {si['latest_publication']}；FINRA days-to-cover {dtc}。")
        for label, name in (("previous", "上一披露"), ("reference", "参考结算日")):
            old = (periods.get(label) or {}).get("records", {}).get("MTUM")
            start = facts.get("price_coverage_start", {}).get("MTUM")
            covered = start is None or (periods.get(label) or {}).get("settlement_date", "") >= start
            if (old and old["short_shares"] > 0 and facts.get("split_safe", {}).get("MTUM")
                    and covered and not old.get("split_flag") and not latest.get("split_flag")):
                short += f" 对比{name} {periods[label].get('settlement_date', '')}：{latest['short_shares'] / old['short_shares'] - 1:+.2%}。"
            else:
                short += f" 对比{name}不可用（缺数据、零基数或公司行动未排除）。"
    short += " 非每日数据：无新披露时维持最新观测，不将披露间变化写成今日变化。未取得同日可靠流通股分母，short float 不可用；不以 short-sale volume 替代。"
    short += " " + facts.get("si_update", "未提供可验证的上次 market brief，不判断本次是否有新披露。")
    basket = si.get("basket", {})
    if basket:
        short += (f" 固定当前成分股覆盖 {basket['covered_count']}/{basket['required_count']}，"
                  f"权重 {pct(basket['covered_weight'])}/{pct(basket['total_weight'])}；加权 DTC（非组合清仓时间）：")
        short += "，".join(f"{label} {value:.2f}" if value is not None else f"{label} 不可用"
                           for label, value in basket["weighted_days_to_cover"].items()) + "。"
        short += " 当前权重回看存在前视偏差；不跨股票汇总原始空头股数，不把成分股拆股前后股数直接比较。"
    return {"momentum": momentum, "concentration": concentration, "short_interest": short,
            "volatility": volatility,
            "crowding": "证据不足，不能据此确认或排除 momentum 拥挤。价格、集中度和ETF空头持仓是不同维度的代理；"
                        "缺少全市场持仓/借券利用率/借券费率及真实历史持仓。低波动不代表不拥挤，ETF空头也可能用于对冲或套利。"}


async def interpret(observations: dict[str, str], client=None, *, enabled: bool = True) -> dict:
    result = {"status": "fallback", "focus": ["crowding"], "llm_requests": 0,
              "reason": "disabled" if not enabled else "unavailable", "raw_response": None}
    if not enabled:
        return result
    owned = client is None
    usage = UsageSummary()
    try:
        if owned:
            client = make_client()
        if hasattr(client, "with_options"):
            client = client.with_options(max_retries=0)
        model = sub_agent_model()
        result["model"] = model
        def count():
            result["llm_requests"] += 1
        prompt = (Path(__file__).parent / "coordinator/prompts/market_focus.md").read_text()
        response = await react_loop_detailed(client, model, prompt, json.dumps(observations, ensure_ascii=False),
            tools=[], tool_registry={}, budget=LoopBudget(max_turns=1, overall_deadline_s=30, llm_timeout_s=25),
            before_llm_request=count, usage_tracker=usage, max_output_tokens=512, temperature=0)
        result["raw_response"] = response.text
        if not response.completed:
            raise ValueError("Incomplete model response")
        focus = Focus.model_validate_json(response.text).focus
        if len(set(focus)) != len(focus) or not set(focus) <= observations.keys():
            raise ValueError("Unknown or duplicate evidence ID")
        result.update(status="ok", focus=focus, reason="Validated selection of existing observations only")
    except Exception as exc:
        # Provider messages can contain sensitive request context; retain only exception type.
        result["reason"] = type(exc).__name__
    finally:
        result["usage"] = usage.model_dump(mode="json")
        if owned and client is not None:
            await client.close()
    return result


def replay(root: Path) -> dict:
    """Recompute deterministic answers offline; never call the model or a provider."""
    from momentum_research_agent import short_interest
    report = MarketBrief.model_validate_json((root / "market_brief.json").read_text())
    config_path = proxy_brief.checked_path(root, "market/inputs.json", report.inputs_sha256)
    config = json.loads(config_path.read_text())
    for relative, digest in config["hashes"].items():
        proxy_brief.checked_path(root, relative, digest)
    reference = date.fromisoformat(config["reference_date"]) if config["reference_date"] else None
    facts, _ = price_facts(root, reference)
    si = short_interest.replay(root / "market/short_interest")
    if si["target_date"] != facts["target_date"] or si.get("reference_date") != facts["reference_date"]:
        raise ValueError("Short-interest dates do not match report")
    facts["si_update"] = disclosure_update(root / "market", si)
    return {"facts": facts, "short_interest": si, "answers": answers(facts, si)}


def disclosure_update(sidecar: Path, current: dict) -> str:
    from momentum_research_agent import short_interest
    if not (sidecar / "previous_short_interest").is_dir():
        return "未提供可验证的上次 market brief，不判断本次是否有新披露。"
    try:
        prior = short_interest.replay(sidecar / "previous_short_interest")
        if prior["target_date"] >= current["target_date"]:
            raise ValueError("Prior target must be earlier")
        old, new = prior["latest_settlement"], current["latest_settlement"]
        if not old or not new or new < old:
            return "无法与上次披露状态比较；不把缺失数据记为零。"
        if old != new:
            return f"相对上次报告有新披露：结算日 {old} → {new}，不是今日仓位变化。"
        old_record = (prior["periods"]["latest"] or {}).get("records", {}).get("MTUM")
        new_record = (current["periods"]["latest"] or {}).get("records", {}).get("MTUM")
        if old_record != new_record:
            return f"无新披露结算日（{new}），但同日 MTUM 记录修订或覆盖变化；暂停跨快照比较。"
        return f"相对上次报告无新披露：仍为 {new} 的 MTUM 观测。"
    except (OSError, ValueError, KeyError, TypeError):
        return "上次 short-interest 证据不可验证；不判断本次是否有新披露。"


def render(report: MarketBrief) -> str:
    lines = [f"# Momentum market brief — {report.facts['target_date']}", "",
             f"Status: {report.status} | Personal research | {VERSION}", "",
             "代理研究，不是完整动量风险模型、投资建议或原引擎验证通过。", ""]
    for key, title in TITLES.items():
        lines += [f"## {title}", "", report.answers[key], ""]
    lines += ["## 关注重点（受限模型选择）", "",
              f"{report.interpretation['status']}；LLM requests: {report.interpretation['llm_requests']}。"
              "模型只能选择已有结论，不能编造数字、调用工具或修改政策。", ""]
    lines += [f"- {TITLES[key]}" for key in report.interpretation["focus"]]
    lines += ["", "## 数据与复算", "", f"实际价格日期：{report.facts['price_dates']}。",
              f"抓取时间：{report.facts['fetched_at']}。", report.facts["comparison_method"],
              "上一交易日与参考日价格指标从本次复权历史重算；不是通过旧快照修订检查的跨快照比较。",
              "[完整价格及持仓指标](brief.md) · [结构化研究报告](market_brief.json) · [输入哈希](market/inputs.json)",
              "[FINRA 披露日程](https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest) · "
              "[FINRA 空头持仓文件](https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files)", ""]
    lines += [f"- {item}" for item in report.short_interest.get("limitations", [])]
    return "\n".join(lines) + "\n"


async def run(root: Path, reference: date | None = None, *, llm: bool = True, client=None,
              previous: Path | None = None) -> MarketBrief:
    from momentum_research_agent import short_interest
    facts, holdings = price_facts(root, reference)
    sidecar = root / "market"
    sidecar.mkdir(exist_ok=False)
    si = await asyncio.to_thread(short_interest.build, sidecar / "short_interest",
                                 date.fromisoformat(facts["target_date"]), reference, holdings)
    if previous is not None:
        try:
            prior = replay(previous.parent)
            if prior["facts"]["target_date"] >= facts["target_date"]:
                raise ValueError("Prior report must be earlier")
            shutil.copytree(previous.parent / "market/short_interest", sidecar / "previous_short_interest")
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Core evidence remains usable; no inference of a new disclosure.
    facts["si_update"] = disclosure_update(sidecar, si)
    observations = answers(facts, si)
    interpretation = await interpret(observations, client, enabled=llm)
    hashes = {name: sha256_file(root / name) for name in
              ("brief.json", "manifest.json", "crowding/manifest.json", "market/short_interest/manifest.json",
               "market/previous_short_interest/manifest.json")
              if (root / name).is_file()}
    save_json(sidecar / "inputs.json", {"version": VERSION, "reference_date": facts["reference_date"], "hashes": hashes})
    report = MarketBrief(status=facts["status"], facts=facts, short_interest=si, answers=observations,
                         interpretation=interpretation, inputs_sha256=sha256_file(sidecar / "inputs.json"))
    save_json(root / "market_brief.json", report.model_dump(mode="json"))
    (root / "market_brief.md").write_text(render(report), encoding="utf-8")
    return report
