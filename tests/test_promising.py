import json
import pytest
from dop import data as D
from dop.atp import Supply, naive_promise, propose, risk_buffer_days
from dop.governance import (ALLOW, DENY, REQUIRE_APPROVAL, Guard, HashChainAudit, PromiseLedger,
                            PromisePolicy, SimulatedPlanner)
from dop.risk import RiskModel, evaluate
from dop.demo import run

LINE = {"line_id": "L1", "qty": 10, "value": 100.0, "allow_partial": True}


def test_generator_matches_public_schema():
    rows = D.generate_backorders(50)
    assert list(rows[0].keys()) == D.BACKORDER_COLUMNS
    o = D.generate_olist_orders(5)
    assert set(D.OLIST_COLUMNS) <= set(o[0])


def test_loader_roundtrip(tmp_path):
    p = tmp_path / "bo.csv"
    D.write_csv(D.generate_backorders(20), p, D.BACKORDER_COLUMNS)
    rows = D.load_backorders(p)
    assert len(rows) == 20 and isinstance(rows[0]["national_inv"], float)


def test_committed_samples_load():
    assert len(D.load_backorders("data/sample/backorder_sample_SYNTHETIC.csv")) > 100
    assert len(D.transit_days(D.load_olist_orders("data/sample/olist_orders_sample_SYNTHETIC.csv"))) > 100


def test_risk_model_learns_signal():
    rows = D.generate_backorders(3000, seed=1)
    m = RiskModel().fit(rows[:2000])
    assert evaluate(m, rows[2000:])["auc"] > 0.7
    assert len(m.explain(rows[0])) == 3


def test_pure_python_fallback_learns():
    rows = D.generate_backorders(800, seed=2)
    m = RiskModel(); m._fit_pure([__import__("dop.risk", fromlist=["x"]).featurize(r) for r in rows],
                                 [r["went_on_backorder"] == "Yes" for r in rows])
    assert evaluate(m, rows)["auc"] > 0.65


def test_buffer_monotonic_in_risk():
    assert risk_buffer_days(0.0, 28) == 0 < risk_buffer_days(0.3, 28) < risk_buffer_days(0.9, 28)


def test_full_from_stock():
    p = propose(LINE, Supply(50, 0, 14, 56), 0.9, 5, 8, None)
    assert p["type"] == "full" and p["promise_day"] == 8


def test_partial_split_when_allowed():
    p = propose(LINE, Supply(5, 20, 14, 56), 0.5, 5, 8, None)
    assert p["type"] == "partial_split" and sum(q for q, _, _ in p["shipments"]) == 10


def test_alternate_date_when_no_split_and_risky():
    p = propose({**LINE, "allow_partial": False}, Supply(5, 20, 14, 56), 0.5, 5, 8, None)
    assert p["type"] == "alternate_date"
    assert p["promise_day"] > naive_promise(LINE, Supply(5, 20, 14, 56), 5)["promise_day"]


def test_substitution_when_high_risk():
    p = propose(LINE, Supply(0, 20, 14, 56), 0.8, 5, 8, {"sku": "SKU9", "on_hand": 30})
    assert p["type"] == "substitute"


def test_escalate_beyond_feasible_horizon():
    p = propose(LINE, Supply(0, 0, 60, 120), 0.5, 5, 8, None)
    assert p["type"] == "escalate" and p["committed_qty"] == 0


def _ctx(ptype="full", day=10, conf=0.9, qty=10, ceiling=50, value=100, risk=0.1):
    return {"proposal": {"type": ptype, "promise_day": day, "confidence": conf, "committed_qty": qty,
                         "shipments": [(qty, day, "stock")]}, "value": value, "risk": risk, "supply_ceiling": ceiling}


@pytest.mark.parametrize("ctx,outcome,rule", [
    (_ctx(), ALLOW, "P9"),
    (_ctx(value=6000, risk=0.6), REQUIRE_APPROVAL, "P4"),
    (_ctx(day=60), REQUIRE_APPROVAL, "P5"),
    (_ctx(ptype="substitute"), REQUIRE_APPROVAL, "P6"),
    (_ctx(qty=100, ceiling=50), DENY, "P2"),
    (_ctx(conf=0.1), DENY, "P3"),
    (_ctx(ptype="escalate"), DENY, "P1"),
    (_ctx(value=4999.99, risk=0.99), ALLOW, "P9"),
])
def test_policy_rules(ctx, outcome, rule):
    d = PromisePolicy().evaluate("commit_promise", ctx)
    assert d.outcome == outcome and d.rule.startswith(rule)


def test_unknown_action_default_deny():
    assert PromisePolicy().evaluate("delete_order", _ctx()).outcome == DENY


def test_guard_hitl_reject_does_not_commit():
    audit, ledger = HashChainAudit(), PromiseLedger()
    g = Guard(PromisePolicy(), audit, SimulatedPlanner(), ledger)
    r = g.commit_promise("L1", _ctx(value=25000, risk=0.9))
    assert r["status"] == "escalated" and r["approval"] == "rejected" and "L1" not in ledger.rows
    r = g.commit_promise("L2", _ctx(value=6000, risk=0.6))
    assert r["approval"] == "approved" and "L2" in ledger.rows
    g.rollback("L2", "customer cancelled")
    assert "L2" not in ledger.rows and audit.records[-1]["event"] == "promise_cancelled"
    assert audit.verify()


def test_audit_tamper_detected():
    a = HashChainAudit()
    for i in range(5):
        a.record("e", "x", {"i": i})
    assert a.verify()
    a.records[2]["payload"]["i"] = 99
    assert not a.verify()


@pytest.mark.parametrize("engine", ["langgraph", "fallback"])
def test_demo_end_to_end(tmp_path, engine):
    r = run(n_skus=2000, n_lines=300, seed=3, engine=engine, out=str(tmp_path))
    assert r["engine"] == engine and r["audit_chain_valid"]
    a, n = r["workflow_committed"], r["naive_same_lines"]
    assert a["backorder_surprise_rate"] < n["backorder_surprise_rate"]
    assert a["otif_proxy"] > n["otif_proxy"]
    assert json.loads((tmp_path / "results.json").read_text())["lines"] == 300


def test_engines_agree():
    a = run(n_skus=1500, n_lines=200, seed=5, engine="langgraph", out="/tmp/dop_a")
    b = run(n_skus=1500, n_lines=200, seed=5, engine="fallback", out="/tmp/dop_b")
    assert a["outcomes"] == b["outcomes"] and a["workflow_committed"] == b["workflow_committed"]


def test_agcp_adapter_mirrors_or_skips():
    from dop.adapters.agcp_adapter import AgcpAuditSink, available
    sink = AgcpAuditSink(HashChainAudit())
    sink.record("e", "x", {})
    assert sink.verify() and isinstance(available(), bool)


def test_workflow_has_four_fixed_steps():
    from dop.graph import STEPS, FallbackRunner, build_workflow
    wf, eng = build_workflow(RiskModel(), Guard(PromisePolicy(), HashChainAudit(), SimulatedPlanner(), PromiseLedger()),
                             5, 8, engine="fallback")
    assert eng == "fallback" and isinstance(wf, FallbackRunner)
    assert tuple(n for n, _ in wf.nodes) == STEPS == ("retrieve_context", "decide_promise", "policy_gate",
                                                      "commit_or_escalate")


def test_commit_refuses_without_passing_gate():
    g = Guard(PromisePolicy(), HashChainAudit(), SimulatedPlanner(), PromiseLedger())
    with pytest.raises(PermissionError):
        g.commit("L1", {"type": "full"}, {"verdict": "escalate", "rule": "P2", "approval": None})
    assert g.ledger.rows == {}


def test_every_commit_and_escalation_follows_a_gate_decision(tmp_path):
    run(n_skus=1500, n_lines=200, seed=9, engine="fallback", out=str(tmp_path))
    gated, n_final = set(), 0
    for line in (tmp_path / "audit.jsonl").read_text().splitlines():
        r = json.loads(line)
        lid = r["payload"].get("line")
        if r["event"] == "policy_decision":
            gated.add(lid)
        if r["event"] in ("promise_committed", "promise_escalated"):
            assert lid in gated
            n_final += 1
    assert n_final == 200
