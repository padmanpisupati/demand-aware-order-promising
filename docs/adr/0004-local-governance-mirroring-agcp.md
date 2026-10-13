# ADR-0004: Local governance hooks that mirror the control plane

**Status:** accepted

**Context.** The governance patterns live in a separate reusable library (`agcp`, repo `agentic-governance-control-plane`). This package must run on its own.

**Decision.** Define `PolicyGate`, `AuditSink`, and `Approver` as Protocols in `dop/governance.py`, with minimal local implementations: default-deny policy-as-code, a SHA-256 hash-chained append-only audit, a simulated planner for HITL, and a `Guard` that exposes `gate()` (policy + HITL, never writes) and `commit()` (refuses without a passing verdict) plus a compensating `rollback`. `dop/adapters/agcp_adapter.py` is an optional adapter that mirrors audit events into `agcp.AuditLog` when that library is installed. As of v0.2 the adapter tests are re-run with the control-plane source on `PYTHONPATH`.

**Policy rules:** P0 unknown action → deny; P1 escalation → no commit; P2 qty above on-hand + inbound (+ substitute) → deny (no oversell); P3 confidence < 0.2 → deny; P4 value ≥ 5,000 **and** risk ≥ 0.5 → approval; P5 promise beyond 45 days → approval; P6 substitution → approval; otherwise auto-commit.

**Consequences.** + No hard dependency, and the same seams accept the shared control plane. − Two implementations of the same patterns exist until the adapter is promoted to the default.
