import json

from test_research_arena import ScriptedClient, response, script_for

from momentum_research_agent.eval.research_arena import ArenaControls, run_world
from momentum_research_agent.eval.research_world import load_approved_worlds
from momentum_research_agent.state.policies import PolicyStore


async def test_repair_cannot_expand_or_rewrite_research(tmp_path):
    world = load_approved_worlds()[0]
    script = script_for(world, world.hidden_facts)
    valid = script[3]
    payload = json.loads(valid.choices[0].message.content)
    invalid = json.loads(valid.choices[0].message.content)
    invalid["findings"][0]["category"] = "contrary_evidence"
    script[3] = response(invalid)
    controls = ArenaControls(max_schema_repairs=1)
    payload["findings"][0]["claim"] = "A new fabricated assertion."
    script.insert(4, response(payload))
    client = ScriptedClient(script)
    result = await run_world(
        client=client,
        requested_model="test",
        project_root=tmp_path,
        world=world,
        policy=PolicyStore(tmp_path).load_active(),
        session_dir=tmp_path / "run",
        controls=controls,
    )
    assert result.completion_status == "failed"
    assert not result.verifier_completed
    assert result.schema_repair_requests <= 1
    assert len(client.requests) == 5
    assert len(result.traces) == 2 + len({f.source_url for f in world.hidden_facts})
