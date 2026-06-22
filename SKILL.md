---
name: petrophysical-pay-zone-identification
description: >
  Build/iterate an agentic pipeline that ingests raw, unconditioned LAS well
  log files and produces a complete petrophysical curve suite (VSH, PHIT,
  PHIE, SW, PERM, PAY_FLAG) per well, screening out wells whose raw
  measurements contain baked-in physics violations ("honeypots"). Use when
  the task involves raw LAS files, well-log curve calculation, petrophysical
  cutoffs, or pay-zone / net-pay identification.
---

# Petrophysical Pay-Zone Identification Workflow

This skill documents the repeatable workflow used to build and iterate this
challenge submission. It is meant to be re-runnable: pointed at a new batch
of raw LAS files, or re-invoked after a leaderboard score comes back, it
should produce the same disciplined sequence of steps rather than ad hoc
changes.

## When to use this

- A fresh batch of raw LAS files needs a full petrophysical suite computed
  from scratch, with no labeled training data available.
- A leaderboard/scoring axis came back weak and the workflow needs to be
  re-audited and adjusted (e.g. honeypot precision/recall, Axis-4 curve
  accuracy, gate compliance).
- A new vintage of LAS files appears with mnemonics not yet in the alias
  table.

## Workflow steps

1. **Audit before coding.** Never assume curve names, units, or null
   conventions. Parse the raw headers across the *entire* dataset (not a
   sample) and tabulate: every distinct curve mnemonic and its unit
   variants, the NULL value convention, STEP/sampling interval, depth
   range, and curves-per-well distribution. This dataset turned out to have
   217 distinct mnemonics across 800 wells purely from vintage/vendor
   variation in something as simple as "gamma ray" -- skipping this step
   and hardcoding `GR`/`RHOB`/`NPHI` would silently drop most wells.

2. **Build a mnemonic resolver as its own module**, separate from the
   physics. It should: (a) match known aliases first, (b) fall back to a
   conservative regex/heuristic for unseen mnemonics, (c) explicitly
   blocklist look-alike non-petrophysical channels (drilling/trajectory
   curves), and (d) record *which* alias was used per well/curve for
   auditability -- never silently guess without leaving a trace.

3. **Implement petrophysics as small, individually testable functions**
   (one per curve: VSH, PHIT, PHIE, SW, PERM), each taking/returning plain
   arrays. Use standard, named, textbook methods (Larionov, Archie, Timur,
   Wyllie) rather than inventing new transforms -- the challenge explicitly
   rewards "competent petrophysicist accuracy," not novelty. Always
   implement a fallback chain when a primary curve is missing (e.g. density
   -> sonic -> neutron for porosity; deep -> medium -> shallow resistivity
   for Rt), and prefer leaving a value as NaN over fabricating a plausible-
   looking default when no input curve exists at all. Implement that
   fallback **per depth sample**, not as a single whole-well source pick --
   a well's curve coverage is often complementary (density logs one
   interval, sonic another) rather than redundant, and a gate-compliance
   axis that fails NaN samples rewards closing every real gap you can
   (`pp.merge_per_sample` in this codebase).

4. **Treat "honeypot" wells as an evidence-based classification problem,
   not a vibe.** A whole-well rejection should be backed by specific,
   physically-justified evidence (raw values outside what's possible for
   real rock, cross-method disagreement between independent curves
   measuring the same property, or a derived quantity blowing outside its
   valid range before any clipping is applied). Flagging zero pay
   everywhere as a shortcut is a trap -- the scoring's geometric mean zeroes
   the entire score if the pay-accuracy axis is zero.

5. **Run an internal gate/QC pass before submitting**, even though the
   real grader's exact gate list is undisclosed. Scope it to exactly what
   the grader can possibly see: the columns actually written to the
   output file, never the pipeline's internal/raw curves -- a gate on a
   curve you don't submit can't be a real gate, and would unfairly punish
   wells (especially honeypots) whose raw measurements are intentionally
   broken by the challenge design, conflating that with Axis 1. Keep any
   raw-curve sanity checks as a clearly separate, excluded diagnostic
   pass for catching your own pipeline bugs. Score every well against the
   submission-scoped gates and treat a low score as a bug report pointing
   at a specific well/curve to go investigate -- not noise.

6. **Validate end to end on the full dataset before declaring done.** A
   pipeline that works on 10 wells but throws on well #347 because of a
   ragged data row or an unseen mnemonic is not done. Check: zero
   exceptions, every well has all required curves populated and non-fully-
   NaN, and headline stats (honeypot rate, mean pay footage, mean gate
   score) are sane given what's known about the dataset (e.g. ~25% true
   honeypot rate here).

7. **Document what's tuned vs. guessed.** Every cutoff/threshold/constant
   that hasn't been validated against real feedback (leaderboard score,
   labeled data, etc.) should be named explicitly in the README's
   "Status & Next Steps" section, with a plan for which axis it affects and
   how to use the next round of feedback to adjust it.

8. **Check reference skill libraries for techniques worth adapting, but
   verify before porting.** When a reference repo is pointed to (e.g. a
   public oil & gas skills library), read its actual code, not just its
   `SKILL.md` spec prose -- specs often restate the same textbook formulas
   you already have without adding anything new. Adopt only what's both
   concrete and physically justified for *this* dataset (e.g. caliper-based
   bad-hole detection -> per-sample density-porosity fallback in
   `petrophysics.py::detect_bad_hole`), and re-validate end to end (task 6)
   after adopting it to confirm no regression.

## Inputs this skill expects

- A directory of raw `.las` files (LAS 2.0, one line per depth step).
- No labels, no answer key, no starter notebook -- by design.

## Outputs this skill produces

- One `.las` file per input well containing `DEPTH, VSH, PHIT, PHIE, SW,
  PERM, PAY_FLAG`.
- A JSON QC report (per-well honeypot score/flag, internal gate score,
  curve-source provenance) for regression-checking future iterations.

## Harness / model used to build this

Built using Claude (Claude Sonnet 4.6) in Anthropic's Cowork agent harness,
with direct file-system and sandboxed-shell access to the raw LAS dataset
(no internet access to install third-party LAS libraries during
development, which is why `src/las_io.py` is a from-scratch, dependency-
free parser rather than a wrapper around `lasio`).
