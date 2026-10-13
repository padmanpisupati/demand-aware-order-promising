# ADR-0003: Risk buffers and promise types

**Status:** accepted

**Decision.**
- Stock-backed lines are promised at carrier p80 transit. Supply-dependent dates are padded by `ceil(risk × (7 + 0.5 × exposure_days))`.
- Promise types, in order: **full** from stock → **substitute** (risk ≥ 0.6 and the substitute has stock) → **partial split** (customer allows splits and stock covers ≥30%) → **full / alternate date** on buffered inbound → **alternate date** on buffered replenishment → **escalate** if the date is beyond 2× the horizon.

**Consequences.** In the synthetic demo the agent cuts late "backorder surprises" by ~60%, but promises ~3–4 days later and has slightly higher absolute date error, because buffered lines often arrive early. That trade (reliability over speed) should be set per customer segment. The buffer coefficient is the KPI lever, and it should be tuned against OTIF and quoted-lead-time targets with sales and customer service involved.
