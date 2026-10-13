# ADR-0002: Simple, explainable backorder-risk model

**Status:** accepted

**Context.** Planners and auditors must understand why a date moved. Gradient-boosted models score higher on the public backorder data, but they are hard to defend in a promise dispute.

**Decision.** Logistic regression (scikit-learn, class-balanced) over 8 planner-readable features: coverage ratio, supplier performance gap, potential issue, deck risk, PPAP risk, lead time, past-due flag, and local backorder flag. A pure-Python fallback is included if scikit-learn is unavailable. The top-3 feature contributions are written to the audit log for every line.

**Consequences.** + Every buffer is traceable to named drivers. + The model can be swapped behind `RiskModel.predict/explain`. − It gives up some accuracy. Calibration on real data is required before production (the synthetic base rate is 24%, the real one ~0.7%).
