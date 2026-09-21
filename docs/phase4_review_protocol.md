# Precision review protocol (written BEFORE viewing any sampled flag)

**Who labels:** Claude (an AI), using only the context printed per row. This is NOT a domain-expert or human review
and must not be described as one. It gives a rough precision estimate with wide uncertainty; a billing/coding expert
would likely disagree on some rows. The user asked for best judgment in place of manual review.

**Sampling:** stratified by the *first* detector that fired in the order R5_placeholder > R4_cash_gt_gross >
R3_out_of_range > R2_neg_gt_gross > R1_robust_z > IF-only (Isolation Forest with no rule). 20 random rows per stratum
(all rows if the stratum is smaller), fixed seed. Overall precision = stratum precisions weighted by stratum size.

**Labels**
- **E (likely data error):** (1) a placeholder/sentinel value; or (2) contradicts the same item's own gross/min/max by
  >= 5x in a way a unit-of-measure difference cannot plausibly explain; or (3) >= 20x from the peer median for a plain
  procedure/service/supply description (not an implant, device, transplant, DRG/case rate or unit-priced drug); or
  (4) under $1 for a professional/facility procedure code that is not a drug or supply.
- **R (plausible real price):** extreme but explainable: implant/device/transplant/DRG or bundle case rate, drug or supply
  priced per unit/NDC where unit ambiguity is normal, contradiction with own gross/min/max under 5x, or peer deviation
  under 20x.
- **U (cannot tell):** context insufficient.

**Reporting:** precision lower bound = E / N (U and R count as not-error); upper bound = (E + U) / N. Also reported per
stratum, with Wilson 95% intervals. A row labeled R is "plausible", not "verified correct".
