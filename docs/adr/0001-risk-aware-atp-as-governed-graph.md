# ADR-0001: Risk-aware ATP as a governed agent graph

**Status:** accepted

**Context.** Classic ATP treats on-hand and inbound supply as certain. Order-management teams then spend effort on customer-facing re-promises when inbound supply slips. We want promises that reflect supply risk, but an ERP promise is a customer commitment that cannot be left to free-form agent behaviour.

**Decision.** Model the flow as an explicit graph: `check_supply → score_risk → propose → govern`. Each node has one job and writes one audit event. Commits happen only in `govern`, through a guard. LangGraph is used when it's installed; a plain sequential runner with identical node functions is the fallback, and a test asserts the two give identical results.

**Consequences.** + Deterministic, testable, replayable. + The graph shape maps one-to-one onto an ERP integration design (read ATP, call risk service, write promise via BAPI/API). − No LLM in the decision loop by design; an LLM could be added later to draft customer messages or planner notes, outside the commit path.
