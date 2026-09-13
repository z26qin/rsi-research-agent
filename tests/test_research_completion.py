import asyncio
import json

import pytest

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.sub_agent import SubAgent
from momentum_research_agent.models.schemas import Task
from test_react_loop import FakeClient, FakeMessage, FakeResponse, FakeToolCall


@pytest.mark.asyncio
async def test_partial_report_retains_sources_and_usage_after_final_timeout(tmp_path, monkeypatch):
    async def source(url):
        return json.dumps({'status':'ok','url':url,'text':'AAA 10%', 'evidence_kind':'page_content'})
    monkeypatch.setattr('momentum_research_agent.agents.sub_agent.resolve_tools',
        lambda names: ([{'type':'function','function':{'name':'read_url'}}], {'read_url':source}))
    client = FakeClient([FakeResponse(FakeMessage(tool_calls=[FakeToolCall('read','read_url','{"url":"https://example.com"}')]))])
    create = client.completions.create
    async def slow(**kwargs):
        if client.completions.calls:
            await asyncio.sleep(.2)
        return await create(**kwargs)
    client.completions.create = slow
    task = Task(title='Holdings',assignment='What holdings?',profile='momentum_analyst')
    result = await SubAgent(client,'test',tmp_path,budget=LoopBudget(overall_deadline_s=.08,llm_timeout_s=.04)).run(task,None,tmp_path)
    assert result.report.status == 'partial'
    assert result.report.findings == []  # Never promote incomplete model prose into claims.
    assert result.report.sources == ['https://example.com']
    assert result.report.unanswered_questions
    assert result.usage.total_tokens == 15 and result.tool_calls == 1
    saved = json.loads(next((tmp_path/'sub_reports').glob('*.json')).read_text())
    assert saved['status'] == 'partial' and saved['as_of'] is None
    assert 'read_url' in (tmp_path/'traces.jsonl').read_text()


@pytest.mark.asyncio
async def test_structured_answer_roundtrips_and_finalization_forces_partial(tmp_path):
    task = Task(title='Holdings',assignment='What holdings?',profile='momentum_analyst')
    payload = {'task_id':task.id,'title':'Holdings','agent_role':task.profile,
        'summary':'AAA is 10%','status':'complete', 'as_of':'2026-09-08',
        'sources':['https://example.com'], 'limitations':['Recorded example only'], 'findings':[]}
    client = FakeClient([FakeResponse(FakeMessage(content=json.dumps(payload)))])
    result = await SubAgent(client,'test',tmp_path,budget=LoopBudget(max_turns=1)).run(task,None,tmp_path)
    assert result.report.status == 'partial'
    assert str(result.report.as_of) == '2026-09-08'
    assert result.report.limitations == ['Recorded example only']
    assert result.report.summary == 'AAA is 10%'


@pytest.mark.asyncio
async def test_single_run_propagates_verifier_failure_and_blocks_task(tmp_path, monkeypatch):
    from rich.console import Console
    from momentum_research_agent import cli
    from momentum_research_agent.models.schemas import AgentRunResult, ResearchReport, UsageSummary
    report = ResearchReport(task_id='t', title='Answer', agent_role='momentum_analyst',
                            summary='Partial', status='insufficient_evidence')
    async def analyst(*args, **kwargs): return AgentRunResult(report=report)
    async def verifier(*args, **kwargs): raise RuntimeError('verifier unavailable')
    monkeypatch.setattr(cli.SubAgent, 'run', analyst)
    monkeypatch.setattr(cli.Verifier, 'run', verifier)
    with pytest.raises(RuntimeError, match='verifier unavailable'):
        await cli.run_single(question='q', session_dir=tmp_path, client=object(), model='test',
                             project_root=tmp_path, verbose=False, console=Console(), usage=UsageSummary())
    board = json.loads((tmp_path/'task_board.json').read_text())
    assert board['tasks'][0]['status'] == 'BLOCKED'
