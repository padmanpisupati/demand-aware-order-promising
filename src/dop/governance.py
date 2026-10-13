"""Minimal, local governance hooks mirroring the agentic-governance-control-plane patterns:
policy-as-code (default-deny), hash-chained append-only audit, HITL approval, guarded commit.
Interfaces are Protocols so the optional `agcp` adapter (adapters/agcp_adapter.py) can replace them.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

ALLOW, REQUIRE_APPROVAL, DENY = "allow", "require_approval", "deny"


@dataclass
class Decision:
    outcome: str
    rule: str
    reason: str


class PolicyGate(Protocol):
    def evaluate(self, action: str, ctx: dict) -> Decision: ...


class AuditSink(Protocol):
    def record(self, event: str, actor: str, payload: dict) -> dict: ...
    def verify(self) -> bool: ...


class Approver(Protocol):
    def review(self, proposal: dict, decision: Decision) -> tuple[bool, str]: ...


@dataclass
class PromisePolicy:
    """Policy-as-code for promise commits. Rules evaluated in order; first DENY wins, then approvals."""
    high_value: float = 5000.0
    high_risk: float = 0.5
    horizon_days: int = 45
    min_confidence: float = 0.2
    known_actions: tuple = ("commit_promise",)

    def evaluate(self, action: str, ctx: dict) -> Decision:
        if action not in self.known_actions:
            return Decision(DENY, "P0-default-deny", f"unknown action {action}")
        p = ctx["proposal"]
        if p["type"] == "escalate":
            return Decision(DENY, "P1-no-commit-on-escalation", "proposal is an escalation, nothing to commit")
        if p["committed_qty"] > ctx["supply_ceiling"]:
            return Decision(DENY, "P2-no-oversell", "promised qty exceeds on-hand + inbound + substitute")
        if p["confidence"] < self.min_confidence:
            return Decision(DENY, "P3-min-confidence", f"confidence {p['confidence']:.2f} < {self.min_confidence}")
        reasons = []
        if ctx["value"] >= self.high_value and ctx["risk"] >= self.high_risk:
            reasons.append("P4-high-value-x-high-risk")
        if p["promise_day"] > self.horizon_days:
            reasons.append("P5-beyond-horizon")
        if p["type"] == "substitute":
            reasons.append("P6-substitution-needs-approval")
        if reasons:
            return Decision(REQUIRE_APPROVAL, ",".join(reasons), "human approval required")
        return Decision(ALLOW, "P9-auto-commit", "within autonomous envelope")


class HashChainAudit:
    """Append-only, hash-chained audit log (tamper-evident). In-memory, optionally mirrored to JSONL."""
    def __init__(self, path: str | None = None):
        self.records: list[dict] = []
        self.path = path

    def record(self, event: str, actor: str, payload: dict) -> dict:
        prev = self.records[-1]["hash"] if self.records else "GENESIS"
        body = {"seq": len(self.records), "event": event, "actor": actor, "payload": payload, "prev": prev}
        body["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        self.records.append(body)
        if self.path:
            with open(self.path, "a") as fh:
                fh.write(json.dumps(body, default=str) + "\n")
        return body

    def verify(self) -> bool:
        prev = "GENESIS"
        for i, r in enumerate(self.records):
            b = {k: v for k, v in r.items() if k != "hash"}
            if r["seq"] != i or r["prev"] != prev:
                return False
            if hashlib.sha256(json.dumps(b, sort_keys=True, default=str).encode()).hexdigest() != r["hash"]:
                return False
            prev = r["hash"]
        return True


class SimulatedPlanner:
    """Deterministic stand-in for a human approver (replace with a ticket/queue integration)."""
    def __init__(self, reject_risk: float = 0.85, reject_value: float = 20000.0):
        self.reject_risk, self.reject_value = reject_risk, reject_value

    def review(self, proposal: dict, decision: Decision) -> tuple[bool, str]:
        if proposal["risk"] >= self.reject_risk and proposal["value"] >= self.reject_value:
            return False, "planner: exposure too high, expedite supply first"
        return True, "planner: approved"


@dataclass
class PromiseLedger:
    """Mock ERP promise table with compensating action (cancel_promise) for rollback."""
    rows: dict = field(default_factory=dict)

    def commit(self, line_id: str, proposal: dict) -> None:
        self.rows[line_id] = proposal

    def cancel(self, line_id: str) -> None:  # compensating action
        self.rows.pop(line_id, None)


class Guard:
    """Every ERP-style write goes through policy -> (HITL) -> commit, all audited."""
    def __init__(self, policy: PolicyGate, audit: AuditSink, approver: Approver, ledger: PromiseLedger):
        self.policy, self.audit, self.approver, self.ledger = policy, audit, approver, ledger

    def commit_promise(self, line_id: str, ctx: dict) -> dict:
        d = self.policy.evaluate("commit_promise", ctx)
        self.audit.record("policy_decision", "policy_gate", {"line": line_id, "outcome": d.outcome, "rule": d.rule})
        approved_by = None
        if d.outcome == DENY:
            return {"status": "escalated", "rule": d.rule, "approval": None}
        if d.outcome == REQUIRE_APPROVAL:
            ok, note = self.approver.review({**ctx["proposal"], "risk": ctx["risk"], "value": ctx["value"]}, d)
            self.audit.record("hitl_review", "planner", {"line": line_id, "approved": ok, "note": note, "rule": d.rule})
            if not ok:
                return {"status": "escalated", "rule": d.rule, "approval": "rejected"}
            approved_by = "planner"
        self.ledger.commit(line_id, ctx["proposal"])
        self.audit.record("promise_committed", "atp_agent", {"line": line_id, "proposal": ctx["proposal"],
                                                            "approved_by": approved_by})
        return {"status": "committed", "rule": d.rule, "approval": "approved" if approved_by else "auto"}

    def rollback(self, line_id: str, reason: str) -> None:
        self.ledger.cancel(line_id)
        self.audit.record("promise_cancelled", "atp_agent", {"line": line_id, "reason": reason})
