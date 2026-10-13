"""OPTIONAL adapter to the agentic-governance-control-plane library (`agcp`).

Package 4 is self-contained and never requires `agcp`. If it is installed, `available()` returns True and
`AgcpAuditSink` mirrors every local audit event into an `agcp.AuditLog`, so promise workflows share the
control plane's tamper-evident log. The local `HashChainAudit` stays the source of truth for this demo.
This adapter targets agcp 0.1.x and is deliberately thin; verify against the installed version.
"""
from __future__ import annotations


def available() -> bool:
    try:
        import agcp  # noqa: F401
        return hasattr(agcp, "AuditLog")
    except Exception:
        return False


class AgcpAuditSink:
    """Implements dop.governance.AuditSink by delegating to a local chain plus a best-effort agcp mirror."""
    def __init__(self, local, agcp_log=None):
        self.local = local
        self.agcp_log = agcp_log
        self.mirror_errors = 0

    def record(self, event: str, actor: str, payload: dict) -> dict:
        rec = self.local.record(event, actor, payload)
        if self.agcp_log is not None:
            for name in ("append", "record", "write"):
                fn = getattr(self.agcp_log, name, None)
                if callable(fn):
                    try:
                        fn({"event": event, "actor": actor, "payload": payload})
                        break
                    except TypeError:
                        continue
                    except Exception:
                        self.mirror_errors += 1
                        break
        return rec

    def verify(self) -> bool:
        ok = self.local.verify()
        v = getattr(self.agcp_log, "verify", None)
        if callable(v):
            try:
                res = v()
                ok = ok and (res if isinstance(res, bool) else bool(getattr(res, "ok", res)))
            except Exception:
                return False
        return ok
