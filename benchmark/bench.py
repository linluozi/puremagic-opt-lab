#!/usr/bin/env python3
"""Benchmark puremagic's magic-matching path.

The two implementations are selected by --impl-root (baseline upstream
checkout or this repository), so exactly the same corpus and timing code are
used for both.  Raw samples are written to benchmark/raw/<impl>-<scale>-<i>.json.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

SEED = 4321  # synthetic edge cases only; the real corpus is selected deterministically

SCALES = {"small": 150, "medium": 500, "large": 1200}


def cpu_info() -> dict:
    try:
        text = subprocess.run(["lscpu"], capture_output=True, text=True, check=True).stdout
    except Exception:
        return {"model": platform.processor() or "unknown", "lscpu": "unavailable"}
    fields = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return {
        "model": fields.get("Model name", "unknown"),
        "cores": fields.get("CPU(s)", "unknown"),
        "mhz": fields.get("CPU MHz", "unknown"),
        "lscpu": text[:2000],
    }


def mem_info() -> str:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            return "".join(fh.readlines()[:3]).strip()
    except OSError:
        return "unavailable"


def _read(path: str) -> bytes | None:
    try:
        if os.path.getsize(path) > 8 * 1024 * 1024:
            return None
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def corpus(limit: int) -> list[dict]:
    """Deterministic real-file corpus: HTML docs, Python sources, ELF bins, images."""
    patterns = [
        "/usr/share/doc/nodejs/api/*.html",
        "/usr/lib/python3.12/**/*.py",
        "/usr/bin/*",
        "/usr/share/icons/**/*.png",
        "/usr/share/fonts/**/*.ttf",
    ]
    seen: set[str] = set()
    items: list[dict] = []
    for pattern in patterns:
        for path in sorted(glob.glob(pattern, recursive=True)):
            if len(items) >= limit:
                return items
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                continue
            data = _read(path)
            if data is None:
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            items.append({"path": path, "sha256": digest, "bytes": len(data)})
    return items


def time_impl(root: str, api: str, items: list[dict], warmup: int, reps: int) -> list[float]:
    sys.path.insert(0, root)
    import puremagic  # noqa: PLC0415

    payload = [(item, _read(item["path"])) for item in items]
    payload = [(item, data) for item, data in payload if data is not None]
    if len(payload) < len(items):
        raise RuntimeError("corpus changed while reading")
    for _ in range(warmup):
        for item, data in payload:
            if api == "magic":
                puremagic.magic_string(data)
            else:
                try:
                    puremagic.from_file(item["path"])
                except Exception:
                    pass
    samples = []
    for _ in range(reps):
        start = time.perf_counter()
        for item, data in payload:
            if api == "magic":
                puremagic.magic_string(data)
            else:
                try:
                    puremagic.from_file(item["path"])
                except Exception:
                    pass
        samples.append(time.perf_counter() - start)
    return samples


def summarise(samples: list[float]) -> dict:
    med = statistics.median(samples)
    q = statistics.quantiles(samples, n=4) if len(samples) >= 4 else [med, med]
    rel = statistics.pstdev(samples) / med if med else 0.0
    return {
        "median_s": med,
        "p25_s": q[0],
        "p75_s": q[-1],
        "min_s": min(samples),
        "max_s": max(samples),
        "rel_stdev": rel,
        "samples_s": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl-root", required=True)
    parser.add_argument("--impl", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--api", default="magic", choices=["magic", "file"])
    parser.add_argument("--scales", default="small,medium,large")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--test-command", default="")
    parser.add_argument("--test-result", default="")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_dir = out.parent / "raw"
    raw_dir.mkdir(exist_ok=True)

    scales = [name.strip() for name in args.scales.split(",") if name.strip()]
    result = {
        "impl": args.impl,
        "impl_root": os.path.abspath(args.impl_root),
        "api": args.api,
        "seed": SEED,
        "python": sys.version,
        "platform": platform.platform(),
        "cpu": cpu_info(),
        "memory": mem_info(),
        "warmup": args.warmup,
        "reps": args.reps,
        "upstream_tests": {"command": args.test_command, "result": args.test_result},
        "scales": {},
    }

    for name in scales:
        items = corpus(SCALES[name])
        if len(items) < SCALES[name]:
            raise SystemExit(f"corpus too small for {name}: {len(items)} < {SCALES[name]}")
        samples = time_impl(args.impl_root, args.api, items, args.warmup, args.reps)
        for index, seconds in enumerate(samples, start=1):
            raw = {
                "impl": args.impl,
                "scale": name,
                "rep": index,
                "n_files": len(items),
                "n_bytes": sum(item["bytes"] for item in items),
                "seconds": seconds,
                "api": args.api,
                "deepscan": os.getenv("PUREMAGIC_DEEPSCAN", "1") if args.api == "file" else "n/a",
            }
            deep = os.getenv("PUREMAGIC_DEEPSCAN", "1")
            label = "deep" if args.api == "file" and deep != "0" else "nodeep"
            suffix = f"-{label}" if args.api == "file" else ""
            (raw_dir / f"{args.impl}-{args.api}{suffix}-{name}-{index}.json").write_text(
                json.dumps(raw, indent=2) + "\n", encoding="utf-8"
            )
        result["scales"][name] = {
            "n_files": len(items),
            "n_bytes": sum(item["bytes"] for item in items),
            "paths_sha256": hashlib.sha256(
                "".join(item["sha256"] for item in items).encode("ascii")
            ).hexdigest(),
            **summarise(samples),
        }
        print(f"{args.impl} {args.api} {name}: {result['scales'][name]['median_s']:.6f}s")
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
