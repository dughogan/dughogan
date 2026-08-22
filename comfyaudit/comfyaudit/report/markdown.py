"""Render an audit as a Markdown report."""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable

from .. import __version__
from ..audit import AuditReport
from ..records import Finding, ModelRef

VERDICT_LABEL = {
    "blocked": "BLOCKED - not deliverable commercially as it stands",
    "conditional": "CONDITIONAL - deliverable if the conditions are met",
    "unclear": "UNCLEAR - cannot be cleared without more information",
    "clear": "CLEAR - all identified models permit commercial use",
    "unknown": "UNKNOWN - no models identified",
}

SEVERITY_MARK = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM",
                 "low": "LOW", "info": "INFO"}

COMMERCIAL_MARK = {"yes": "Yes", "conditional": "Conditional", "no": "No", "unknown": "Unknown"}


def render(report: AuditReport) -> str:
    out: list[str] = []
    w = out.append
    src = report.source

    w(f"# ComfyUI workflow audit - {src.get('name', 'workflow')}")
    w("")
    w(f"*Generated {_dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')} "
      f"by comfyaudit {__version__}.*")
    w("")

    # -- verdict -----------------------------------------------------------
    w("## Verdict")
    w("")
    w("| | |")
    w("|---|---|")
    w(f"| **Commercial clearance** | {VERDICT_LABEL.get(report.risk.commercial_verdict, 'Unknown')} |")
    w(f"| **Production risk** | {report.risk.score}/100 - {report.risk.band} |")
    w(f"| **Automation index** | {report.automation.index}/100 - {report.automation.band} |")
    w(f"| **Graph** | {src.get('nodes_total', 0)} nodes "
      f"({src.get('nodes_disabled', 0)} disabled), {len(report.models)} models, "
      f"{len(report.packs)} custom packs |")
    w("")
    if report.risk.commercial_detail:
        w(f"{report.risk.commercial_detail}")
        w("")
    w(f"{report.risk.band_detail} {report.automation.band_detail}")
    w("")

    counts = report.risk.counts()
    if counts:
        parts = [f"{counts[s]} {s}" for s in ("critical", "high", "medium", "low", "info")
                 if counts.get(s)]
        w(f"**Findings:** {', '.join(parts)}.")
        w("")

    _headline_actions(w, report)

    # -- models ------------------------------------------------------------
    w("## 1. Models and licensing")
    w("")
    if not report.models:
        w("No model references were found in this workflow.")
        w("")
    else:
        w("| Model | Role | Licence | Commercial use | Fee | Source |")
        w("|---|---|---|---|---|---|")
        for model in report.models:
            lic = model.license
            prov = model.provenance
            w("| {file} | {role} | {lic} | {comm} | {fee} | {src} |".format(
                file=_cell(model.filename) + ("" if model.enabled else " *(disabled)*"),
                role=_cell(model.role),
                lic=_cell(lic.name if lic else "Unknown"),
                comm=COMMERCIAL_MARK.get(lic.commercial_use if lic else "unknown", "Unknown"),
                fee=_cell(_fee_label(lic.fee if lic else "unknown")),
                src=_source_cell(prov),
            ))
        w("")
        _model_details(w, report.models)

    # -- prompts -----------------------------------------------------------
    w("## 2. Prompts")
    w("")
    if not report.prompts:
        w("No prompt text was found.")
        w("")
    else:
        for polarity in ("positive", "negative", "both", "system", "unknown"):
            group = [p for p in report.prompts if p.polarity == polarity]
            if not group:
                continue
            w(f"### {polarity.capitalize()} ({len(group)})")
            w("")
            for prompt in group:
                head = f"**{prompt.node_label}** - `{prompt.widget}`"
                flags = []
                if prompt.driven_by_link:
                    flags.append("driven from upstream at run time")
                if not prompt.enabled:
                    flags.append("node disabled")
                if prompt.dynamic_syntax:
                    flags.append("contains {a|b} alternation")
                if prompt.token_estimate > 77 and prompt.node_type.startswith("CLIPTextEncode"):
                    flags.append(f"~{prompt.token_estimate} tokens, over the 77-token CLIP window")
                if flags:
                    head += f" *({'; '.join(flags)})*"
                w(head)
                w("")
                w("```text")
                w(prompt.text.strip()[:2000])
                w("```")
                if prompt.consumers:
                    w(f"Consumed by: {', '.join(prompt.consumers)}")
                w("")

        deps = report.prompt_dependencies
        extras = [(k, v) for k, v in deps.items() if v and k != "dynamic_syntax"]
        if extras:
            w("**Dependencies referenced inside prompt text**")
            w("")
            for key, values in extras:
                w(f"- {key.replace('_', ' ')}: {', '.join(values)}")
            w("")

    if report.notes:
        w("### Notes left in the graph")
        w("")
        for note in report.notes:
            w(f"- **{note.node_label}**: {_oneline(note.text, 400)}")
        w("")

    # -- assets ------------------------------------------------------------
    w("## 3. Assets")
    w("")
    if report.inputs:
        w("**Inputs**")
        w("")
        w("| Asset | Kind | Node | Supplied how |")
        w("|---|---|---|---|")
        for asset in report.inputs:
            how = "upload widget (a person picks it)" if asset.upload_widget else "path in the graph"
            if asset.kind == "url":
                how = "downloaded at run time"
            if asset.absolute_path:
                how += " - absolute path"
            w(f"| {_cell(asset.value)} | {asset.kind} | {_cell(asset.node_label)} | {how} |")
        w("")
    else:
        w("No external input assets - this workflow generates from scratch.")
        w("")

    if report.outputs:
        w("**Outputs**")
        w("")
        for out_asset in report.outputs:
            w(f"- `{out_asset.value}` from {out_asset.node_label} (`{out_asset.node_type}`)")
        w("")

    # -- dependencies ------------------------------------------------------
    w("## 4. Node dependencies")
    w("")
    w(f"Core ComfyUI node types used: **{len(report.core_node_types)}**"
      + (f" | Hosted API node types: **{len(report.api_node_types)}**" if report.api_node_types else ""))
    w("")
    if report.packs:
        w("| Pack | Author | Nodes used | Version pinned | Stars | Last commit |")
        w("|---|---|---|---|---|---|")
        for pack in report.packs:
            if not pack.identified:
                w(f"| {_cell(pack.title)} **(unidentified)** | - | {pack.node_count} | - | - | - |")
                continue
            w("| [{title}]({url}) | {author} | {n} ({types}) | {ver} | {stars} | {last} |".format(
                title=_cell(pack.title), url=pack.reference or "#",
                author=_cell(pack.author or "-"), n=pack.node_count,
                types=_cell(", ".join(pack.node_types[:3]) + ("..." if len(pack.node_types) > 3 else "")),
                ver=pack.pinned_version or "**not pinned**",
                stars=pack.stars if pack.stars is not None else "-",
                last=pack.last_update.split(" ")[0] if pack.last_update else "-",
            ))
        w("")
        notes = [(p.title, n) for p in report.packs for n in p.notes]
        if notes:
            for title, note in notes:
                w(f"- **{title}**: {note}")
            w("")
    else:
        w("This workflow uses only core ComfyUI nodes - the strongest possible position "
          "for portability and long-term maintenance.")
        w("")

    if report.api_node_types:
        w("**Hosted API nodes** (billed per call, run on vendor infrastructure):")
        w("")
        for node_type in report.api_node_types:
            w(f"- `{node_type}`")
        w("")

    # -- automation --------------------------------------------------------
    w("## 5. Automation vs human intervention")
    w("")
    auto = report.automation
    w(f"**{auto.index}/100 - {auto.band}.** {auto.band_detail}")
    w("")
    w(f"Per-run human cost: {auto.per_run_cost:.1f} | one-off setup cost: {auto.setup_cost:.1f}")
    w("")
    per_run = auto.per_run_touchpoints
    if per_run:
        w("### Human touchpoints on every run")
        w("")
        w("| Weight | When | Touchpoint | Why |")
        w("|---|---|---|---|")
        for tp in per_run:
            w(f"| {tp.cost:.1f} | {tp.stage} | {_cell(tp.label)} | {_cell(tp.detail)} |")
        w("")
    else:
        w("No per-run human touchpoints were detected: this graph can be queued as-is.")
        w("")

    setup = auto.setup_touchpoints
    if setup:
        w("### One-off setup before it will run anywhere else")
        w("")
        for tp in setup:
            w(f"- **{tp.label}** - {tp.detail}")
        w("")

    if auto.automation_signals:
        w("### What is already automated")
        w("")
        for sig in auto.automation_signals:
            w(f"- {sig}")
        w("")

    # -- risks -------------------------------------------------------------
    w("## 6. Production risks")
    w("")
    if not report.risk.findings:
        w("No risks were identified.")
        w("")
    else:
        if report.risk.by_category:
            w("| Category | Weighted score |")
            w("|---|---|")
            for cat, value in sorted(report.risk.by_category.items(), key=lambda kv: -kv[1]):
                w(f"| {cat} | {value} |")
            w("")
        for finding in report.risk.findings:
            w(f"### [{SEVERITY_MARK.get(finding.severity, finding.severity.upper())}] "
              f"{finding.title}")
            w("")
            w(f"*{finding.category}*")
            w("")
            w(finding.detail)
            w("")
            if finding.evidence:
                for item in finding.evidence[:12]:
                    w(f"- {item}")
                if len(finding.evidence) > 12:
                    w(f"- ...and {len(finding.evidence) - 12} more")
                w("")
            if finding.recommendation:
                w(f"**What to do:** {finding.recommendation}")
                w("")

    # -- appendix ----------------------------------------------------------
    _appendix(w, report)
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------


def _headline_actions(w, report: AuditReport) -> None:
    """The three things a supervisor should do first."""
    top = [f for f in report.risk.findings if f.severity in ("critical", "high")][:3]
    if not top:
        return
    w("### Do these first")
    w("")
    for i, finding in enumerate(top, 1):
        w(f"{i}. **{finding.title}** - {finding.recommendation or finding.detail}")
    w("")


def _model_details(w, models: list[ModelRef]) -> None:
    interesting = [m for m in models if m.license and (
        m.license.restrictions or m.license.commercial_use in ("no", "conditional", "unknown")
    )]
    if not interesting:
        return
    w("### Licence detail")
    w("")
    for model in interesting:
        lic = model.license
        w(f"**{model.filename}** - {lic.name}")
        w("")
        if lic.summary:
            w(f"{lic.summary}")
            w("")
        if lic.restrictions:
            for restriction in lic.restrictions:
                w(f"- {restriction}")
            w("")
        meta = []
        if lic.matched_on:
            meta.append(f"matched on `{lic.matched_on}`")
        meta.append(f"confidence: {lic.confidence}")
        if lic.url:
            meta.append(f"[licence source]({lic.url})")
        if model.provenance and model.provenance.url:
            meta.append(f"[model source]({model.provenance.url})")
        w(f"*{' | '.join(meta)}*")
        w("")


def _appendix(w, report: AuditReport) -> None:
    w("## Appendix")
    w("")
    know = report.knowledge
    lic_meta = know.get("licences", {})
    w("**Knowledge sources**")
    w("")
    w(f"- Core node schemas scraped from ComfyUI {know.get('comfyui_catalog_version', '?')}")
    w(f"- Custom node index: {know.get('node_packs_indexed', 0)} packs from the ComfyUI-Manager registry")
    w(f"- Licence knowledge base v{lic_meta.get('version', '?')} "
      f"({lic_meta.get('model_rules', 0)} model rules, "
      f"{lic_meta.get('licence_terms', 0)} licence definitions), last verified "
      f"{lic_meta.get('checked', '?')}")
    if lic_meta.get("overrides_from"):
        w(f"- Studio licence overrides: {lic_meta['overrides_from']}")
    w("")

    diag = report.diagnostics
    w("**Audit coverage**")
    w("")
    w(f"- Online lookups: {'enabled' if diag.get('online') else 'disabled (offline knowledge base only)'}")
    if diag.get("models_dir"):
        w(f"- Local models directory: `{diag['models_dir']}` "
          f"({diag.get('models_scanned_locally', 0)} weight files indexed, "
          f"{diag.get('models_hashed', 0)} hashed)")
    else:
        w("- Local models directory: not supplied, so model presence was not verified")
    if diag.get("parser_warning_count"):
        w(f"- Parser warnings: {diag['parser_warning_count']} "
          "(nodes whose stored widget values did not match a known schema)")
    if diag.get("lookup_errors"):
        w(f"- Failed lookups: {len(diag['lookup_errors'])}")
        for err in diag["lookup_errors"][:5]:
            w(f"  - {err}")
    w("")

    w("**Reading this report**")
    w("")
    w("Licence findings are derived by matching model filenames against a curated "
      "knowledge base. Filenames are not authoritative - anyone can rename a weight - "
      "so every licence verdict carries the pattern it matched on and a confidence "
      "level. Treat a `low` confidence verdict as a prompt to check the source page, "
      "not as an answer.")
    w("")
    w("This is an engineering tool, not legal advice. It is designed to find the "
      "questions worth asking your legal or production team before a delivery, and to "
      "make the answers reproducible.")
    w("")


def _cell(text: Any) -> str:
    value = str(text if text is not None else "")
    return value.replace("|", "\\|").replace("\n", " ")[:160]


def _oneline(text: str, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


def _fee_label(fee: str) -> str:
    return {
        "none": "None",
        "revenue-threshold": "Above revenue cap",
        "paid": "Licence required",
        "unknown": "Unknown",
    }.get(fee, fee)


def _source_cell(prov: Any) -> str:
    if prov is None or prov.source == "unknown":
        return "unresolved"
    if prov.url:
        return f"[{prov.source}]({prov.url})"
    return prov.source
