#!/usr/bin/env python3
"""Per-input-class timings for one implementation, plus a merge mode."""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def groups() -> dict[str, list[str]]:
    bins = [p for p in sorted(glob.glob("/usr/bin/*")) if os.path.isfile(p) and _size(p) > 10_000]
    return {
        "html": sorted(glob.glob("/usr/share/doc/nodejs/api/*.html"))[:40],
        "python": sorted(glob.glob("/usr/lib/python3.12/**/*.py", recursive=True))[:40],
        "elf": bins[:40],
        "png": sorted(glob.glob("/usr/share/icons/**/*.png", recursive=True))[:40],
        "font": sorted(glob.glob("/usr/share/fonts/**/*.ttf", recursive=True))[:20],
    }


def run(root: str, impl: str, reps: int, warmup: int) -> dict:
    sys.path.insert(0, root)
    import puremagic  # noqa: PLC0415

    out = {"impl": impl, "root": os.path.abspath(root), "api": "magic_string", "classes": {}}
    for cls, paths in groups().items():
        rows = []
        for path in paths:
            with open(path, "rb") as fh:
                data = fh.read()
            for _ in range(warmup):
                puremagic.magic_string(data)
            samples = []
            for _ in range(reps):
                start = time.perf_counter()
                puremagic.magic_string(data)
                samples.append(time.perf_counter() - start)
            rows.append(
                {
                    "path": path,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                    "median_s": statistics.median(samples),
                }
            )
        out["classes"][cls] = {
            "n": len(rows),
            "median_s": statistics.median([row["median_s"] for row in rows]),
            "files": rows,
        }
    return out


def merge(base_path: str, opt_path: str) -> dict:
    base = json.loads(Path(base_path).read_text())
    opt = json.loads(Path(opt_path).read_text())
    out = {"api": "magic_string", "classes": {}}
    for cls in base["classes"]:
        b = base["classes"][cls]["median_s"]
        o = opt["classes"][cls]["median_s"]
        out["classes"][cls] = {
            "n": base["classes"][cls]["n"],
            "baseline_s": b,
            "optimized_s": o,
            "speedup": b / o,
            "paths": [row["path"] for row in base["classes"][cls]["files"]],
            "sha256": [row["sha256"] for row in base["classes"][cls]["files"]],
        }
    out["min_speedup"] = min(v["speedup"] for v in out["classes"].values())
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    parser.add_argument("--impl")
    parser.add_argument("--out", required=True)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--merge", nargs=2)
    args = parser.parse_args()
    if args.merge:
        result = merge(*args.merge)
    else:
        if not args.root or not args.impl:
            parser.error("--root and --impl are required without --merge")
        result = run(args.root, args.impl, args.reps, args.warmup)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
