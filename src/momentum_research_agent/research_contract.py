"""Small intent and evidence contracts; no extra model call or policy mutation."""
from __future__ import annotations

import json
import re

from momentum_research_agent.models.schemas import ResearchReport, ToolTrace


def route_question(question: str, mode: str = 'auto') -> dict[str, str]:
    if mode not in {'auto', 'single', 'team'}:
        raise ValueError('Unknown research mode')
    analytical = bool(re.search(
        r'\b(compare|comparison|why|analy[sz]e|research|assess|versus|vs\.?|outlook)\b'
        r'|为什么|为何|对比|比较|研究|分析|评估|是否.*(拥挤|风险)|(拥挤|风险).*吗'
        r'|\b(?:is .*(?:crowded|crowding|at risk)|how crowded)\b', question, re.I))
    selected = ('team' if analytical else 'single') if mode == 'auto' else mode
    return {'mode':selected, 'intent':'research' if selected == 'team' else 'direct_answer',
            'reason': 'Explicit user selection' if mode != 'auto' else
            ('Comparison, causal explanation or assessment requested' if analytical else 'Factual or ambiguous question: bounded single-analyst answer')}


def source_catalog(question: str) -> str:
    from momentum_research_agent.crowding_metrics import PRODUCTS
    rows = []
    for symbol, path in PRODUCTS.items():
        if re.search(r'(?<![A-Za-z])'+symbol+r'(?![A-Za-z])',question,re.I):
            base = 'https://www.ishares.com/us/products/' + path
            rows.append(f'{symbol}: holdings CSV {base}/latest-holdings.csv ; product page {base}')
    if not rows:
        return ''
    return ('\n\nConfigured issuer source directory (addresses, not data or verified answers). '
            'For holdings read the CSV directly first. Do not invent product IDs or ajax endpoints. '
            'These configured addresses supersede guessed paths in an assignment.\n' + '\n'.join(rows))


def ground_report(report: ResearchReport, traces: list[ToolTrace]) -> ResearchReport:
    def key(url): return url.split('#',1)[0].rstrip('/') if isinstance(url,str) else ''
    def is_web(url): return key(url).startswith(('https://', 'http://'))
    failed, leads, read = set(), set(), set()
    for trace in traces:
        try:
            data = json.loads(trace.observation)
        except ValueError:
            continue
        if not isinstance(data,dict): continue
        if trace.tool == 'read_url':
            urls = {key(trace.arguments.get('url')),key(data.get('url'))} - {''}
            (read if data.get('status') == 'ok' else failed).update(urls)
        elif trace.tool == 'web_search' and data.get('evidence_kind') == 'source_discovery':
            leads.update(key(s.get('url')) for s in data.get('sources',[]) if isinstance(s,dict))
    removed = [e for e in report.findings if e.kind == 'retrieval' or
               (is_web(e.source_url) and key(e.source_url) not in read)]
    if not removed: return report
    removed_ids = {e.id for e in removed}
    report.findings = [e for e in report.findings if e.id not in removed_ids]
    report.limitations = list(dict.fromkeys([*report.limitations, *(f'Unsubstantiated / retrieval-only item withheld: {e.claim}' for e in removed)]))
    # The narrative can mix supported and removed claims; do not retain that draft.
    report.summary = ('Partial evidence only. Some claims were withheld because their source content was not retrieved. '
                      'See the remaining findings, numeric observations and limitations.' if report.findings else
                      'The question remains unanswered: usable source evidence was not retrieved.')
    for metric in report.metrics:
        if metric.evidence_id in removed_ids:
            metric.value = None
            metric.missing_reason = 'Supporting source content was not retrieved'
            metric.evidence_id = None
    report.status = 'partial' if report.findings else 'insufficient_evidence'
    return report


def answer_status(reports: list[ResearchReport]) -> str:
    """Coverage signal, not independent truth verification."""
    if not reports or not any(r.findings for r in reports): return 'unanswered'
    if all(r.status == 'complete' and not r.unanswered_questions and not any(m.value is None for m in r.metrics) for r in reports): return 'answer_available'
    return 'partial'
