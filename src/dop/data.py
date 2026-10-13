"""Schema-faithful SYNTHETIC generators + loaders for the real public files.

Backorder schema: Kaggle `gowthammiryala/back-order-prediction-dataset`.
Order/delivery timing schema: Kaggle `olistbr/brazilian-ecommerce` (olist_orders_dataset.csv
+ olist_order_items_dataset.csv). No real data is committed; generated rows are SYNTHETIC.
"""
from __future__ import annotations
import csv, math, random
from datetime import datetime, timedelta
from pathlib import Path

BACKORDER_COLUMNS = [
    "sku", "national_inv", "lead_time", "in_transit_qty", "forecast_3_month", "forecast_6_month",
    "forecast_9_month", "sales_1_month", "sales_3_month", "sales_6_month", "sales_9_month",
    "min_bank", "potential_issue", "pieces_past_due", "perf_6_month_avg", "perf_12_month_avg",
    "local_bo_qty", "deck_risk", "oe_constraint", "ppap_risk", "stop_auto_buy", "rev_stop",
    "went_on_backorder",
]
YESNO = ["potential_issue", "deck_risk", "oe_constraint", "ppap_risk", "stop_auto_buy", "rev_stop", "went_on_backorder"]
OLIST_COLUMNS = ["order_id", "order_status", "order_purchase_timestamp", "order_approved_at",
                 "order_delivered_carrier_date", "order_delivered_customer_date",
                 "order_estimated_delivery_date", "price"]


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def latent_supply_risk(r: dict) -> float:
    """Hidden 'true' risk process of the synthetic world (NOT visible to the model)."""
    cover = (r["national_inv"] + r["in_transit_qty"]) / max(1.0, r["forecast_3_month"])
    z = (-2.2 - 1.6 * min(cover, 3) + 3.0 * (1 - r["perf_6_month_avg"])
         + 0.9 * (r["potential_issue"] == "Yes") + 0.6 * (r["deck_risk"] == "Yes")
         + 0.5 * (r["ppap_risk"] == "Yes") + 0.04 * min(r["lead_time"], 20)
         + 0.8 * (r["pieces_past_due"] > 0) + 0.7 * (r["local_bo_qty"] > 0) + 2.0)
    return _sig(z)


def generate_backorders(n: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        f3 = max(0, int(rng.lognormvariate(3.0, 1.1)))
        inv = max(0, int(f3 * rng.uniform(0.0, 2.5) + rng.gauss(0, 5)))
        perf = round(min(1.0, max(0.05, rng.betavariate(8, 1.5))), 2)
        r = {
            "sku": f"SKU{1000000 + i}", "national_inv": inv, "lead_time": rng.choice([2, 4, 8, 8, 8, 12, 16]),
            "in_transit_qty": int(f3 * rng.uniform(0, 1.0)) if rng.random() < 0.6 else 0,
            "forecast_3_month": f3, "forecast_6_month": int(f3 * rng.uniform(1.8, 2.2)),
            "forecast_9_month": int(f3 * rng.uniform(2.7, 3.3)),
            "sales_1_month": int(f3 / 3 * rng.uniform(0.6, 1.4)), "sales_3_month": int(f3 * rng.uniform(0.7, 1.3)),
            "sales_6_month": int(f3 * 2 * rng.uniform(0.7, 1.3)), "sales_9_month": int(f3 * 3 * rng.uniform(0.7, 1.3)),
            "min_bank": int(f3 / 6 * rng.uniform(0, 1.5)),
            "potential_issue": "Yes" if rng.random() < 0.05 else "No",
            "pieces_past_due": int(rng.expovariate(0.2)) if rng.random() < 0.08 else 0,
            "perf_6_month_avg": perf, "perf_12_month_avg": round(min(1.0, perf + rng.gauss(0, 0.04)), 2),
            "local_bo_qty": int(rng.expovariate(0.3)) if rng.random() < 0.07 else 0,
            "deck_risk": "Yes" if rng.random() < 0.2 else "No", "oe_constraint": "Yes" if rng.random() < 0.02 else "No",
            "ppap_risk": "Yes" if rng.random() < 0.12 else "No", "stop_auto_buy": "No" if rng.random() < 0.96 else "Yes",
            "rev_stop": "No",
        }
        r["went_on_backorder"] = "Yes" if rng.random() < latent_supply_risk(r) else "No"
        rows.append(r)
    return rows


def generate_olist_orders(n: int, seed: int = 11) -> list[dict]:
    rng = random.Random(seed)
    base = datetime(2017, 6, 1)
    out = []
    fmt = "%Y-%m-%d %H:%M:%S"
    for i in range(n):
        p = base + timedelta(minutes=rng.randint(0, 60 * 24 * 365))
        a = p + timedelta(hours=rng.uniform(0.2, 30))
        c = a + timedelta(days=rng.uniform(0.5, 4))
        d = c + timedelta(days=max(1.0, rng.lognormvariate(2.0, 0.55)))
        e = p + timedelta(days=rng.choice([15, 20, 24, 28, 32]))
        out.append({"order_id": f"synthetic{i:06d}", "order_status": "delivered",
                    "order_purchase_timestamp": p.strftime(fmt), "order_approved_at": a.strftime(fmt),
                    "order_delivered_carrier_date": c.strftime(fmt), "order_delivered_customer_date": d.strftime(fmt),
                    "order_estimated_delivery_date": e.strftime("%Y-%m-%d 00:00:00"),
                    "price": round(rng.lognormvariate(4.3, 0.9), 2)})
    return out


def _num(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def load_backorders(path: str | Path) -> list[dict]:
    """Load the real Kaggle file (e.g. Kaggle_Training_Dataset_v2.csv) or a committed sample."""
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if not r.get("sku") or r.get("national_inv") in (None, ""):
                continue  # real file ends with a summary row
            row = {k: r[k] for k in YESNO if k in r}
            for k in BACKORDER_COLUMNS:
                if k not in YESNO and k != "sku":
                    x = _num(r.get(k))
                    row[k] = 0.0 if math.isnan(x) else x
            row["sku"] = r["sku"]
            if row["perf_6_month_avg"] < 0:  # real data uses -99 for missing
                row["perf_6_month_avg"] = 0.8
            if row["perf_12_month_avg"] < 0:
                row["perf_12_month_avg"] = 0.8
            rows.append(row)
    return rows


def load_olist_orders(path: str | Path) -> list[dict]:
    with open(path, newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("order_delivered_customer_date")]


def transit_days(orders: list[dict]) -> list[float]:
    """Carrier handover -> customer delivery, in days (Olist timing semantics)."""
    fmt = "%Y-%m-%d %H:%M:%S"
    out = []
    for o in orders:
        try:
            c = datetime.strptime(o["order_delivered_carrier_date"], fmt)
            d = datetime.strptime(o["order_delivered_customer_date"], fmt)
        except (KeyError, ValueError, TypeError):
            continue
        if d > c:
            out.append((d - c).total_seconds() / 86400)
    return sorted(out)


def quantile(xs: list[float], q: float) -> float:
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def write_csv(rows: list[dict], path: str | Path, cols: list[str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
