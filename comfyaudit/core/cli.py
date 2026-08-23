"""Command line interface for comfyaudit."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import __version__, catalog, graph
from .audit import AuditOptions, AuditReport, run
from .report import markdown as md_report
from .records import Finding
from .score import clearance

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comfyaudit",
        description="Evaluate and audit ComfyUI workflows: models, licences, prompts, "
                    "assets, automation level and production risk.",
    )
    parser.add_argument("--version", action="version", version=f"comfyaudit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="run a full audit on one or more workflows")
    audit.add_argument("workflows", nargs="+",
                       help="workflow .json files, or PNG/WebP images with embedded metadata")
    audit.add_argument("-o", "--output", default="",
                       help="write the report here (a directory when auditing several files)")
    audit.add_argument("-f", "--format", default="markdown",
                       choices=["markdown", "md", "json", "html", "text"],
                       help="report format (default: markdown)")
    audit.add_argument("--online", action="store_true",
                       help="look up provenance and licences on HuggingFace, Civitai and "
                            "the Comfy Registry (results are cached on disk)")
    audit.add_argument("--models-dir", default="",
                       help="path to a ComfyUI models/ folder, to verify the weights exist "
                            "and hash them")
    audit.add_argument("--licences", "--licenses", dest="licences", default="",
                       help="a studio licence file that extends or overrides the bundled one")
    audit.add_argument("--sources", default="",
                       help="limit which services --online contacts, comma separated: "
                            "huggingface, civitai, github, comfy-registry (default: all)")
    audit.add_argument("--hf-token", default="",
                       help="HuggingFace token for gated repositories (or set HF_TOKEN)")
    audit.add_argument("--civitai-token", default="",
                       help="Civitai API key (or set CIVITAI_API_KEY)")
    audit.add_argument("--github-token", default="",
                       help="GitHub token; lifts the 60-requests-an-hour anonymous "
                            "limit (or set GITHUB_TOKEN)")
    audit.add_argument("--no-hash", action="store_true",
                       help="skip SHA-256 hashing of local weights")
    audit.add_argument("--fail-on", default="", choices=[""] + SEVERITY_ORDER,
                       help="exit non-zero if a finding at this severity or worse is present, "
                            "for use as a pipeline gate")
    audit.add_argument("--quiet", action="store_true", help="suppress the console summary")

    # -- the studio's own facts, without which no verdict is possible --------
    profile = audit.add_argument_group(
        "studio profile",
        "Facts about the facility. Licence terms turn on these, so supplying them "
        "is what turns a description of the terms into a go / no-go. Omit them "
        "and the report describes the terms and stops there.")
    profile.add_argument("--territory", default="", metavar="CODE",
                         choices=[""] + sorted(clearance.TERRITORIES),
                         help="where the work is rendered and deployed; several "
                              "licences exclude regions by name")
    profile.add_argument("--revenue", default="unknown", metavar="BAND",
                         choices=sorted(clearance.REVENUE_BANDS),
                         help="annual company revenue band; free use is capped by "
                              "revenue under several licences")
    profile.add_argument("--ships", default="unknown", metavar="WHAT",
                         choices=sorted(clearance.SHIPS),
                         help="what leaves the building; decides whether copyleft "
                              "reaches your own code")
    profile.add_argument("--trains-models", action="store_true",
                         help="outputs are used to train other models, which "
                              "several licences forbid outright")
    profile.add_argument("--likeness", action="store_true",
                         help="real performers are involved, which is a consent "
                              "question no model licence answers")
    profile.add_argument("--studio", default="", metavar="NAME",
                         help="a label for the report - a facility, show or client")
    profile.add_argument("--profile", default="", metavar="PATH",
                         help="read the above from a JSON file instead, so a "
                              "facility states its circumstances once")
    audit.add_argument("--claude", nargs="?", const="full", default="",
                       choices=["", "full", "identify", "clearance", "remediate"],
                       help="have Claude investigate the audit as well: identify models "
                            "the rules could not, review prompt text for trademark and "
                            "likeness risk, and propose commercially clear replacements")
    audit.add_argument("--claude-model", default="claude-opus-5",
                       help="model for the review (default: claude-opus-5)")
    audit.add_argument("--claude-effort", default="high",
                       choices=["low", "medium", "high", "xhigh", "max"])
    audit.add_argument("--no-web-search", action="store_true",
                       help="stop the review looking models up on the web; use this "
                            "when the workflow content is confidential")
    audit.add_argument("--ask", default="",
                       help="ask Claude a specific question about the workflow "
                            "instead of running a review mode")

    listing = sub.add_parser("models", help="list just the models a workflow references")
    listing.add_argument("workflow")
    listing.add_argument("--online", action="store_true")
    listing.add_argument("--models-dir", default="")

    sub.add_parser("info", help="show what the bundled knowledge base contains")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "info":
        return _cmd_info()
    if args.command == "models":
        return _cmd_models(args)
    return _cmd_audit(args)


# --------------------------------------------------------------------------


def _cmd_audit(args: argparse.Namespace) -> int:
    from ..core.resolve.resolver import ALL_SOURCES
    wanted = tuple(s.strip().lower() for s in args.sources.split(",") if s.strip())
    unknown = [s for s in wanted if s not in ALL_SOURCES]
    if unknown:
        print(f"unknown source(s): {', '.join(unknown)}. "
              f"Valid: {', '.join(ALL_SOURCES)}", file=sys.stderr)
        return 2

    opts = AuditOptions(
        online=args.online,
        sources=tuple(s for s in wanted if s in ALL_SOURCES) or ALL_SOURCES,
        models_dir=args.models_dir,
        licences_path=args.licences,
        hf_token=args.hf_token,
        civitai_token=args.civitai_token,
        github_token=args.github_token,
        hash_models=not args.no_hash,
        profile=_studio_profile(args),
    )

    paths = _expand(args.workflows)
    if not paths:
        print("no workflow files matched", file=sys.stderr)
        return 2

    multiple = len(paths) > 1
    reports: list[tuple[str, AuditReport]] = []
    failures = 0

    for path in paths:
        try:
            report = run(path, opts)
        except (OSError, ValueError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            failures += 1
            continue

        if args.claude or args.ask:
            _add_claude_review(report, args)

        reports.append((path, report))
        _emit(report, path, args, multiple)

    if not args.quiet:
        if multiple:
            _print_batch_summary(reports)
        elif reports:
            _print_summary(reports[0][1])

    if failures and not reports:
        return 2

    if args.fail_on:
        threshold = SEVERITY_ORDER.index(args.fail_on)
        for _, report in reports:
            for finding in report.risk.findings:
                if SEVERITY_ORDER.index(finding.severity) <= threshold:
                    return 1
    return 0 if not failures else 2


def _add_claude_review(report: AuditReport, args: argparse.Namespace) -> None:
    """Run the agent and attach the result so every format renders it."""
    from ..agent import reviewer as reviewer_mod
    from ..core.resolve.http import Credentials, HttpClient
    from ..core.resolve.resolver import Resolver

    # Give the agent the same lookups the audit used, so it can check a licence
    # at source instead of recalling one.
    resolver = None
    if args.online:
        from ..core.resolve.resolver import ALL_SOURCES
        wanted = tuple(s.strip().lower() for s in args.sources.split(",") if s.strip())
        resolver = Resolver(
            http=HttpClient(),
            credentials=Credentials.from_environment(
                huggingface=args.hf_token, civitai=args.civitai_token,
                github=args.github_token),
            sources=tuple(s for s in wanted if s in ALL_SOURCES) or ALL_SOURCES,
            enabled=True,
        )

    if not args.quiet:
        print("running the Claude review...", file=sys.stderr)
    result = reviewer_mod.review(
        report,
        mode=args.claude or "full",
        model=args.claude_model,
        effort=args.claude_effort,
        web_search=not args.no_web_search,
        question=args.ask,
        resolver=resolver,
    )
    reviewer_mod.apply_to_report(report, result)
    report.diagnostics["claude_review"] = result.as_dict()
    if result.error and not args.quiet:
        print(f"claude review: {result.error}", file=sys.stderr)


def _emit(report: AuditReport, path: str, args: argparse.Namespace, multiple: bool) -> None:
    fmt = "markdown" if args.format == "md" else args.format
    body = _render(report, fmt)

    if not args.output:
        if fmt == "text":
            return  # the console summary is the text format
        print(body)
        return

    if multiple or os.path.isdir(args.output) or args.output.endswith(os.sep):
        os.makedirs(args.output, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        target = os.path.join(args.output, f"{stem}.audit.{_extension(fmt)}")
    else:
        target = args.output

    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(body)
    if not args.quiet:
        print(f"wrote {target}", file=sys.stderr)


def _render(report: AuditReport, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(report.to_dict(), indent=2)
    if fmt == "html":
        from .report import html as html_report
        return html_report.render(report)
    return md_report.render(report)


def _extension(fmt: str) -> str:
    return {"json": "json", "html": "html"}.get(fmt, "md")


# --------------------------------------------------------------------------


def _cmd_models(args: argparse.Namespace) -> int:
    report = run(args.workflow, AuditOptions(online=args.online, models_dir=args.models_dir))
    if not report.models:
        print("no models found")
        return 0
    width = max(len(m.filename) for m in report.models)
    for model in report.models:
        lic = model.license
        flag = {"no": "non-commercial", "conditional": "conditional",
                "unknown": "unstated", "yes": "permissive"}.get(
                    lic.commercial_use if lic else "unknown", "?")
        print(f"{model.filename:<{width}}  {model.role:<28}  {flag:<16}  "
              f"{lic.name if lic else 'Unknown'}")
    return 0


def _cmd_info() -> int:
    from .knowledge import licences as licences_mod

    packs = catalog.node_packs()
    meta = licences_mod.kb_metadata()
    print(f"comfyaudit {__version__}")
    print(f"  core node catalog     ComfyUI {catalog.comfyui_version()}, "
          f"{len(catalog.core_nodes()['nodes'])} node types")
    print(f"  custom node index     {len(packs['packs'])} packs, "
          f"{len(packs['node_index'])} node classes")
    print(f"  known model index     {len(catalog.known_models())} filenames")
    print(f"  licence knowledge     v{meta['version']} ({meta['model_rules']} model rules, "
          f"{meta['licence_terms']} licence definitions), verified {meta['checked']}")
    bases = licences_mod.load_base_models().get("base_models", {})
    classified = sum(1 for r in bases.values() if r.get("licence_id"))
    print(f"  base model licences   {len(bases)} base models, {classified} classified")
    from ..core.resolve.http import Credentials
    from ..core.resolve.resolver import ALL_SOURCES
    have = Credentials.from_environment().describe()
    tokens = ", ".join(f"{k}{'*' if v else ''}" for k, v in have.items())
    print(f"  online sources        {', '.join(ALL_SOURCES)}")
    print(f"  credentials found     {tokens or 'none'}   (* = token present)")
    return 0


# --------------------------------------------------------------------------



def _studio_profile(args) -> clearance.StudioProfile | None:
    """Build the profile from flags, or from the file that stands in for them."""
    if getattr(args, "profile", ""):
        with open(args.profile, "r", encoding="utf-8") as handle:
            return clearance.StudioProfile.from_dict(json.load(handle))
    built = clearance.StudioProfile(
        territory=args.territory,
        revenue_band=args.revenue,
        ships=args.ships,
        trains_models=args.trains_models,
        likeness_involved=args.likeness,
        label=args.studio,
    )
    return built if built.is_set else None


def _expand(paths: list[str]) -> list[str]:
    out: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.lower().endswith((".json", ".png", ".webp")):
                    out.append(os.path.join(path, name))
        else:
            out.append(path)
    return out


def _print_summary(report: AuditReport) -> None:
    risk = report.risk
    auto = report.automation
    counts = risk.counts()
    line = "=" * 68
    print(line, file=sys.stderr)
    print(f" {report.source.get('name', 'workflow')}", file=sys.stderr)
    print(line, file=sys.stderr)
    print(f" Licences             : {report.licensing.headline}", file=sys.stderr)
    print(f" Operational risk     : {risk.score}/100 ({risk.band})", file=sys.stderr)
    print(f" Automation index     : {auto.index}/100 ({auto.band})", file=sys.stderr)
    print(f" Models / packs       : {len(report.models)} / {len(report.packs)}", file=sys.stderr)
    if counts:
        parts = [f"{counts[s]} {s}" for s in SEVERITY_ORDER if counts.get(s)]
        print(f" Findings             : {', '.join(parts)}", file=sys.stderr)
    for finding in risk.findings[:3]:
        if finding.severity in ("critical", "high"):
            print(f"   [{finding.severity}] {finding.title}", file=sys.stderr)
    print(line, file=sys.stderr)


def _print_batch_summary(reports: list[tuple[str, AuditReport]]) -> None:
    if not reports:
        return
    name_w = max(len(os.path.basename(p)) for p, _ in reports)
    print("", file=sys.stderr)
    print(f"{'workflow':<{name_w}}  {'risk':>7}  {'auto':>5}  licences", file=sys.stderr)
    for path, report in reports:
        counts = report.licensing.counts
        composition = ", ".join(f"{counts[p]} {p}" for p in
                                ("permissive", "conditional", "non-commercial", "unstated")
                                if counts.get(p)) or "none found"
        print(f"{os.path.basename(path):<{name_w}}  "
              f"{report.risk.score:>3}/100  {report.automation.index:>3}  "
              f"{composition}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
