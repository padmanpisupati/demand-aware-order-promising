"""LangGraph-style promise workflow with a dependency-free fallback runner.

load_context -> check_supply -> score_risk -> propose -> govern(policy gate + HITL + commit) -> END
"""
from __future__ import annotations
from typing import Any, Callable, TypedDict

from .atp import propose, supply_for
from .governance import Guard


class PromiseState(TypedDict, total=False):
    line: dict
    sku: dict
    substitute: dict | None
    supply: Any
    risk: float
    drivers: list
    proposal: dict
    result: dict


def build_nodes(model, guard: Guard, transit_p50: float, transit_p80: float, horizon: int) -> list[tuple[str, Callable]]:
    audit = guard.audit

    def check_supply(st):
        s = supply_for(st["sku"])
        audit.record("supply_checked", "supply_agent", {"line": st["line"]["line_id"], "on_hand": round(s.on_hand, 1),
                                                       "inbound": s.inbound, "inbound_eta": s.inbound_eta})
        return {"supply": s}

    def score_risk(st):
        r = model.predict(st["sku"])
        drivers = [(f, round(c, 3)) for f, c in model.explain(st["sku"])]
        audit.record("risk_scored", "risk_agent", {"line": st["line"]["line_id"], "risk": round(r, 4), "drivers": drivers})
        return {"risk": r, "drivers": drivers}

    def make_proposal(st):
        p = propose(st["line"], st["supply"], st["risk"], transit_p50, transit_p80, st.get("substitute"), horizon)
        audit.record("promise_proposed", "atp_agent", {"line": st["line"]["line_id"], "type": p["type"],
                                                      "promise_day": p["promise_day"], "confidence": p["confidence"]})
        return {"proposal": p}

    def govern(st):
        s, sub = st["supply"], st.get("substitute")
        ceiling = s.on_hand + s.inbound + (sub["on_hand"] if sub and st["proposal"]["type"] == "substitute" else 0)
        ceiling = max(ceiling, st["line"]["qty"]) if st["proposal"]["shipments"] and \
            st["proposal"]["shipments"][-1][2] == "replenishment" else ceiling
        res = guard.commit_promise(st["line"]["line_id"], {"proposal": st["proposal"], "risk": st["risk"],
                                                           "value": st["line"]["value"], "supply_ceiling": ceiling})
        return {"result": res}

    return [("check_supply", check_supply), ("score_risk", score_risk), ("propose", make_proposal), ("govern", govern)]


class FallbackRunner:
    def __init__(self, nodes):
        self.nodes = nodes

    def invoke(self, state: dict) -> dict:
        st = dict(state)
        for _, fn in self.nodes:
            st.update(fn(st))
        return st


def build_graph(model, guard, transit_p50, transit_p80, horizon=45, engine="auto"):
    nodes = build_nodes(model, guard, transit_p50, transit_p80, horizon)
    if engine in ("auto", "langgraph"):
        try:
            from langgraph.graph import StateGraph, END
            g = StateGraph(PromiseState)
            for name, fn in nodes:
                g.add_node(name, fn)
            g.set_entry_point(nodes[0][0])
            for (a, _), (b, _) in zip(nodes, nodes[1:]):
                g.add_edge(a, b)
            g.add_edge(nodes[-1][0], END)
            return g.compile(), "langgraph"
        except ImportError:
            if engine == "langgraph":
                raise
    return FallbackRunner(nodes), "fallback"
