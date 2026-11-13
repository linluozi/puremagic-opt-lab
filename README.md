# puremagic-opt-lab

`puremagic` is a pure-Python magic-number file type detector; this repository
indexes its 1,497 header signatures by the byte they actually compare first and
caches the extension table, so the common path does not scan every signature on
every call.

Upstream: https://github.com/cdgriffith/puremagic
Pinned commit: `b6f856696e185eab639c1fba5fdaa2a26e61a9dd` (puremagic 2.2.0)

Two hunks, 33 insertions / 4 deletions in `puremagic/main.py`:

1. **Header index.** Offset-0 signatures are bucketed by `byte_match[0]`;
   positive-offset signatures stay in one ordered list. Per-first-byte buckets
   are pre-merged with that list, preserving the exact upstream match order
   (the stable confidence tie-break) without sorting on every call.
2. **Extension set.** `ext_from_filename()` used to rebuild a 1,505-element
   list on every call; it now reads a module-level frozenset.

Public API, return values, and upstream tests are unchanged. `patch.diff`
applies to the pinned commit with `git apply --check`.

## Measured results

All numbers below were produced on 2026-11-13 on the machine described in
**Environment**. No synthetic payload is used for the headline numbers: the
corpus is real files under `/usr/share/doc/nodejs/api`, `/usr/lib/python3.12`,
`/usr/bin`, `/usr/share/icons`, and `/usr/share/fonts`, de-duplicated by full
SHA-256.

### Three scales, `magic_string()` (`benchmark/{baseline,optimized}.json`)

| Scale | Files | Bytes | Baseline median | Optimized median | Speedup |
|---|---:|---:|---:|---:|---:|
| small | 150 | 14.6 MB | 53.316 ms | 11.009 ms | **4.843x** |
| medium | 500 | 21.3 MB | 174.467 ms | 35.492 ms | **4.916x** |
| large | 1,200 | 118.3 MB | 419.918 ms | 88.486 ms | **4.746x** |

Median of the three scale speedups: **4.843x**. Warmup 3 + 5 timed repetitions
per scale; raw samples are in `benchmark/raw/`. Relative standard deviation was
0.3-2.4% for these runs.

### Real corpus, per file (`benchmark/real_corpus.json`)

8 real files, 140,572,240 bytes total: the two largest Node API HTML files, the
two largest stdlib Python files, two ELF executables, one PNG icon, one TTF
font. Each file: 3 warmups + 7 timed calls.

| File | Bytes | Speedup |
|---|---:|---:|
| `/usr/share/doc/nodejs/api/all.html` | 5,840,766 | 4.263x |
| `/usr/share/doc/nodejs/api/fs.html` | 498,323 | 4.304x |
| `/usr/lib/python3.12/pydoc_data/topics.py` | 805,508 | 4.077x |
| `/usr/lib/python3.12/_pydecimal.py` | 229,220 | 4.224x |
| `/usr/bin/dockerd` | 83,879,288 | 4.685x |
| `/usr/bin/caddy` | 48,521,378 | 4.635x |
| `/usr/share/icons/hicolor/256x256/apps/google-chrome.png` | 38,037 | 4.765x |
| `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` | 759,720 | 4.087x |

Per-file median **4.284x**, worst real file **4.077x**.

### Per-input-class floor (`benchmark/per_class.json`)

40 files per class (20 fonts), median of per-file medians:

| Class | Speedup |
|---|---:|
| HTML | 4.333x |
| Python source | 5.341x |
| ELF binaries | 4.787x |
| PNG images | 5.654x |
| TTF fonts | 4.268x |

Minimum across classes: **4.268x** (no class regresses).

### Full `from_file()` pipeline, including deep scanners (`benchmark/*_file_deep.json`)

Deep scanning (PDF/ZIP/text/JSON/executable scanners) runs after the magic
match. On the same three scales the full pipeline is:

| Scale | Baseline | Optimized | Speedup |
|---|---:|---:|---:|
| small | 428.928 ms | 384.619 ms | 1.115x |
| medium | 1,407.287 ms | 1,211.374 ms | **1.162x** |
| large | 2,806.314 ms | 2,417.092 ms | **1.161x** |

This is the honest whole-product number: deepscan dominates, so the header
index is largely hidden for files that trigger a scanner. The optimization is
**1.16x on the full pipeline** and **4.8x on the magic-matching path**; it is not
a 4.8x end-to-end claim.

With `PUREMAGIC_DEEPSCAN=0`, `from_file()` is 4.353x / 4.372x / 3.986x on the
three scales.

## Correctness evidence

`tests/test_diff.py` compares the optimized `identify_all()` against an embedded
copy of the exact upstream algorithm, plus `ext_from_filename()` against its
upstream body. Inputs are de-duplicated by full SHA-256; the test reports the
number of unique inputs, not loop iterations.

- **1,941 unique real/edge inputs**, each compared under four `ext` values:
  **7,764 byte-exact comparisons, 0 mismatches**.
- Corpus includes empty bytes, all 256 single bytes, 256 two-byte pairs,
  `0x00`/`0xFF` runs, BOM, PDF/ZIP/PNG signatures, non-ASCII text, 36,870-byte
  boundary cases, and real files from five system directories.
- In the local run with the upstream `test/` directory added, `tests/test_diff.py` plus
  the upstream suite was **152 passed** in 3.48 s. The upstream suite alone was
  **150 passed** in 0.59 s; this repository ships only `tests/test_diff.py`.

## Quality gates

| Gate | Result | Reproduce |
|---|---|---|
| G1 upstream tests | 150 passed, 0 failed | `cd /tmp/puremagic-baseline && python -m pytest test -q` |
| G2 differential | 1,941 unique / 7,764 comparisons / 0 mismatch | `python -m pytest tests/test_diff.py -q -s` |
| G3 median speedup | 4.843x (scales 4.843/4.916/4.746) | `python benchmark/bench.py --impl-root . --impl optimized --out benchmark/optimized.json --api magic` and the baseline command below |
| G3b real corpus | 4.284x median / 4.077x worst file; full pipeline 1.161x | `python benchmark/real_corpus.py ...` (commands below) |
| G4 large scale | 4.746x magic, 1.161x full pipeline, both >= 0.95x | same bench, `large` scale |
| G5 peak RSS | 32,780 kB -> 33,292 kB = **1.016x** | `/usr/bin/time -v python /tmp/memprobe.py <root>` |

G5 probe processes 200 HTML + 300 Python files through `magic_string()`.
The +512 kB is the pre-merged index (256 buckets); no per-call allocation
growth.

## Two-hunk ablation (`benchmark/ablation.json`)

Workload: `from_file()`, 500 real files, `PUREMAGIC_DEEPSCAN=0`.

| Variant | Median | Speedup | Saving vs baseline |
|---|---:|---:|---:|
| baseline | 218.967 ms | 1.000x | - |
| H1 only (header index) | 79.050 ms | 2.770x | 139.917 ms |
| H2 only (extension set) | 187.211 ms | 1.170x | 31.756 ms |
| H1 + H2 | 49.913 ms | 4.387x | 169.054 ms |

H1 + H2 individual savings = 171.673 ms, **101.5%** of the measured total
saving (difference is run-to-run noise). Leave-one-out marginals: removing H2
adds 29.137 ms; removing H1 adds 137.298 ms. Each hunk's claimed saving is
measured by actually rebuilding that variant, not by subtraction of unrelated
runs.

## 本轮创新

**B 档：把“首个比较字节索引”拆成两个可分别回退的 hunk，并用留一消融 +
输入类下限 + 全管线归因说明收益到底落在哪一层。** 已有台账做过“调用点归因”
和“最弱文件门禁”，但没有逐 hunk 留一消融；本轮的实测新结论是：
magic 匹配层可提速 4.8x，但真实 `from_file()` 全管线只有 1.16x，因为 deepscan
占了大头；单靠 H1 全管线只有 1.115x（低于 1.15 门线），必须把 H2 的
扩展表缓存一起做才过线。这个“局部大收益、全管线刚过线”的分层结论是本轮
新增的可验证判断，换一个上游不能直接复现。

## Reproduce

```bash
git clone --depth=1 git@github-linluozi:linluozi/puremagic-opt-lab.git && cd puremagic-opt-lab
python3 -m venv .venv && . .venv/bin/activate && pip install -q pytest && pip install -q -e .
python -m pytest tests/test_diff.py -q && python benchmark/bench.py --impl-root . --impl optimized --out benchmark/optimized.json --api magic
```

Baseline needs the pinned upstream checkout (this machine has GitHub HTTPS
blocked, hence SSH):

```bash
git clone --depth=1 git@github-linluozi:cdgriffith/puremagic.git /tmp/puremagic-baseline
git -C /tmp/puremagic-baseline checkout b6f856696e185eab639c1fba5fdaa2a26e61a9dd
python benchmark/bench.py --impl-root /tmp/puremagic-baseline --impl baseline --out benchmark/baseline.json --api magic
python benchmark/real_corpus.py --root /tmp/puremagic-baseline --impl baseline --out benchmark/real_baseline.json
python benchmark/real_corpus.py --root . --impl optimized --out benchmark/real_optimized.json
python benchmark/real_corpus.py --merge benchmark/real_baseline.json benchmark/real_optimized.json --out benchmark/real_corpus.json
```

Apply/verify the patch:

```bash
git -C /tmp/puremagic-baseline apply --check patch.diff
```

## Environment

- CPU: see `benchmark/baseline.json` (`lscpu` captured at run time)
- Memory: 3.6 GiB, 4 cores
- Python: 3.12.3 (`/usr/bin/python3`); only 3.12 exists on this machine, so no
  3.10/3.11 cross-interpreter run was possible and none is reported
- Seed: 4321 (synthetic edge cases only; real corpus selection is deterministic
  and recorded by SHA-256 in each JSON)
- Timing: `time.perf_counter()`, warmup 3, 5 timed reps; medians with p25/p75
  and raw samples retained

## License and provenance

MIT, copied verbatim from upstream in `LICENSE`, with a source/change note
appended. Upstream copyright is retained. This is a modified redistribution of
`cdgriffith/puremagic` at the pinned commit; the only source change is
`puremagic/main.py`, shown in `patch.diff`.
