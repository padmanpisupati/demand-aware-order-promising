"""End-to-end demo: train risk model, run governed risk-aware ATP vs naive ATP, score vs simulated actuals."""
from __future__ import annotations
import argparse, json, random, statistics
from pathlib import Path

from . import data as D
from .atp import actual_completion, naive_promise, realise, supply_for
from .governance import Guard, HashChainAudit, PromiseLedger, PromisePolicy, SimulatedPlanner
from .graph import build_graph
from .risk import RiskModel, evaluate

LATE_TOL = 3  # days of slack before a miss counts as a "backorder surprise"


def score(proposal: dict, actual: list) -> dict:
    final_actual = max(d for _, d in actual)
    otif = all(a_d <= p_d for (_, a_d), (_, p_d, _) in zip(actual, proposal["shipments"]))
    return {"err": abs(final_actual - proposal["promise_day"]), "signed": final_actual - proposal["promise_day"],
            "otif": otif, "surprise": final_actual > proposal["promise_day"] + LATE_TOL}


def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {}
    return {"lines": len(rows), "mean_abs_promise_error_days": round(statistics.mean(r["err"] for r in rows), 2),
            "median_abs_promise_error_days": statistics.median(r["err"] for r in rows),
            "otif_proxy": round(sum(r["otif"] for r in rows) / len(rows), 3),
            "backorder_surprise_rate": round(sum(r["surprise"] for r in rows) / len(rows), 3),
            "mean_promise_day": round(statistics.mean(r["promise_day"] for r in rows), 2)}


def run(n_skus=6000, n_lines=1500, seed=42, engine="auto", out="out", backorder_csv=None, olist_csv=None) -> dict:
    rng = random.Random(seed)
    if backorder_csv:
        skus, bo_src = D.load_backorders(backorder_csv), f"public dataset file: {backorder_csv}"
    else:
        skus, bo_src = D.generate_backorders(n_skus, seed), "SYNTHETIC (schema of Kaggle product backorders)"
    orders = D.load_olist_orders(olist_csv) if olist_csv else D.generate_olist_orders(3000, seed)
    ol_src = f"public dataset file: {olist_csv}" if olist_csv else "SYNTHETIC (schema of Olist orders)"
    pool = D.transit_days(orders)
    t50, t80 = D.quantile(pool, 0.5), D.quantile(pool, 0.8)

    idx = list(range(len(skus))); rng.shuffle(idx)
    cut = int(0.7 * len(idx))
    train, test = [skus[i] for i in idx[:cut]], [skus[i] for i in idx[cut:]]
    model = RiskModel().fit(train)
    model_eval = evaluate(model, test)

    audit = HashChainAudit()
    ledger = PromiseLedger()
    guard = Guard(PromisePolicy(), audit, SimulatedPlanner(), ledger)
    graph, used_engine = build_graph(model, guard, t50, t80, engine=engine)

    agent_rows, naive_rows, outcomes = [], [], {}
    candidates = [s for s in test if s["forecast_3_month"] > 0]
    for i in range(n_lines):
        sku = rng.choice(candidates)
        sub = rng.choice(candidates) if rng.random() < 0.3 else None
        sub_view = {"sku": sub["sku"], "on_hand": supply_for(sub).on_hand} if sub else None
        qty = max(1, int(sku["forecast_3_month"] / 3 * rng.uniform(0.1, 0.9)))
        price = rng.choice(orders)["price"] if "price" in orders[0] else 100.0
        line = {"line_id": f"L{i:05d}", "sku_id": sku["sku"], "qty": qty, "value": round(float(price) * qty, 2),
                "allow_partial": rng.random() < 0.5}
        true_risk = D.latent_supply_risk(sku) if not backorder_csv else (1.0 if sku["went_on_backorder"] == "Yes" else 0.05)
        world = realise(i, sku, pool, true_risk, seed)
        s = supply_for(sku)
        audit.record("line_received", "intake", {"line": line["line_id"], "sku": sku["sku"], "qty": qty, "value": line["value"]})

        nv = naive_promise(line, s, t50)
        naive_rows.append({**score(nv, actual_completion(nv, s, world)), "promise_day": nv["promise_day"]})

        st = graph.invoke({"line": line, "sku": sku, "substitute": sub_view})
        p, res = st["proposal"], st["result"]
        key = f"{p['type']}/{res['status']}"
        outcomes[key] = outcomes.get(key, 0) + 1
        if res["status"] == "committed":
            agent_rows.append({**score(p, actual_completion(p, s, world)), "promise_day": p["promise_day"],
                               "approval": res["approval"], "idx": len(naive_rows) - 1})
        else:
            agent_rows.append({"escalated": True, "idx": len(naive_rows) - 1, "approval": res["approval"]})

    committed = [r for r in agent_rows if not r.get("escalated")]
    naive_same = [naive_rows[r["idx"]] for r in committed]
    needs_review = sum(1 for r in agent_rows if r.get("approval") in ("approved", "rejected"))
    results = {
        "data_sources": {"backorder": bo_src, "olist": ol_src},
        "engine": used_engine, "risk_model": {"backend": model.backend, **model_eval,
                                              "coefficients": dict(zip(__import__('dop.risk', fromlist=['F']).FEATURES,
                                                                       [round(c, 3) for c in model.coef]))},
        "transit_days": {"p50": round(t50, 2), "p80": round(t80, 2)},
        "lines": n_lines, "outcomes": dict(sorted(outcomes.items())),
        "agent_committed": summarise(committed),
        "naive_same_lines": summarise(naive_same),
        "naive_all_lines": summarise(naive_rows),
        "commit_rate": round(len(committed) / n_lines, 3),
        "escalation_rate": round(1 - len(committed) / n_lines, 3),
        "approval_rate_of_lines": round(needs_review / n_lines, 3),
        "hitl_approved": sum(1 for r in agent_rows if r.get("approval") == "approved"),
        "hitl_rejected": sum(1 for r in agent_rows if r.get("approval") == "rejected"),
        "audit_records": len(audit.records), "audit_chain_valid": audit.verify(),
    }
    Path(out).mkdir(parents=True, exist_ok=True)
    Path(out, "results.json").write_text(json.dumps(results, indent=2))
    with open(Path(out, "audit.jsonl"), "w") as fh:
        for r in audit.records:
            fh.write(json.dumps(r, default=str) + "\n")
    Path(out, "results.md").write_text(render(results))
    return results


def render(r: dict) -> str:
    a, n = r["agent_committed"], r["naive_same_lines"]
    rows = [("Mean abs promise-date error (days)", "mean_abs_promise_error_days"),
            ("Median abs promise-date error (days)", "median_abs_promise_error_days"),
            ("OTIF proxy", "otif_proxy"), ("Backorder-surprise rate (>3d late)", "backorder_surprise_rate"),
            ("Mean promised lead time (days)", "mean_promise_day")]
    lines = [f"# Results ({r['data_sources']['backorder']}; {r['data_sources']['olist']})", "",
             f"Engine: {r['engine']} | lines: {r['lines']} | risk model: {r['risk_model']['backend']}", "",
             "| Metric | Naive ATP | Risk-aware governed ATP |", "|---|---|---|"]
    lines += [f"| {lab} | {n[k]} | {a[k]} |" for lab, k in rows]
    lines += ["", f"Compared on the {a['lines']} lines the agent committed (same lines, same simulated world).",
              f"Escalated to planner: {r['escalation_rate']:.1%} | lines routed to HITL: {r['approval_rate_of_lines']:.1%} "
              f"(approved {r['hitl_approved']}, rejected {r['hitl_rejected']})",
              f"Audit records: {r['audit_records']} | hash chain valid: {r['audit_chain_valid']}", "",
              "Risk model (holdout): " + ", ".join(f"{k}={r['risk_model'][k]}" for k in
                                                     ("n", "base_rate", "auc", "precision@0.5", "recall@0.5")),
              "", "Outcomes: " + ", ".join(f"{k}={v}" for k, v in r["outcomes"].items()), ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--engine", default="auto", choices=["auto", "langgraph", "fallback"])
    ap.add_argument("--out", default="out")
    ap.add_argument("--backorder-csv"); ap.add_argument("--olist-csv")
    a = ap.parse_args()
    r = run(n_lines=a.lines, seed=a.seed, engine=a.engine, out=a.out, backorder_csv=a.backorder_csv, olist_csv=a.olist_csv)
    print(render(r))


if __name__ == "__main__":
    main()
