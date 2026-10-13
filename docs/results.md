# Results (SYNTHETIC (schema of Kaggle product backorders); SYNTHETIC (schema of Olist orders))

Engine: langgraph | lines: 1500 | risk model: scikit-learn

| Metric | Naive ATP | Risk-aware governed ATP |
|---|---|---|
| Mean abs promise-date error (days) | 5.33 | 5.9 |
| Median abs promise-date error (days) | 3 | 5 |
| OTIF proxy | 0.514 | 0.792 |
| Backorder-surprise rate (>3d late) | 0.302 | 0.122 |
| Mean promised lead time (days) | 12.22 | 15.94 |

Compared on the 1445 lines the workflow committed (same lines, same simulated world).
Escalated to planner: 3.7% | lines routed to HITL: 9.9% (approved 149, rejected 0)
Audit records: 9149 | hash chain valid: True

Risk model (holdout): n=1800, base_rate=0.2444, auc=0.838, precision@0.5=0.496, recall@0.5=0.759

Outcomes: alternate_date/committed=125, alternate_date/escalated=5, escalate/escalated=50, full/committed=1250, partial_split/committed=16, substitute/committed=54

## How to read this

- **All numbers are SYNTHETIC.** Supply, backorder labels, carrier transit times and the "actual" fulfillment are generated from schema-faithful simulators (seed 42). They demonstrate mechanics, not real-world performance.
- **Promise accuracy vs simulated actual fulfillment.** Each order line gets one hidden realisation (inbound delay, partial fill, replenishment delay, carrier transit). Naive and risk-aware promises are scored against the *same* realisation.
- **OTIF proxy** = every promised shipment arrives on or before its promised day, in full.
- **Backorder-surprise rate** = final delivery lands more than 3 days after the promised date (the customer finds out about the backorder after the promise was made).
- **Trade-off, stated honestly:** the risk-aware workflow promises about 3–4 days later on average and its *absolute* date error is slightly higher, because buffered promises often deliver early. It cuts late surprises by roughly 60% and lifts the OTIF proxy by ~28 points. Whether that trade is right is a business choice (see ADR-0003); the buffer coefficient is the tuning knob.
- **Escalations** (~4% of lines) are excluded from the workflow's accuracy rows and handed to a planner; the naive baseline is compared on the same committed lines. Naive figures over *all* lines are in `out/results.json` (`naive_all_lines`).
- **Risk model** is evaluated on a 30% holdout of the synthetic SKU table. AUC ~0.84 reflects the synthetic generator, not the real Kaggle data (where published work typically reports high AUC with heavy class imbalance, ~0.7% positives).
- The simulated planner approved every routed line in this run (its reject rule needs risk ≥ 0.85 and value ≥ 20,000); the rejection path is covered by unit tests.
- **Audit count.** 9,149 records vs 9,094 before the workflow refactor: the only difference is a new explicit `promise_escalated` event for each of the 55 escalated lines. Every promise metric is unchanged.
