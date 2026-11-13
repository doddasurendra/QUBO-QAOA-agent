"""Claude tool-use orchestrator with budgets, permissions, approvals and full logging.

Uses the official ``anthropic`` Python SDK (manual agentic loop so that permissions, approval
gating, budgets and audit logging are enforced on every tool call). The client is injectable
for tests; nothing here fabricates model output.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .definitions import AGENTS, AgentSpec
from .tools import TOOLS, AgentContext, NeedsUserInput, execute_tool, to_json

DEFAULT_MODEL = os.environ.get("QOPT_CLAUDE_MODEL", "claude-opus-5-5")
# USD per million tokens (Anthropic first-party list prices; update when pricing changes)
PRICING = {
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.10},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
    "claude-fable-5-2": {"input": 8.0, "output": 40.0, "cache_read": 0.20},
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AgentUnavailable(RuntimeError):
    pass


@dataclass
class Budget:
    max_iterations: int = 12
    max_output_tokens_total: int = 120_000
    max_cost_usd: float = 2.0
    max_delegation_depth: int = 2
    tool_timeout_s: float = 300.0


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    requests: int = 0
    cost_usd: float = 0.0

    def add(self, u, model: str):
        it = getattr(u, "input_tokens", 0) or 0
        ot = getattr(u, "output_tokens", 0) or 0
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        self.input_tokens += it; self.output_tokens += ot
        self.cache_read_tokens += cr; self.cache_write_tokens += cw
        self.requests += 1
        p = PRICING.get(model)
        if p:
            self.cost_usd += (it * p["input"] + ot * p["output"] + cr * p["cache_read"]
                              + cw * p["input"] * 1.25) / 1e6

    def merge(self, o: "Usage"):
        for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "requests"):
            setattr(self, k, getattr(self, k) + getattr(o, k))
        self.cost_usd += o.cost_usd


@dataclass
class RunResult:
    agent: str
    status: str            # completed | needs_input | approval_required | budget_exceeded | refused | error
    final_text: str
    steps: List[dict] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    questions: List[str] = field(default_factory=list)
    approvals: List[str] = field(default_factory=list)
    model_ids: List[str] = field(default_factory=list)
    findings: List[dict] = field(default_factory=list)
    error: Optional[str] = None
    model: str = DEFAULT_MODEL
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["usage"] = dict(self.usage.__dict__)
        d["cost_note"] = "estimated from token usage and list prices; not an invoice"
        return d


def credentials_status() -> dict:
    env = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return {"api_credentials_in_env": env, "model": DEFAULT_MODEL,
            "note": "Agents call the Anthropic API (billed per token, separate from any Claude subscription). "
                    "Set ANTHROPIC_API_KEY on the server; it is never sent to the browser."}


def make_client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AgentUnavailable("the 'anthropic' package is not installed") from exc
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_PROFILE")):
        raise AgentUnavailable("AI agents are unavailable: no Anthropic API credentials configured on the server "
                               "(set ANTHROPIC_API_KEY). All optimisation tools remain usable directly.")
    return anthropic.Anthropic(max_retries=2, timeout=600.0)


class AgentRuntime:
    def __init__(self, client=None, model: str = DEFAULT_MODEL, budget: Optional[Budget] = None,
                 use_fallbacks: Optional[bool] = None, logger: Optional[Callable[[dict], None]] = None):
        self._client = client
        self.model = model
        self.budget = budget or Budget()
        self.use_fallbacks = (os.environ.get("QOPT_CLAUDE_FALLBACKS", "1") != "0") if use_fallbacks is None else use_fallbacks
        self.logger = logger or (lambda e: None)

    @property
    def client(self):
        if self._client is None:
            self._client = make_client()
        return self._client

    # ------------------------------------------------------------------ API call
    def _create(self, spec: AgentSpec, messages: list, tools: list):
        kwargs: Dict[str, Any] = dict(model=self.model, max_tokens=16000, system=spec.system_prompt(),
                                      tools=tools, messages=messages,
                                      output_config={"effort": spec.effort})
        if self.use_fallbacks and self.model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"):
            return self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return self.client.messages.create(**kwargs)

    def _tool_defs(self, spec: AgentSpec, depth: int) -> list:
        defs = [TOOLS[n].api_definition() for n in spec.tools]
        if spec.can_delegate and depth < self.budget.max_delegation_depth:
            defs.append({"name": "delegate_to_agent",
                         "description": "Delegate a self-contained task to a specialist agent and receive its "
                                        "final report (and any model_ids it created). Agents: "
                                        + ", ".join(f"{a} ({AGENTS[a].title})" for a in spec.can_delegate),
                         "input_schema": {"type": "object", "properties": {
                             "agent": {"type": "string", "enum": spec.can_delegate},
                             "task": {"type": "string", "description": "complete instructions incl. model_ids"}},
                             "required": ["agent", "task"]}})
        return defs

    # ------------------------------------------------------------------ loop
    def run(self, agent: str, user_message: str, ctx: Optional[AgentContext] = None,
            history: Optional[list] = None, depth: int = 0, shared_usage: Optional[Usage] = None) -> RunResult:
        if agent not in AGENTS:
            raise KeyError(f"unknown agent {agent!r}; available: {sorted(AGENTS)}")
        spec = AGENTS[agent]
        ctx = ctx or AgentContext()
        t0 = time.perf_counter()
        res = RunResult(agent, "error", "", model=self.model)
        usage_total = shared_usage or res.usage
        messages = list(history or []) + [{"role": "user", "content": user_message}]
        tools = self._tool_defs(spec, depth)
        known_models = set(ctx.models)
        try:
            for it in range(self.budget.max_iterations):
                if usage_total.cost_usd >= self.budget.max_cost_usd or \
                        usage_total.output_tokens >= self.budget.max_output_tokens_total:
                    res.status = "budget_exceeded"
                    res.final_text = (f"Stopped: budget exhausted (cost ≈ ${usage_total.cost_usd:.4f}, "
                                      f"{usage_total.output_tokens} output tokens).")
                    break
                resp = self._create(spec, messages, tools)
                u = Usage(); u.add(resp.usage, self.model)
                res.usage.merge(u) if shared_usage is None else (res.usage.merge(u), shared_usage.merge(u))
                stop = resp.stop_reason
                text = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                res.steps.append({"type": "model", "iteration": it, "stop_reason": stop, "text": text,
                                  "usage": dict(u.__dict__)})
                self.logger({"event": "agent_model_call", "agent": agent, "iteration": it, "stop_reason": stop,
                             "usage": dict(u.__dict__)})
                if stop == "refusal":
                    det = getattr(resp, "stop_details", None)
                    res.status = "refused"
                    res.final_text = text or "The model declined this request."
                    res.error = f"refusal category={getattr(det, 'category', None)}"
                    break
                messages.append({"role": "assistant", "content": resp.content})
                if stop == "pause_turn":
                    continue
                if stop == "max_tokens":
                    res.status, res.final_text = "error", text
                    res.error = "response hit max_tokens"
                    break
                calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
                if stop != "tool_use" or not calls:
                    res.status, res.final_text = "completed", text
                    break
                results = []
                halt = None
                for call in calls:
                    out, is_err = self._run_tool(spec, call, ctx, depth, usage_total, res)
                    results.append({"type": "tool_result", "tool_use_id": call.id, "content": out,
                                    **({"is_error": True} if is_err else {})})
                    if isinstance(out, str) and out.startswith("__NEEDS_INPUT__"):
                        halt = "needs_input"
                if halt == "needs_input":
                    for r in results:
                        if r["content"].startswith("__NEEDS_INPUT__"):
                            r["content"] = "Questions sent to the user; wait for their answers."
                    messages.append({"role": "user", "content": results})
                    res.status = "needs_input"
                    res.final_text = "I need more information before continuing:\n" + \
                                     "\n".join(f"- {q}" for q in res.questions)
                    break
                messages.append({"role": "user", "content": results})
            else:
                res.status = "budget_exceeded"
                res.final_text = f"Stopped after the maximum of {self.budget.max_iterations} iterations."
            if res.approvals and res.status == "completed":
                res.status = "approval_required"
        except AgentUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — reported, never hidden
            res.status, res.error = "error", f"{type(exc).__name__}: {exc}"
            self.logger({"event": "agent_error", "agent": agent, "error": res.error})
        res.model_ids = [m for m in ctx.models if m not in known_models]
        res.findings = list(ctx.artifacts)
        res.duration_s = time.perf_counter() - t0
        res.messages = messages  # type: ignore[attr-defined]  (kept for multi-turn continuation)
        return res

    def _run_tool(self, spec: AgentSpec, call, ctx: AgentContext, depth: int, usage_total: Usage, res: RunResult):
        name, inp = call.name, dict(call.input or {})
        t0 = time.perf_counter()
        step = {"type": "tool", "tool": name, "input": inp}
        allowed = name in spec.tools or (name == "delegate_to_agent" and spec.can_delegate)
        try:
            if not allowed:
                raise PermissionError(f"agent {spec.name!r} is not permitted to use tool {name!r}")
            if name == "delegate_to_agent":
                if inp.get("agent") not in spec.can_delegate:
                    raise PermissionError(f"{spec.name!r} may not delegate to {inp.get('agent')!r}")
                if depth + 1 > self.budget.max_delegation_depth:
                    raise PermissionError("maximum delegation depth reached")
                sub = self.run(inp["agent"], inp["task"], ctx, depth=depth + 1, shared_usage=usage_total)
                res.questions += sub.questions
                res.approvals += sub.approvals
                out_d = {"agent": sub.agent, "status": sub.status, "report": sub.final_text,
                         "model_ids": sub.model_ids, "error": sub.error}
                step["delegated_steps"] = sub.steps
            else:
                out_d = execute_tool(name, ctx, inp)
                if TOOLS[name].requires_approval and out_d.get("approval_id"):
                    res.approvals.append(out_d["approval_id"])
            out, is_err = to_json(out_d), False
            step["output_preview"] = out[:2000]
        except NeedsUserInput as q:
            res.questions += q.questions
            out, is_err = "__NEEDS_INPUT__", False
            step["questions"] = q.questions
        except Exception as exc:  # noqa: BLE001 — tool errors go back to the model as is_error results
            out, is_err = f"Error: {type(exc).__name__}: {exc}", True
            step["error"] = out
        step["duration_s"] = time.perf_counter() - t0
        res.steps.append(step)
        self.logger({"event": "agent_tool_call", "agent": spec.name, "tool": name, "error": step.get("error"),
                     "duration_s": step["duration_s"]})
        return out, is_err
