#!/usr/bin/env python3
"""Per-file real-corpus timings for one implementation.

Usage:
  python benchmark/real_corpus.py --root /tmp/puremagic-baseline --impl baseline --out benchmark/real_baseline.json
  python benchmark/real_corpus.py --root . --impl optimized --out benchmark/real_optimized.json
  python benchmark/real_corpus.py --merge benchmark/real_baseline.json benchmark/real_optimized.json --out benchmark/real_corpus.json
"""
from __future__ import annotations

import argparse
import glob
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


def pick_files() -> list[str]:
    html = sorted(glob.glob("/usr/share/doc/nodejs/api/*.html"), key=_size, reverse=True)[:2]
    py = sorted(glob.glob("/usr/lib/python3.12/**/*.py", recursive=True), key=_size, reverse=True)[:2]
    bins = sorted(glob.glob("/usr/bin/*"), key=_size, reverse=True)
    bins = [p for p in bins if os.path.isfile(p) and _size(p) > 100_000][:2]
    png = sorted(glob.glob("/usr/share/icons/**/*.png", recursive=True), key=_size, reverse=True)[:1]
    ttf = sorted(glob.glob("/usr/share/fonts/**/*.ttf", recursive=True), key=_size, reverse=True)[:1]
    files = html + py + bins + png + ttf
    total = sum(os.path.getsize(p) for p in files)
    if len(files) < 4 or total < 2 * 1024 * 1024:
        raise SystemExit(f"real corpus too small: {len(files)} files, {total} bytes")
    return files


def run(root: str, impl: str, reps: int, warmup: int) -> dict:
    sys.path.insert(0, root)
    import puremagic  # noqa: PLC0415

    rows = []
    for path in pick_files():
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
                "bytes": len(data),
                "median_s": statistics.median(samples),
                "samples_s": samples,
            }
        )
    return {
        "impl": impl,
        "root": os.path.abspath(root),
        "api": "magic_string",
        "python": sys.version,
        "files": rows,
        "total_bytes": sum(row["bytes"] for row in rows),
    }


def merge(baseline_path: str, optimized_path: str) -> dict:
    base = json.loads(Path(baseline_path).read_text())
    opt = json.loads(Path(optimized_path).read_text())
    b = {row["path"]: row for row in base["files"]}
    o = {row["path"]: row for row in opt["files"]}
    rows = []
    for path in b:
        ratio = b[path]["median_s"] / o[path]["median_s"]
        rows.append(
            {
                "path": path,
                "bytes": b[path]["bytes"],
                "baseline_s": b[path]["median_s"],
                "optimized_s": o[path]["median_s"],
                "speedup": ratio,
            }
        )
    ratios = [row["speedup"] for row in rows]
    return {
        "api": "magic_string",
        "total_bytes": sum(row["bytes"] for row in rows),
        "n_files": len(rows),
        "median_speedup": statistics.median(ratios),
        "min_speedup": min(ratios),
        "max_speedup": max(ratios),
        "files": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    parser.add_argument("--impl", choices=["baseline", "optimized"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--reps", type=int, default=7)
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
    if args.merge:
        print(
            f"real corpus: n={result['n_files']} bytes={result['total_bytes']} "
            f"median={result['median_speedup']:.4f} min={result['min_speedup']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
