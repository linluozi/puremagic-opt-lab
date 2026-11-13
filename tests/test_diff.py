"""Differential test: optimized identify_all() vs the exact upstream algorithm.

The reference oracle below is the upstream identify_all() body (MIT, see LICENSE).
Samples are de-duplicated by full SHA-256, so the reported number is the number
of independent inputs, not loop iterations.
"""
from __future__ import annotations

import glob
import hashlib
import os
import random

import puremagic
from puremagic import main as m

SEED = 4321


def baseline_identify_all(header: bytes, footer: bytes, ext=None):
    matches = []
    for magic_row in m.magic_header_array:
        start = magic_row.offset
        end = magic_row.offset + len(magic_row.byte_match)
        if end > len(header):
            continue
        if header[start:end] == magic_row.byte_match:
            matches.append(magic_row)

    for magic_row in m.magic_footer_array:
        start = magic_row.offset
        end = magic_row.offset + len(magic_row.byte_match)
        match_area = footer[start:end] if end != 0 else footer[start:]
        if match_area == magic_row.byte_match:
            matches.append(magic_row)

    new_matches = set()
    for matched in matches:
        if matched.byte_match in m.multi_part_dict:
            for magic_row in m.multi_part_dict[matched.byte_match]:
                start = magic_row.offset
                end = magic_row.offset + len(magic_row.byte_match)
                if magic_row.offset < 0:
                    match_area = footer[start:end] if end != 0 else footer[start:]
                    if match_area == magic_row.byte_match:
                        new_matches.add(
                            m.PureMagic(
                                byte_match=matched.byte_match + magic_row.byte_match,
                                offset=magic_row.offset,
                                extension=magic_row.extension,
                                mime_type=magic_row.mime_type,
                                name=magic_row.name,
                            )
                        )
                else:
                    if end > len(header):
                        continue
                    if header[start:end] == magic_row.byte_match:
                        new_matches.add(
                            m.PureMagic(
                                byte_match=header[matched.offset : end],
                                offset=magic_row.offset,
                                extension=magic_row.extension,
                                mime_type=magic_row.mime_type,
                                name=magic_row.name,
                            )
                        )

    matches.extend(list(new_matches))
    return m.determine_confidence(matches, ext)


def baseline_ext_from_filename(filename) -> str:
    try:
        base, ext = os.path.basename(filename).lower().rsplit(".", 1)
    except ValueError:
        return ""
    ext = f".{ext}"
    all_exts = [x.extension for x in m.chain(m.magic_header_array, m.magic_footer_array)]
    if base[-4:].startswith("."):
        long_ext = base[-4:] + ext
        if long_ext in all_exts:
            return long_ext
    return ext


def _read(path: str) -> bytes | None:
    try:
        if os.path.getsize(path) > 8 * 1024 * 1024:
            return None
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def corpus() -> list[bytes]:
    seen: set[str] = set()
    samples: list[bytes] = []

    def add(data: bytes) -> None:
        digest = hashlib.sha256(data).hexdigest()
        if digest not in seen:
            seen.add(digest)
            samples.append(data)

    patterns = [
        "/usr/share/doc/nodejs/api/*.html",
        "/usr/lib/python3.12/**/*.py",
        "/usr/bin/*",
        "/usr/share/icons/**/*.png",
        "/usr/share/fonts/**/*.ttf",
    ]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern, recursive=True)):
            if len(samples) >= 1400:
                break
            data = _read(path)
            if data:
                add(data)

    rng = random.Random(SEED)
    for value in range(256):
        add(bytes([value]))
    for value in range(256):
        add(bytes([value, 255 - value]))
    add(b"")
    add(bytes(range(256)))
    add(b"\xef\xbb\xbf")
    add(b"\x00" * 4096)
    add(b"\xff" * 4096)
    for size in (2, 3, 7, 16, 63, 64, 65, 127, 128, 129, 1024, 4096, 36870, 36871):
        add(rng.randbytes(size))
    for size in (8, 32, 128, 1024, 8192):
        add(rng.randbytes(size).hex().encode("ascii"))
    add("中文 HTML 文件".encode("utf-8"))
    add(b"<!DOCTYPE html><html><body>hello</body></html>")
    add(b"%PDF-1.7\n" + b"x" * 500)
    add(b"PK\x03\x04" + b"\x00" * 64)
    add(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    return samples


def test_differential_1000_plus_unique_samples() -> None:
    samples = corpus()
    assert len(samples) >= 1000, f"only {len(samples)} unique samples"
    checked = 0
    for data in samples:
        header, footer = m.string_details(data)
        for ext in (None, ".html", ".py", ".png"):
            expected = [tuple(row) for row in baseline_identify_all(header, footer, ext)]
            actual = [tuple(row) for row in m.identify_all(header, footer, ext)]
            assert actual == expected, (data[:32].hex(), ext, expected[:3], actual[:3])
            checked += 1
    assert checked >= 1000
    print(f"unique inputs={len(samples)} comparisons={checked} mismatches=0")


def test_extension_lookup_matches_upstream() -> None:
    names = [
        "a.tar.gz",
        "readme.md",
        "x.PDF",
        "archive.tar.bz2",
        "noext",
        ".hidden",
        "file.",
        "UPPER.TXT",
        "a.b.c.d",
        "",
    ]
    names += sorted(glob.glob("/usr/share/doc/nodejs/api/*.html"))[:100]
    names += sorted(glob.glob("/usr/lib/python3.12/*.py"))[:100]
    for name in names:
        assert puremagic.ext_from_filename(name) == baseline_ext_from_filename(name), name
