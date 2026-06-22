"""
scoring_sim.py
Small reference implementation of the official scoring formulas
(docs/scoring.md), used for two things:

1. Sanity-checking our own intuitions about the formulas (e.g. confirming
   "missing 3 of 30 honeypots costs you 19 points" reproduces exactly).
2. Back-solving: given an observed composite leaderboard score `S` and one
   or more axis scores we can estimate locally (we can compute A1 exactly
   from our own gate QC; A2/A3/A4 require the undisclosed answer key, so
   we can't compute them directly), bound what the remaining axes must be.

This is a diagnostic tool, not part of the submission pipeline.
"""
from __future__ import annotations


def final_score(a1, a2, a3, a4) -> float:
    return (a1 * a2 * a3 * a4) ** 0.25


def axis3_honeypot(catch_fraction: float) -> float:
    """A3 = 100 * (mean(c_i))^2 -- squared penalty on the catch fraction."""
    return 100.0 * (catch_fraction ** 2)


def implied_other_axes_product(observed_S: float, known_axis_value: float) -> float:
    """If S = (A1*A2*A3*A4)^(1/4) and we know one axis, return the product
    of the other three."""
    return (observed_S ** 4) / known_axis_value


def implied_axis_if_equal(observed_S: float, known_axis_value: float, n_unknown=3) -> float:
    """Assuming the unknown axes are roughly equal, what value would each
    have to be to reproduce the observed S given one known axis?"""
    product = implied_other_axes_product(observed_S, known_axis_value)
    return product ** (1.0 / n_unknown)


if __name__ == "__main__":
    print("=== Sanity check against challenge's worked A3 examples ===")
    for miss_frac, label in [(0.0, "catch all"), (3/30, "miss 3/30"), (10/30, "miss 10/30")]:
        catch = 1 - miss_frac
        a3 = axis3_honeypot(catch)
        print(f"  miss {miss_frac:.3f} -> catch {catch:.3f} -> A3={a3:.1f} "
              f"(cost vs perfect: {100-a3:.1f} pts)")

    print("\n=== Diagnosing observed leaderboard score 21.4 ===")
    observed_S = 21.4
    our_internal_A1 = 90.73  # mean internal gate score from docs/qc_report.json (submission-scoped gates + per-sample curve merge)
    product_234 = implied_other_axes_product(observed_S, our_internal_A1)
    each_if_equal = implied_axis_if_equal(observed_S, our_internal_A1)
    print(f"  Observed S = {observed_S}")
    print(f"  Our internal A1 estimate = {our_internal_A1}")
    print(f"  => A2 * A3 * A4 must equal {product_234:.1f}")
    print(f"  => if A2, A3, A4 were all roughly equal, each ~= {each_if_equal:.1f}/100")
    print("\n  Caveats:")
    print("  - Our internal A1 (90.7) is from OUR OWN gate implementation, which may not")
    print("    match the real grader's 25 gates exactly (see docs/scoring.md ambiguity note).")
    print("    If the real A1 is lower than 90.7, A2/A3/A4 would need to be HIGHER than")
    print("    ~13.2 each to reproduce S=21.4 -- i.e. this estimate is a lower bound on")
    print("    how bad A2/A3/A4 are, not an exact figure.")
    print("  - We cannot disambiguate which of A2/A3/A4 is the weakest without the real")
    print("    per-axis breakdown (not shown on the leaderboard UI as of this writing).")
