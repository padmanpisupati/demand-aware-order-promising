# ADR-0005: A four-step governed workflow is sufficient for order promising

**Status:** accepted (2026-10). Supersedes [ADR-0001](0001-risk-aware-atp-as-governed-graph.md).

**Context.** v0.1 described the flow as an "agent graph" with per-step actors (`supply_agent`, `risk_agent`, `atp_agent`). In practice:
- **One context.** Every step works on the same order line, the same SKU supply position, and one risk score. No step needs its own memory, tools, or planning loop.
- **No open-ended reasoning.** Choosing a promise type is a bounded decision table (ADR-0003). Whatever freedom an agent added would be freedom to break a customer commitment.
- **Control matters most.** A promise date is a customer commitment and an ERP write. Reviewers need to see one gate and one write path, in that order, every time.
- **Cost and latency.** Promising runs inline with order entry, often thousands of lines an hour. An LLM or multi-agent loop per line would add cost and tail latency that the decision doesn't need.

**Decision.** The promise flow is a fixed workflow of four plain functions:

`retrieve_context (supply + risk score) → decide_promise → policy_gate (incl. HITL) → commit_or_escalate`

- `retrieve_context` is read-only: ATP inputs plus the explainable logistic-regression risk score and its top drivers.
- `decide_promise` applies the deterministic decision table (full / partial split / alternate date / substitute / escalate).
- `policy_gate` calls `Guard.gate()`: default-deny policy-as-code, with planner approval *inside* the gate when P4–P6 fire. It never writes.
- `commit_or_escalate` is the only write. `Guard.commit()` refuses unless it gets a passing verdict. Escalations write an explicit `promise_escalated` audit event for the planner queue.
- LangGraph stays an **optional** engine for this linear flow. `FallbackRunner` runs the same functions, and tests check the two engines give identical results.
- There is no LLM in the decision loop. If one is added (for drafting customer messages or planner notes), it sits outside the commit path as a single LLM with read-only tools.

**When this would need revisiting** (with eval evidence): multi-plant or multi-source allocation that needs negotiated plans across lines; unstructured inputs (supplier emails, carrier notices) that must change a promise; promise decisions that need iterative what-if planning a decision table can't express; or teams that must own and release parts on their own. Even then, any agents would propose into the same gate and write path.

**Consequences.**
+ Lower cost and latency per line, and fully deterministic (same input, same promise, same audit trail).
+ Easier to govern: one gate, one write, and a test asserts every commit or escalation follows a policy decision.
+ Easier to evaluate: the naive-vs-risk-aware comparison is a reproducible replay.
+ Results are unchanged from v0.1 (OTIF proxy 0.792 vs 0.514, surprise rate 0.122 vs 0.302). Audit records go from 9,094 to 9,149 because escalations are now logged explicitly.
− No joint optimization across order lines competing for the same scarce supply. Lines are promised one at a time in arrival order, as most ERP ATP checks do.
