#!/usr/bin/env python3
"""
run_pipeline.py
CLI entrypoint: process every raw LAS file in an input directory and write
the required submission curves (VSH, PHIT, PHIE, SW, PERM, PAY_FLAG) as
output LAS files.

Usage:
    python run_pipeline.py --input-dir <raw_las_dir> --output-dir <submission_dir>
"""
import argparse
import glob
import os
import sys
import json
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src import pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--limit", type=int, default=None, help="process only first N wells (debug)")
    ap.add_argument("--report", default=None, help="path to write a JSON QC summary")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(args.input_dir, "*.las")))
    if args.limit:
        files = files[: args.limit]

    summary = {
        "n_wells": len(files),
        "n_honeypot_flagged": 0,
        "n_with_pay": 0,
        "total_pay_footage_ft": 0.0,
        "errors": [],
        "mean_gate_score": 0.0,
        "mean_diagnostic_score": 0.0,
        "n_wells_bad_hole_mitigated": 0,
        "total_phit_samples_mitigated": 0,
        "per_well": [],
    }

    gate_scores = []
    diagnostic_scores = []
    for i, path in enumerate(files):
        well_id = os.path.splitext(os.path.basename(path))[0]
        try:
            result = pipeline.process_well(path)
            if result.errors:
                summary["errors"].append({"well": well_id, "errors": result.errors})
                continue
            pipeline.write_result(result, args.output_dir)

            pay = result.curves["PAY_FLAG"]
            depth = result.curves["DEPTH"]
            step = abs(float(depth[1] - depth[0])) if len(depth) > 1 else 0.5
            footage = float(pay.sum()) * step

            is_hp = result.honeypot_eval["is_honeypot"]
            summary["n_honeypot_flagged"] += int(is_hp)
            summary["n_with_pay"] += int(footage > 0)
            summary["total_pay_footage_ft"] += footage
            gate_scores.append(result.gate_score)
            diagnostic_scores.append(result.diagnostic_score)

            if result.phit_mitigated_samples > 0:
                summary["n_wells_bad_hole_mitigated"] += 1
                summary["total_phit_samples_mitigated"] += result.phit_mitigated_samples

            summary["per_well"].append({
                "well": well_id,
                "is_honeypot": is_hp,
                "honeypot_score": round(result.honeypot_eval["combined_score"], 3),
                "pay_footage_ft": round(footage, 1),
                "gate_score": round(result.gate_score, 4),
                "diagnostic_score": round(result.diagnostic_score, 4),
                "phit_source": result.phit_source,
                "rt_source": result.rt_source,
                "bad_hole_frac": round(result.bad_hole_frac, 4),
                "phit_mitigated_samples": result.phit_mitigated_samples,
                "resolved_curves": result.resolved_aliases,
            })
        except Exception as e:
            summary["errors"].append({"well": well_id, "errors": [str(e), traceback.format_exc()]})

        if (i + 1) % 100 == 0:
            print(f"  processed {i+1}/{len(files)} wells...")

    summary["mean_gate_score"] = sum(gate_scores) / len(gate_scores) if gate_scores else 0.0
    summary["mean_diagnostic_score"] = sum(diagnostic_scores) / len(diagnostic_scores) if diagnostic_scores else 0.0

    print(f"\nProcessed {len(files)} wells -> {args.output_dir}")
    print(f"  Honeypots flagged: {summary['n_honeypot_flagged']} ({summary['n_honeypot_flagged']/len(files)*100:.1f}%)")
    print(f"  Wells with any pay: {summary['n_with_pay']}")
    print(f"  Total net pay footage: {summary['total_pay_footage_ft']:.1f} ft")
    print(f"  Mean internal gate score (A1 proxy, submitted curves only): {summary['mean_gate_score']*100:.2f}/100")
    print(f"  Mean diagnostic score (raw-curve sanity, not part of A1): {summary['mean_diagnostic_score']*100:.2f}/100")
    print(f"  Wells with bad-hole PHIT mitigation: {summary['n_wells_bad_hole_mitigated']} "
          f"({summary['total_phit_samples_mitigated']} samples total)")
    print(f"  Errors: {len(summary['errors'])}")

    if args.report:
        with open(args.report, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"  Full QC report written to {args.report}")


if __name__ == "__main__":
    main()
