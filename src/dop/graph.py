"""Governed order-promising workflow (four fixed steps) with an optional LangGraph engine.

    retrieve_context (supply + risk score) -> decide_promise -> policy_gate (incl. HITL) -> commit_or_escalate

This is a deterministic workflow, not a set of agents: each step is a plain function
with one job and one or two audit events, and the only write happens in
commit_or_escalate after a passing gate verdict. See ADR-0005 for why a workflow is
sufficient here. LangGraph is optional; the sequential FallbackRunner runs the same
step functions, and a test asserts both engines produce identical results.
"""
from __future__ import annotations
from typing import Any, Callable, TypedDict

from .atp import propose, supply_for
from .governance import Guard

STEPS = ("retrieve_context", "decide_promise", "policy_gate", "commit_or_escalate")


class PromiseState(TypedDict, total=False):
    line: dict
    sku: dict
    substitute: dict | None
    supply: Any
    risk: float
    drivers: list
    proposal: dict
    verdict: dict
    result: dict


def build_steps(model, guard: Guard, transit_p50: float, transit_p80: float, horizon: int) -> list[tuple[str, Callable]]:
    audit = guard.audit

    def retrieve_context(st):
        """Read-only: projected supply (ATP inputs) and an explainable backorder-risk score."""
        lid = st["line"]["line_id"]
        s = supply_for(st["sku"])
        audit.record("supply_checked", "workflow.retrieve_context", {"line": lid, "on_hand": round(s.on_hand, 1),
                                                                    "inbound": s.inbound, "inbound_eta": s.inbound_eta})
        r = model.predict(st["sku"])
        drivers = [(f, round(c, 3)) for f, c in model.explain(st["sku"])]
        audit.record("risk_scored", "workflow.retrieve_context", {"line": lid, "risk": round(r, 4), "drivers": drivers})
        return {"supply": s, "risk": r, "drivers": drivers}

    def decide_promise(st):
        """Deterministic decision table: full / partial split / alternate date / substitute / escalate."""
        p = propose(st["line"], st["supply"], st["risk"], transit_p50, transit_p80, st.get("substitute"), horizon)
        audit.record("promise_proposed", "workflow.decide_promise", {"line": st["line"]["line_id"], "type": p["type"],
                                                                     "promise_day": p["promise_day"],
                                                                     "confidence": p["confidence"]})
        return {"proposal": p}

    def policy_gate(st):
        """Policy-as-code, with human approval where policy requires it. Never writes."""
        s, sub = st["supply"], st.get("substitute")
        ceiling = s.on_hand + s.inbound + (sub["on_hand"] if sub and st["proposal"]["type"] == "substitute" else 0)
        ceiling = max(ceiling, st["line"]["qty"]) if st["proposal"]["shipments"] and \
            st["proposal"]["shipments"][-1][2] == "replenishment" else ceiling
        v = guard.gate(st["line"]["line_id"], {"proposal": st["proposal"], "risk": st["risk"],
                                               "value": st["line"]["value"], "supply_ceiling": ceiling})
        return {"verdict": v}

    def commit_or_escalate(st):
        lid, v = st["line"]["line_id"], st["verdict"]
        if v["verdict"] == "commit":
            return {"result": guard.commit(lid, st["proposal"], v)}
        audit.record("promise_escalated", "workflow.escalate", {"line": lid, "rule": v["rule"],
                                                               "approval": v["approval"], "queue": "planner"})
        return {"result": {"status": "escalated", "rule": v["rule"], "approval": v["approval"]}}

    steps = [("retrieve_context", retrieve_context), ("decide_promise", decide_promise),
             ("policy_gate", policy_gate), ("commit_or_escalate", commit_or_escalate)]
    assert tuple(n for n, _ in steps) == STEPS
    return steps


class FallbackRunner:
    """Dependency-free sequential runner over the same step functions."""
    def __init__(self, steps):
        self.nodes = steps

    def invoke(self, state: dict) -> dict:
        st = dict(state)
        for _, fn in self.nodes:
            st.update(fn(st))
        return st


def build_workflow(model, guard, transit_p50, transit_p80, horizon=45, engine="auto"):
    steps = build_steps(model, guard, transit_p50, transit_p80, horizon)
    if engine in ("auto", "langgraph"):
        try:
            from langgraph.graph import StateGraph, END
            g = StateGraph(PromiseState)
            for name, fn in steps:
                g.add_node(name, fn)
            g.set_entry_point(steps[0][0])
            for (a, _), (b, _) in zip(steps, steps[1:]):
                g.add_edge(a, b)
            g.add_edge(steps[-1][0], END)
            return g.compile(), "langgraph"
        except ImportError:
            if engine == "langgraph":
                raise
    return FallbackRunner(steps), "fallback"


build_graph = build_workflow  # backward-compatible name
build_nodes = build_steps
