"""ATP math, risk-aware promise proposal, naive baseline, and the simulated 'actual' fulfillment world."""
from __future__ import annotations
import math, random
from dataclasses import dataclass

TODAY = 0  # all dates are integer days from the order date


@dataclass
class Supply:
    on_hand: float      # national_inv minus reserved near-term demand
    inbound: float      # in_transit_qty
    inbound_eta: int    # days
    replen_eta: int     # days for a fresh replenishment (lead_time weeks)


def supply_for(sku: dict) -> Supply:
    reserved = sku["forecast_3_month"] / 90 * 14  # two weeks of committed backlog
    lt = int(sku["lead_time"] * 7)
    return Supply(on_hand=max(0.0, sku["national_inv"] - reserved), inbound=float(sku["in_transit_qty"]),
                  inbound_eta=max(3, lt // 2), replen_eta=max(7, lt))


def naive_promise(line: dict, s: Supply, transit_p50: float) -> dict:
    """Classic ATP: deterministic supply, no risk buffer, always a full promise."""
    q = line["qty"]; t = math.ceil(transit_p50)
    if s.on_hand >= q:
        day, src = t, "stock"
    elif s.on_hand + s.inbound >= q:
        day, src = s.inbound_eta + t, "inbound"
    else:
        day, src = s.replen_eta + t, "replenishment"
    return {"type": "full", "committed_qty": q, "promise_day": day, "shipments": [(q, day, src)], "confidence": 1.0}


def risk_buffer_days(risk: float, base_days: int) -> int:
    """Pad supply-dependent dates in proportion to risk and the exposure window."""
    return int(math.ceil(risk * (7 + 0.5 * base_days)))


def propose(line: dict, s: Supply, risk: float, transit_p50: float, transit_p80: float,
            substitute: dict | None, horizon: int = 45) -> dict:
    """Risk-aware ATP proposal: full / partial split / alternate date / substitute / escalate."""
    q = line["qty"]; t50, t80 = math.ceil(transit_p50), math.ceil(transit_p80)
    inbound_day = s.inbound_eta + risk_buffer_days(risk, s.inbound_eta)
    replen_day = s.replen_eta + risk_buffer_days(risk, s.replen_eta)
    inbound_conf = round(1 - 0.8 * risk, 3)
    if s.on_hand >= q:
        return {"type": "full", "committed_qty": q, "promise_day": t80, "shipments": [(q, t80, "stock")],
                "confidence": 0.97}
    if substitute and risk >= 0.6 and substitute["on_hand"] >= q:
        return {"type": "substitute", "committed_qty": q, "promise_day": t80, "sub_sku": substitute["sku"],
                "shipments": [(q, t80, "substitute")], "confidence": 0.9}
    if s.on_hand + s.inbound >= q:
        if line["allow_partial"] and s.on_hand >= 0.3 * q:
            now = int(s.on_hand)
            return {"type": "partial_split", "committed_qty": q, "promise_day": inbound_day + t80,
                    "shipments": [(now, t80, "stock"), (q - now, inbound_day + t80, "inbound")],
                    "confidence": inbound_conf}
        return {"type": "full" if risk < 0.3 else "alternate_date", "committed_qty": q,
                "promise_day": inbound_day + t80, "shipments": [(q, inbound_day + t80, "inbound")],
                "confidence": inbound_conf}
    day = replen_day + t80
    if day > 2 * horizon:
        return {"type": "escalate", "committed_qty": 0, "promise_day": day, "shipments": [], "confidence": 0.0,
                "reason": "no feasible supply within 2x horizon"}
    return {"type": "alternate_date", "committed_qty": q, "promise_day": day,
            "shipments": [(q, day, "replenishment")], "confidence": round(1 - 0.9 * risk, 3)}


@dataclass
class World:
    """Hidden realisation of supply + carrier timing for one order line (same for every policy)."""
    backorder_event: bool
    inbound_delay: int
    inbound_fill: float
    replen_delay: int
    transit: float


def realise(line_id: int, sku: dict, transit_pool: list[float], true_risk: float, seed: int) -> World:
    rng = random.Random(seed * 100003 + line_id)
    bo = rng.random() < true_risk
    return World(backorder_event=bo,
                 inbound_delay=rng.randint(7, 28) if bo else rng.randint(0, 3),
                 inbound_fill=rng.uniform(0.3, 0.8) if bo else 1.0,
                 replen_delay=rng.randint(7, 35) if bo else rng.randint(0, 5),
                 transit=rng.choice(transit_pool))


def actual_completion(proposal: dict, s: Supply, w: World) -> list[tuple[float, int]]:
    """Return (qty, actual_delivery_day) per promised shipment under the realised world."""
    out = []
    tr = math.ceil(w.transit)
    leftover = s.on_hand - sum(q for q, _d, src in proposal["shipments"] if src == "stock")
    for qty, _day, src in proposal["shipments"]:
        if src in ("stock", "substitute"):
            out.append((qty, tr))
        elif src == "inbound":
            arrive = s.inbound_eta + w.inbound_delay
            got = s.inbound * w.inbound_fill + max(0.0, leftover)
            if qty <= got + 1e-9:
                out.append((qty, arrive + tr))
            else:  # remainder waits for the next replenishment
                out.append((qty, s.replen_eta + w.replen_delay + tr))
        else:
            out.append((qty, s.replen_eta + w.replen_delay + tr))
    return out
