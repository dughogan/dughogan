"""Record gate decisions: the human side of the dataset's provenance.

Interactive curation (shows each undecided clip's contact sheet, asks
keep / cut / skip and why):
    python -m cgdata.review shots LIBRARY --gate shot_curated --as "Doug Hogan"

One decision, scripted:
    python -m cgdata.review shot LIBRARY/cg/CG_000001 --gate comp_finished \\
        --approve --note "Grade and defocus read as photographed" --as "Doug Hogan"
    python -m cgdata.review asset LIBRARY city_kit_v1 --approve \\
        --note "Facade variety is enough for wide shots" --evidence turntable.png --as "Doug Hogan"
    python -m cgdata.review look LIBRARY toon_v2 --reject --note "Ramp too soft" --as "Doug Hogan"

Status of every clip's gates and history:
    python -m cgdata.review status LIBRARY

ComfyAudit provenance record (HTML) for a clip:
    python -m cgdata.review record LIBRARY/cg/CG_000001 --out CG_000001_provenance.html

Every decision needs a note saying why: the reasons are the evidence of
creative control (see provenance.py).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from cgdata import provenance


def _open(path):
    """Show an image in the system viewer; harmless if there isn't one."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606 - local review only
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.environ.get("DISPLAY"):
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


def _decision(args):
    if args.approve == args.reject:
        raise SystemExit("give exactly one of --approve or --reject")
    return "approve" if args.approve else "reject"


def cmd_shots(args):
    shots = sorted(p.parent for p in (args.library / "cg").glob("*/meta.json"))
    todo = [s for s in shots
            if args.gate not in provenance.summary(provenance.shot_history_path(s)).get("gates", {})]
    print(f"{len(todo)} of {len(shots)} clips have no {args.gate} decision yet. "
          "k = keep, c = cut, s = skip, q = quit")
    for shot in todo:
        sheet = next(iter(sorted((shot / "qa").glob("*.png"))), None)
        print(f"\n{shot.name}: {sheet or 'no contact sheet'}")
        if sheet and not args.no_open:
            _open(sheet)
        choice = input("  keep / cut / skip / quit [k/c/s/q]: ").strip().lower()[:1]
        if choice == "q":
            break
        if choice not in ("k", "c"):
            continue
        note = ""
        while not note:
            note = input("  why (required): ").strip()
        provenance.decide_shot(shot, gate=args.gate, decision="approve" if choice == "k" else "reject",
                               person=args.person, role=args.role, note=note)
        print("  recorded")


def cmd_shot(args):
    entry = provenance.decide_shot(args.shot, gate=args.gate, decision=_decision(args),
                                   person=args.person, role=args.role, note=args.note)
    print(f"{args.shot.name}: {entry['event']} ({args.gate}) seq {entry['seq']}")


def cmd_subject(args, kind):
    entry = provenance.decide_subject(args.library, kind, args.name, decision=_decision(args),
                                      person=args.person, role=args.role, note=args.note,
                                      evidence=args.evidence)
    print(f"{args.name}: {entry['event']} seq {entry['seq']}")


def cmd_status(args):
    rows = []
    for meta in sorted((args.library / "cg").glob("*/meta.json")):
        s = provenance.summary(provenance.shot_history_path(meta.parent))
        gates = s.get("gates", {})
        rows.append((meta.parent.name, s["assurance"],
                     *(gates.get(g, {}).get("decision", "-") for g in provenance.SHOT_GATES),
                     "; ".join(s.get("problems", []))[:60]))
    print(f"{'clip':<12} {'assurance':<12} {'curated':<9} {'comp':<9} problems")
    for r in rows:
        print(f"{r[0]:<12} {r[1]:<12} {r[2]:<9} {r[3]:<9} {r[4]}")
    for kind in ("assets", "looks"):
        for path in sorted((args.library / "provenance" / kind).glob("*.history.json")):
            s = provenance.summary(path)
            gate = next(iter(s["gates"].values()), {})
            print(f"{kind[:-1]} {path.name.split('.')[0]}: {gate.get('decision', '-')} "
                  f"by {gate.get('by', '-')} ({s['assurance']})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def person(p):
        p.add_argument("--as", dest="person", required=True, help="who is deciding (full name)")
        p.add_argument("--role", default="", help="e.g. 'VFX Supervisor'")

    def verdict(p):
        p.add_argument("--approve", action="store_true")
        p.add_argument("--reject", action="store_true")
        p.add_argument("--note", required=True, help="why: required")

    p = sub.add_parser("shots", help="interactive curation")
    p.add_argument("library", type=Path)
    p.add_argument("--gate", choices=provenance.SHOT_GATES, default="shot_curated")
    p.add_argument("--no-open", action="store_true", help="don't open contact sheets")
    person(p)

    p = sub.add_parser("shot", help="one clip decision")
    p.add_argument("shot", type=Path)
    p.add_argument("--gate", choices=provenance.SHOT_GATES, required=True)
    person(p)
    verdict(p)

    for kind, label in (("asset", "an asset kit"), ("look", "a look")):
        p = sub.add_parser(kind, help=f"approve or reject {label}")
        p.add_argument("library", type=Path)
        p.add_argument("name")
        p.add_argument("--evidence", nargs="*", default=[], help="turntables / contact sheets reviewed")
        person(p)
        verdict(p)

    p = sub.add_parser("status", help="gates and history assurance for every clip")
    p.add_argument("library", type=Path)

    p = sub.add_parser("record", help="export a clip's ComfyAudit provenance record (HTML)")
    p.add_argument("shot", type=Path)
    p.add_argument("--out", type=Path, required=True)

    args = ap.parse_args()
    if args.cmd == "shots":
        cmd_shots(args)
    elif args.cmd == "shot":
        cmd_shot(args)
    elif args.cmd in ("asset", "look"):
        cmd_subject(args, args.cmd + "s")
    elif args.cmd == "record":
        print(provenance.record_html(provenance.shot_history_path(args.shot), args.out))
    else:
        cmd_status(args)


if __name__ == "__main__":
    main()
