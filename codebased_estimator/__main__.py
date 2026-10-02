"""Plain tables or JSON, with no service or UI dependency."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import sys
from pathlib import Path

from . import AttackInstance, DemoScheme, Options, estimate


def _table(reports):
    print("Costs are log2 in the units shown for each row; '--' means unavailable.")
    print("Each row estimates one decoding route, not overall scheme security.")
    for report in reports:
        i = report.instance
        print(f"\n{i.name} | {i.goal} | {i.problem.kind} {i.problem.parameters}")
        print(f"  {i.route}")
        print(f"  tags={list(i.tags)}; targets={i.targets}")
        print(f"  {'algorithm':24} {'model':10} {'status':17} {'time':>9} {'memory':>9}  units (time / memory); parameters")
        for r in report.results:
            time = "--" if r.time_log2 is None else f"{r.time_log2:.3f}"
            memory = "--" if r.memory_log2 is None else f"{r.memory_log2:.3f}"
            print(f"  {r.algorithm:24} {r.model:10} {r.status:17} {time:>9} {memory:>9}  {r.time_unit} / {r.memory_unit}; {r.parameters}")
            if r.reason:
                print(f"    {r.reason}")
        for family, conclusion in report.conclusions.items():
            if conclusion.best:
                for best in conclusion.best:
                    print(f"  Best {family}: {best.algorithm} | "
                          f"time=2^{best.time_log2:.3f} {best.time_unit}; "
                          f"memory=2^{best.memory_log2:.3f} {best.memory_unit}; "
                          f"parameters={best.parameters}")
            else:
                print(f"  Best {family}: -- ({conclusion.status})")
            print(f"    {conclusion.reason}")
        for note in i.assumptions:
            print(f"  Assumption: {note}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run small synthetic key/msg examples")
    run = commands.add_parser("estimate", help="estimate a single JSON attack instance")
    run.add_argument("input", type=Path)
    run.add_argument("--doom", choices=("qccf", "qcsd"), help="DOOM mechanism tag, interpreted inside each algorithm")
    run.add_argument("--targets", type=int, help="usable candidate/target count, interpreted according to the DOOM tag")
    demo.set_defaults(doom=None, targets=None)
    for command in (demo, run):
        command.add_argument("--classical-algorithms", nargs="*", help="classical names; empty disables classical estimates")
        command.add_argument("--quantum-algorithms", nargs="*", help="quantum names, e.g. QPrange QSS 'QMMT+'; empty disables quantum estimates")
        command.add_argument("--memory-bound", type=float, help="maximum log2(memory in bits)")
        command.add_argument("--json", action="store_true", help="emit reproducible result records")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            adapter = DemoScheme()
            selections = {
                "hamming": ("Prange", "Stern", "Dumer"),
                "qary": ("Prange", "Stern", "LeeBrickell"),
                "rank": ("GRS", "MaxMinors", "SupportMinors"),
            }
            jobs = [(instance, names, ("QPrange", "QSS", "QMMT+") if family == "hamming" else ())
                    for family, names in selections.items()
                    for goal in ("key_recovery", "msg_recovery")
                    for instance in adapter.instances(family, goal)]
        else:
            try:
                data = json.loads(args.input.read_text(encoding="utf-8"))
                instance = AttackInstance.from_dict(data)
            except (TypeError, KeyError, ValueError) as exc:
                raise ValueError(f"invalid attack instance: {exc}") from exc
            jobs = [(instance, None, ())]
        reports = []
        for instance, classical, quantum in jobs:
            changes = {}
            if args.doom is not None:
                existing = tuple(tag for tag in instance.tags if tag.startswith("doom:"))
                tag = f"doom:{args.doom}"
                if existing and existing != (tag,):
                    raise ValueError("--doom conflicts with the instance's DOOM tag")
                changes["tags"] = instance.tags if existing else (*instance.tags, tag)
            if args.targets is not None:
                changes["targets"] = args.targets
            if changes:
                instance = replace(instance, **changes)
            reports.append(estimate(instance, options=Options(
                classical_algorithms=classical if args.classical_algorithms is None else args.classical_algorithms,
                quantum_algorithms=quantum if args.quantum_algorithms is None else args.quantum_algorithms,
                memory_bound_log2_bits=args.memory_bound,
            )))
        if args.json:
            print(json.dumps([r.to_dict() for r in reports], indent=2, ensure_ascii=False, allow_nan=False))
        else:
            _table(reports)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    except ImportError as exc:
        parser.error(f"backend dependency unavailable: {exc}; install with python -m pip install -e .")
    return 0


if __name__ == "__main__":
    sys.exit(main())
