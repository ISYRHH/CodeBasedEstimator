#!/usr/bin/env python3
"""Rebuild public HARE tail columns from an unmodified reference package.

Usage: python tools/export_hare_tail.py --source-root SOURCE --output FILE
Only the four implemented KR instances are exported. No KEM randomness,
private key, audit library, cost estimator, or third-party Python dependency
is needed. The C compiler is selected by CC (default: cc).
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


INSTANCES = ((128, "HARE-2"), (256, "HARE-5"),
             (384, "HARE-7"), (512, "HARE-9"))
FLAGS = ("-std=c99", "-O2", "-Wall", "-Wextra", "-Wpedantic",
         "-DHARE_SYMMETRIC_MODE_B", "-DHARE_BACKEND_KR=1")
CORE = Path("Implementations/_shared/hare_core")
API = Path("Implementations/_shared/api_pkc")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(root):
    """Hash every C/header input under the supplied root using relative names."""
    paths = sorted(p for p in root.rglob("*") if p.suffix in (".c", ".h") and p.is_file())
    if not paths:
        raise ValueError("source root contains no C/header files")
    for path in paths:
        if not path.resolve().is_relative_to(root):
            raise ValueError("source C/header resolves outside the supplied source root")
    return {p.relative_to(root).as_posix(): digest(p) for p in paths}


def export(source_root, output):
    source_root = source_root.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(source_root):
        raise ValueError("output must be outside the frozen source root")
    exporter = Path(__file__).with_name("hare_tail_export.c")
    exporter_hash = digest(exporter)
    before = source_manifest(source_root)
    compiler = shlex.split(os.environ.get("CC", "cc"))
    if not compiler:
        raise ValueError("CC must name a C compiler")
    version = subprocess.run(compiler + ["--version"], check=True,
                             capture_output=True, text=True).stdout.splitlines()
    common_sources = sorted((source_root / CORE / "common").glob("*.c"))
    reference_sources = sorted((source_root / CORE / "ref").glob("*.c"))
    if not common_sources or not reference_sources:
        raise ValueError("missing the reference common/ref C sources")
    sources = common_sources + reference_sources + [source_root / API / name
                                                    for name in ("auxfunc.c", "drng.c")]
    relative_sources = [p.relative_to(source_root).as_posix() for p in sources]
    if any(name not in before for name in relative_sources):
        raise ValueError("a required compiled source is absent from the source manifest")

    entries, builds = [], []
    try:
        with tempfile.TemporaryDirectory(prefix="hare-tail-export-") as temporary:
            for level, name in INSTANCES:
                instance = Path("Implementations/Reference_Implementation") / f"HARE-{level}" / "kr"
                includes = [instance, CORE / "common", CORE / "ref", API]
                if (instance / "parameters.h").as_posix() not in before:
                    raise ValueError(f"missing reference parameters for {name}")
                binary = Path(temporary) / f"hare-tail-{level}"
                command = compiler + list(FLAGS)
                for directory in includes:
                    command += ["-I", directory.as_posix()]
                command += [str(exporter), *relative_sources, "-o", str(binary)]
                subprocess.run(command, cwd=source_root, check=True, capture_output=True, text=True)
                run = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
                entry = json.loads(run.stdout)
                columns = entry["message_columns"]
                width = entry["tail_bits"]
                if (type(width) is not int or not 0 < width < 64 or
                        len(columns) != entry["message_bits"] or
                        any(type(value) is not int or not 0 <= value < (1 << width)
                            for value in columns) or
                        entry["tail_start"] + width != entry["encoded_bits"] or
                        entry["encoded_bits"] > entry["ring_length"]):
                    raise ValueError(f"invalid exported columns for {name}")
                entries.append({"parameter_set": name, **entry})
                builds.append({"parameter_set": name, "reference_instance": instance.as_posix(),
                               "include_directories": [p.as_posix() for p in includes]})
    finally:
        if source_manifest(source_root) != before:
            raise RuntimeError("reference C/header inputs changed during export; output was not written")
        if digest(exporter) != exporter_hash:
            raise RuntimeError("C exporter changed during export; output was not written")

    payload = {
        "schema": "hare-tail-generators-v1",
        "source_files_sha256": before,
        "generator_export_sha256": exporter_hash,
        "export_script_sha256": digest(Path(__file__)),
        "provenance": {
            "implementation": "Reference_Implementation; submitted KR instances",
            "compiler": Path(compiler[0]).name,
            "compiler_version": version[0] if version else "unavailable",
            "compiler_flags": list(FLAGS),
            "compiled_sources": relative_sources,
            "builds": builds,
            "bit_order": "message bit j: byte j//8, LSB j%8; tail bit i: coordinate tail_start+i",
            "unit_message_columns_exported": True,
            "zero_input_checked": True,
            "combination_checks_per_instance": 16,
            "source_files_unchanged": True,
            "not_exported": ["HARE-1", "HARE-3"],
            "not_exported_reason": "The supplied frozen package has no matching implemented instances.",
        },
        "entries": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                      encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path,
                        help="root of the frozen Implementations and Test_Vectors package")
    parser.add_argument("--output", required=True, type=Path, help="JSON file outside the frozen source root")
    args = parser.parse_args()
    try:
        result = export(args.source_root, args.output)
    except subprocess.CalledProcessError as error:
        parser.exit(1, f"reference compiler/exporter failed:\n{error.stderr or error.stdout or error}\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"export failed: {error}\n")
    for row in result["entries"]:
        print(f"{row['parameter_set']}: {row['message_bits']} columns, {row['tail_bits']} tail bits")


if __name__ == "__main__":
    main()
