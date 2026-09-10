import json
import pytest
from pydantic import ValidationError
from momentum_research_agent.models.schemas import ResearchReport


@pytest.mark.parametrize('question, expected', [
    ('What are MTUM’s top 10 holdings? Include weights and observation date.', 'single'),
    ('MTUM前十大持仓权重是多少？', 'single'),
    ('Compare momentum crowding and volatility with May 29', 'team'),
    ('为什么动量风险上升？对比上月波动率', 'team'),
    ('What is realized volatility?', 'single'),
    ('Explain why MTUM underperformed SPY', 'team'),
    ('How crowded is momentum now?', 'team'),
    ('现在动量拥挤吗？', 'team'),
])
def test_intent_routes_facts_separately_from_analysis(question, expected):
    from momentum_research_agent.research_contract import route_question
    assert route_question(question, 'auto')['mode'] == expected
    assert route_question(question, 'single')['mode'] == 'single'


def test_catalog_uses_existing_issuer_config_not_generated_paths():
    from momentum_research_agent.research_contract import source_catalog
    text = source_catalog('MTUM top holdings')
    assert '251614/ishares-msci-usa-momentum-factor-etf/latest-holdings.csv' in text
    assert '239729' not in text
    assert source_catalog('Unknown XYZ fund') == ''


def test_cli_default_is_auto_not_implicit_deep_research():
    from momentum_research_agent.cli import build_parser
    assert build_parser().parse_args(['MTUM top holdings']).mode == 'auto'


@pytest.mark.asyncio
async def test_issuer_read_to_numeric_report_offline(tmp_path,monkeypatch):
    import importlib
    from momentum_research_agent.agents.sub_agent import SubAgent
    from momentum_research_agent.models.schemas import Task
    from test_react_loop import FakeClient,FakeResponse,FakeMessage,FakeToolCall
    url='https://www.ishares.com/us/products/251614/ishares-msci-usa-momentum-factor-etf/latest-holdings.csv'
    async def fetch(address):
        assert address == url
        return {'url':url,'text':'Holdings as of Sep 08, 2026\nTicker,Weight (%)\nAAA,10.5', 'links':[], 'truncated':False,'content_type':'text/csv'}
    monkeypatch.setattr(importlib.import_module('momentum_research_agent.tools.read_url'),'_fetch',fetch)
    report={'task_id':'t','title':'Recorded holdings example','agent_role':'momentum_analyst','summary':'AAA weighs 10.5%.','status':'complete',
        'findings':[{'id':'e','claim':'AAA 10.5%','category':'other','stance':'neutral','source_url':url}],
        'metrics':[{'name':'AAA weight','value':10.5,'unit':'% portfolio','as_of':'2026-09-08','source_url':url,'evidence_id':'e'}]}
    client=FakeClient([FakeResponse(FakeMessage(tool_calls=[FakeToolCall('r','read_url',json.dumps({'url':url}))])),FakeResponse(FakeMessage(content=json.dumps(report)))])
    result=await SubAgent(client,'test',tmp_path).run(Task(title='Holdings',assignment='MTUM holdings',profile='momentum_analyst'),None,tmp_path)
    assert result.report.metrics[0].value == 10.5
    assert result.report.metrics[0].evidence_id == result.report.findings[0].id
    assert url in client.completions.calls[0]['messages'][1]['content']
    assert len(list((tmp_path/'source_reads').glob('*.json'))) == 1


def test_numeric_metrics_reject_nan_and_require_evidence_for_values():
    base = dict(task_id='t',title='Risk',agent_role='momentum_analyst',summary='Risk metrics')
    metadata = dict(as_of='2026-09-08',source_url='https://example.com',evidence_id='e')
    with pytest.raises(ValidationError):
        ResearchReport(**base, findings=[{'id':'e','claim':'vol','category':'other','stance':'neutral','source_url':'https://example.com'}],
                       metrics=[{'name':'vol','value':float('nan'),'unit':'%',**metadata}])
    with pytest.raises(ValidationError):
        ResearchReport(**base, metrics=[{'name':'vol','value':21,'unit':'%',**metadata}])


def test_failed_retrieval_becomes_limitation_not_followup_evidence():
    from momentum_research_agent.research_contract import ground_report, answer_status
    from momentum_research_agent.agents.ledger import record_trace
    report=ResearchReport(task_id='t',title='Holdings',agent_role='momentum_analyst',summary='Read blocked',findings=[
        {'id':'e','claim':'The source could not be read','category':'other','stance':'neutral','source_url':'https://example.com'}])
    trace=record_trace('read_url',{'url':'https://example.com'},json.dumps({'status':'unavailable'}))
    result=ground_report(report,[trace])
    assert not result.findings and any('The source could not be read' in item for item in result.limitations)
    assert result.status == 'insufficient_evidence' and answer_status([result]) == 'unanswered'


def test_cross_task_evidence_ids_and_metric_references_do_not_collide():
    from momentum_research_agent.agents.sub_agent import _bind_report
    from momentum_research_agent.models.schemas import Task
    def report():
        return ResearchReport(task_id='t',title='Holdings',agent_role='momentum_analyst',summary='AAA is 10%',findings=[
            {'id':'e1','claim':'AAA is 10%','category':'other','stance':'neutral','source_url':'https://example.com'}],
            metrics=[{'name':'AAA','value':10,'unit':'%','as_of':'2026-09-08','source_url':'https://example.com','evidence_id':'e1'}])
    a,b=[_bind_report(Task(id=id,title='Holdings',assignment='MTUM',profile='momentum_analyst'),report()) for id in ['a','b']]
    assert a.findings[0].id != b.findings[0].id
    assert a.metrics[0].evidence_id == a.findings[0].id
    assert b.metrics[0].evidence_id == b.findings[0].id


def test_failed_source_cannot_leave_an_asserted_numeric_summary():
    from momentum_research_agent.research_contract import ground_report,answer_status
    from momentum_research_agent.agents.ledger import record_trace
    report=ResearchReport(task_id='t',title='Holdings',agent_role='momentum_analyst',summary='AAA is 10%',status='complete',findings=[
        {'id':'e','claim':'AAA is 10%','category':'other','stance':'neutral','source_url':'https://example.com'}],
        metrics=[{'name':'AAA','value':10,'unit':'%','as_of':'2026-09-08','source_url':'https://example.com','evidence_id':'e'}])
    trace=record_trace('read_url',{'url':'https://example.com'},json.dumps({'status':'unavailable'}))
    result=ground_report(report,[trace])
    assert 'AAA is 10%' not in result.summary
    assert result.metrics[0].value is None
    assert answer_status([result]) == 'unanswered'


def test_missing_metric_prevents_answer_available_even_with_context_evidence():
    from momentum_research_agent.research_contract import answer_status
    report=ResearchReport(task_id='t',title='Holdings',agent_role='momentum_analyst',summary='Context only',status='complete',findings=[
        {'claim':'Momentum ETF','category':'other','stance':'neutral'}],
        metrics=[{'name':'Top holdings','value':None,'unit':'%','missing_reason':'Source unavailable'}])
    assert answer_status([report]) == 'partial'
