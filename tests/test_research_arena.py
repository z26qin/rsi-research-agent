"""Safety and grounding contracts for real ReAct runs in frozen worlds."""

import json
from types import SimpleNamespace as NS


from momentum_research_agent.eval.research_arena import ArenaControls, run_world
from momentum_research_agent.eval.research_world import load_approved_worlds
from momentum_research_agent.state.policies import PolicyStore


def response(payload, calls=(), model="frozen-test-model", finish="stop"):
    return NS(
        model=model,
        usage=NS(prompt_tokens=100, completion_tokens=100),
        choices=[
            NS(
                finish_reason="tool_calls" if calls else finish,
                message=NS(
                    content=json.dumps(payload) if payload is not None else None,
                    tool_calls=[
                        NS(
                            id=f"c{i}",
                            function=NS(name=name, arguments=json.dumps(args)),
                        )
                        for i, (name, args) in enumerate(calls)
                    ],
                ),
            )
        ],
    )


class ScriptedClient:
    """Only the external model transport is replaced; tools/runtime/verifier are real."""

    def __init__(self, script):
        self.script = iter(script)
        self.requests = []
        self.chat = NS(completions=NS(create=self.create))

    def with_options(self, **kwargs):
        return self

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs)))
        result = next(self.script)
        if isinstance(result, Exception):
            raise result
        return result


def script_for(world, facts):
    profile = world.allowed_profiles[0]
    findings = [
        {
            "id": f"e{i}",
            "claim": f.quote,
            "category": f.category.value,
            "stance": f.stance.value,
            "source_url": f.source_url,
            "excerpt": f.quote,
            "confidence": "high",
            "published_at": next(
                s.published_at for s in world.sources if s.url == f.source_url
            ),
        }
        for i, f in enumerate(facts)
    ]
    report = {
        "task_id": "research-1",
        "title": "Investigation",
        "agent_role": profile,
        "as_of": world.as_of,
        "summary": "Evidence assessment.",
        "findings": findings,
        "status": "insufficient_evidence" if world.require_withholding else "complete",
        "unanswered_questions": [
            f"Missing evidence: {q}." for q in world.missing_evidence
        ]
        if world.require_withholding
        else [],
        "contradictions": ["Sources disagree."] if world.contradiction_fact_ids else [],
    }
    urls = sorted({f.source_url for f in facts})
    script = [
        response({"profile": profile, "subquestion": world.research_question}),
        response(
            None,
            [
                ("engine_query", {"end": world.as_of}),
                ("web_search", {"query": "momentum recovery crowding risk"}),
            ],
        ),
    ]
    if urls:
        script.append(response(None, [("read_url", {"url": url}) for url in urls]))
    script += [
        response(report),
        response({"replan": False, "profile": profile, "subquestion": ""}),
    ]
    if urls:
        script.append(response(None, [("read_url", {"url": url}) for url in urls]))
    script.append(
        response(
            {
                "question": world.research_question,
                "overall_status": "pass",
                "summary": "Checked sources.",
                "verdicts": [
                    {
                        "evidence_id": f"research-1:{item['id']}",
                        "claim": item["claim"],
                        "status": "verified",
                        "rechecked_source": item["source_url"],
                    }
                    for item in findings
                ],
            }
        )
    )
    return script


async def run(tmp_path, world, facts):
    policy = PolicyStore(tmp_path).load_active()
    client = ScriptedClient(script_for(world, facts))
    result = await run_world(
        client=client,
        requested_model="test",
        project_root=tmp_path,
        world=world,
        policy=policy,
        session_dir=tmp_path / "run",
        controls=ArenaControls(),
    )
    return result, client


async def test_verifier_prompt_excludes_policy_and_hidden_evaluator_fields(tmp_path):
    from momentum_research_agent.state.policies import PolicyPatch, merge_policy_patch

    world = load_approved_worlds()[0]
    base = PolicyStore(tmp_path).load_active()
    policy = merge_policy_patch(
        base,
        PolicyPatch(
            prompt_overlays={world.allowed_profiles[0]: "PRIVATE_POLICY_SENTINEL"}
        ),
        trigger_ids=["private-trigger"],
    )
    client = ScriptedClient(script_for(world, world.hidden_facts))
    result = await run_world(
        client=client,
        requested_model="test",
        project_root=tmp_path,
        world=world,
        policy=policy,
        session_dir=tmp_path / "run",
        controls=ArenaControls(),
    )
    assert result.completion_status == "complete"
    assert any("PRIVATE_POLICY_SENTINEL" in json.dumps(req) for req in client.requests)
    verifier_requests = [
        req
        for req in client.requests
        if "independent verifier" in req["messages"][1]["content"]
    ]
    assert verifier_requests
    for req in verifier_requests:
        text = json.dumps(req)
        assert "Scope: frozen-source support" in req["messages"][0]["content"]
        assert "PRIVATE_POLICY_SENTINEL" not in text
        assert "hidden_facts" not in text
        assert "private-trigger" not in text
        assert "target_improvements" not in text
