"""Agent orchestration tests.

The LLM is replaced by a scripted fake client (no network, no cost) — but every tool call
executes the REAL platform code, so these tests verify that agents actually run their tools,
that permissions / approvals / budgets are enforced, and that results come from tools.
"""
import json
from types import SimpleNamespace as NS

import pytest

from qopt.agents import AGENTS, AgentContext, AgentRuntime, AgentUnavailable, Budget
from qopt.industries import get_problem


def text(t):
    return NS(type="text", text=t)


def call(name, inp, cid):
    return NS(type="tool_use", id=cid, name=name, input=inp)


def resp(blocks, stop):
    return NS(content=blocks, stop_reason=stop, stop_details=None,
              usage=NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0,
                       cache_creation_input_tokens=0))


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        step = self.script.pop(0)
        return step(kw) if callable(step) else step


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)
        self.beta = NS(messages=self.messages)


def last_tool_result(kw):
    msg = kw["messages"][-1]
    assert msg["role"] == "user"
    return [json.loads(b["content"]) if not b.get("is_error") else b["content"] for b in msg["content"]]


def test_problem_understanding_agent_executes_real_tools():
    ex = get_problem("finance.portfolio").example()
    captured = {}

    def after_formulate(kw):
        out = last_tool_result(kw)[0]
        captured["model_id"] = out["model_id"]
        assert out["num_decision_variables"] == 6 and out["num_slack_variables"] > 0
        return resp([call("validate_formulation", {"model_id": out["model_id"]}, "t2")], "tool_use")

    def after_validate(kw):
        out = last_tool_result(kw)[0]
        assert out["exhaustive"]["passed"] is True
        return resp([call("run_classical_solver", {"model_id": captured["model_id"], "solver": "exhaustive"}, "t3")],
                    "tool_use")

    def after_solve(kw):
        out = last_tool_result(kw)[0]
        captured["selected"] = out["interpretation"]["selected_assets"]
        assert out["evaluation"]["feasible"] and out["result"]["proven_optimal"]
        return resp([text(f"Hold {captured['selected']}")], "end_turn")

    client = FakeClient([
        resp([text("Using the portfolio template."),
              call("formulate_industry_problem", {"key": "finance.portfolio", "data": ex,
                                                  "assumptions": ["costs in lakh"]}, "t1")], "tool_use"),
        after_formulate, after_validate, after_solve])
    rt = AgentRuntime(client=client, use_fallbacks=True)
    r = rt.run("problem_understanding", "Optimise my portfolio", AgentContext())
    assert r.status == "completed", r.error
    assert r.model_ids == [captured["model_id"]]
    assert [s["tool"] for s in r.steps if s["type"] == "tool"] == ["formulate_industry_problem",
                                                                    "validate_formulation", "run_classical_solver"]
    # request shape: official model id, explicit effort, server-side fallback beta
    kw = client.messages.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"] == {"effort": "high"}
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert {t["name"] for t in kw["tools"]} == set(AGENTS["problem_understanding"].tools)
    assert r.usage.requests == 4 and r.usage.cost_usd > 0


def test_permission_denied_for_tool_outside_allow_list():
    client = FakeClient([
        resp([call("submit_hardware_job", {"model_id": "x", "provider": "ibm_quantum", "backend": "b"}, "t1")],
             "tool_use"),
        lambda kw: (lambda r: resp([text("ok")], "end_turn"))(
            None if "not permitted" in kw["messages"][-1]["content"][0]["content"] else pytest.fail("no denial")),
    ])
    r = AgentRuntime(client=client).run("research_assistant", "run on QPU")
    assert r.status == "completed"
    assert "not permitted" in r.steps[1]["error"]


def test_hardware_request_creates_approval_and_never_submits():
    approvals = []
    ctx = AgentContext(request_approval=lambda req: approvals.append(req) or "apr_1")
    prob = get_problem("manufacturing.machine_scheduling")
    _, cm = prob.compile(prob.example())
    sm = ctx.store(cm)
    client = FakeClient([
        resp([call("submit_hardware_job", {"model_id": sm.model_id, "provider": "ibm_quantum",
                                           "backend": "ibm_x", "shots": 500}, "t1")], "tool_use"),
        resp([text("Approval requested.")], "end_turn")])
    r = AgentRuntime(client=client).run("hardware_integration", "run it on IBM", ctx)
    assert r.status == "approval_required" and r.approvals == ["apr_1"]
    assert approvals[0]["shots"] == 500 and approvals[0]["num_qubits"] == cm.qubo.num_variables


def test_missing_information_halts_instead_of_guessing():
    client = FakeClient([
        resp([call("request_missing_information", {"questions": ["What is the per-slot grid limit?"],
                                                   "reason": "grid limit unknown"}, "t1")], "tool_use")])
    r = AgentRuntime(client=client).run("problem_understanding", "Schedule 100 EVs")
    assert r.status == "needs_input"
    assert r.questions == ["What is the per-slot grid limit?"]
    assert len(client.messages.calls) == 1       # loop stopped; no further spend


def test_iteration_and_cost_budgets_enforced():
    loop = [resp([call("list_industry_problems", {}, f"t{i}")], "tool_use") for i in range(10)]
    r = AgentRuntime(client=FakeClient(loop), budget=Budget(max_iterations=3)).run("qubo_formulation", "go")
    assert r.status == "budget_exceeded" and r.usage.requests == 3
    # each fake call costs 1000*$4/M + 200*$20/M = $0.008; the cap is checked before every call,
    # so the run stops as soon as cumulative cost ≥ $0.01, i.e. after the 2nd call (≤ one call overshoot)
    r2 = AgentRuntime(client=FakeClient(loop), budget=Budget(max_cost_usd=0.01)).run("qubo_formulation", "go")
    assert r2.status == "budget_exceeded" and r2.usage.requests == 2
    assert r2.usage.cost_usd == pytest.approx(0.016)


def test_tool_errors_are_returned_to_model_not_hidden():
    def check(kw):
        b = kw["messages"][-1]["content"][0]
        assert b["is_error"] is True and "unknown model_id" in b["content"]
        return resp([text("The model id was wrong.")], "end_turn")
    client = FakeClient([resp([call("validate_formulation", {"model_id": "nope"}, "t1")], "tool_use"), check])
    r = AgentRuntime(client=client).run("scientific_validation", "validate")
    assert r.status == "completed"


def test_delegation_between_agents_shares_budget_and_context():
    prob = get_problem("telecom.base_station_assignment")
    ex = prob.example()
    client = FakeClient([
        # project manager delegates
        resp([call("delegate_to_agent", {"agent": "qubo_formulation", "task": "formulate telecom example"}, "p1")],
             "tool_use"),
        # sub-agent formulates
        resp([call("formulate_industry_problem", {"key": prob.key, "data": ex}, "s1")], "tool_use"),
        resp([text("Formulated.")], "end_turn"),
        # back in PM: sees model id
        lambda kw: resp([text("Done: " + last_tool_result(kw)[0]["model_ids"][0])], "end_turn"),
    ])
    ctx = AgentContext()
    r = AgentRuntime(client=client).run("project_manager", "Plan the telecom study", ctx)
    assert r.status == "completed" and len(ctx.models) == 1
    assert r.usage.requests == 4    # parent + child calls are all accounted for
    assert r.final_text.startswith("Done: m_")


def test_delegation_to_unlisted_agent_denied():
    client = FakeClient([
        resp([call("delegate_to_agent", {"agent": "security_quality", "task": "x"}, "p1")], "tool_use"),
        resp([text("denied")], "end_turn")])
    r = AgentRuntime(client=client).run("project_manager", "x")
    assert "may not delegate" in r.steps[1]["error"]


def test_refusal_is_reported():
    r = AgentRuntime(client=FakeClient([NS(content=[], stop_reason="refusal",
                                           stop_details=NS(category="cyber", explanation=""),
                                           usage=NS(input_tokens=1, output_tokens=1))])).run("research_assistant", "x")
    assert r.status == "refused" and "cyber" in r.error


def test_unavailable_without_credentials(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(AgentUnavailable):
        AgentRuntime().run("research_assistant", "hello")


def test_every_agent_tool_exists():
    from qopt.agents import TOOLS
    for a in AGENTS.values():
        assert set(a.tools) <= set(TOOLS), a.name
