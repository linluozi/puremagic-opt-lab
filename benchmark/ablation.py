#!/usr/bin/env python3
"""Run leave-one-hunk ablation variants through the same bench.py workload.

Example (build the two variants first):
  git clone --depth=1 <upstream> /tmp/v-h1 && git -C /tmp/v-h1 apply benchmark/variants/h1_only.patch
  git clone --depth=1 <upstream> /tmp/v-h2 && git -C /tmp/v-h2 apply benchmark/variants/h2_only.patch
  python benchmark/ablation.py --variant baseline=/tmp/upstream --variant h1_only=/tmp/v-h1 \
      --variant h2_only=/tmp/v-h2 --variant full=. --out benchmark/ablation.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", action="append", required=True, help="name=root")
    parser.add_argument("--out", default="benchmark/ablation.json")
    parser.add_argument("--reps", type=int, default=5)
    args = parser.parse_args()

    medians = {}
    env = dict(os.environ, PUREMAGIC_DEEPSCAN="0")
    for spec in args.variant:
        name, root = spec.split("=", 1)
        tmp = Path(f"/tmp/ablation-{name}.json")
        subprocess.run(
            [
                sys.executable,
                "benchmark/bench.py",
                "--impl-root",
                root,
                "--impl",
                name,
                "--out",
                str(tmp),
                "--api",
                "file",
                "--scales",
                "medium",
                "--reps",
                str(args.reps),
            ],
            check=True,
            env=env,
        )
        medians[name] = json.loads(tmp.read_text())["scales"]["medium"]["median_s"]

    baseline = medians["baseline"]
    total = baseline - medians["full"]
    h1 = baseline - medians["h1_only"]
    h2 = baseline - medians["h2_only"]
    result = {
        "workload": "from_file, 500 real files, PUREMAGIC_DEEPSCAN=0",
        "medians_s": medians,
        "speedups": {name: baseline / value for name, value in medians.items()},
        "savings_s": {"h1": h1, "h2": h2, "total": total, "sum_h1_h2": h1 + h2},
        "share_of_total": {"h1": h1 / total, "h2": h2 / total, "sum": (h1 + h2) / total},
        "leave_one_out": {
            "h2_marginal_s": medians["h1_only"] - medians["full"],
            "h1_marginal_s": medians["h2_only"] - medians["full"],
        },
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["share_of_total"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
