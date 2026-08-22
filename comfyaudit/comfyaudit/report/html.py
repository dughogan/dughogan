"""Render an audit as a single self-contained HTML page.

No external assets: the page is one file you can email, archive with the show,
or open on a machine with no network.  It respects the reader's light/dark
preference and prints cleanly to PDF for a production folder.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
from typing import Any, Iterable

from .. import __version__
from ..audit import AuditReport
from ..records import Finding

VERDICT_TONE = {"blocked": "bad", "unclear": "warn", "conditional": "warn",
                "clear": "good", "unknown": "warn"}

VERDICT_LABEL = {
    "blocked": "Blocked",
    "conditional": "Conditional",
    "unclear": "Unclear",
    "clear": "Clear",
    "unknown": "Unknown",
}

SEVERITY_TONE = {"critical": "bad", "high": "bad", "medium": "warn",
                 "low": "muted", "info": "muted"}

COMMERCIAL_TONE = {"yes": "good", "conditional": "warn", "no": "bad", "unknown": "warn"}

CSS = """
:root{
  --bg:#f7f7f5; --panel:#ffffff; --ink:#1b1b1a; --muted:#63635e; --line:#e2e2dd;
  --good:#0f7a4d; --good-bg:#e6f4ec; --warn:#8a5a00; --warn-bg:#fdf1dc;
  --bad:#a32020; --bad-bg:#fbeaea; --accent:#2f4f8f;
}
:root:not([data-theme="light"]){ }
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#16171a; --panel:#1e2024; --ink:#e8e8e4; --muted:#a0a099; --line:#32343a;
    --good:#5fd0a0; --good-bg:#122b21; --warn:#e8b661; --warn-bg:#2e2412;
    --bad:#f08d8d; --bad-bg:#2f1919; --accent:#8fb0ee;
  }
}
:root[data-theme="dark"]{
  --bg:#16171a; --panel:#1e2024; --ink:#e8e8e4; --muted:#a0a099; --line:#32343a;
  --good:#5fd0a0; --good-bg:#122b21; --warn:#e8b661; --warn-bg:#2e2412;
  --bad:#f08d8d; --bad-bg:#2f1919; --accent:#8fb0ee;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:19px;margin:40px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:22px 0 8px}
.sub{color:var(--muted);font-size:13px;margin-bottom:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:20px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.card .v{font-size:22px;font-weight:640;margin-top:4px;letter-spacing:-.01em}
.card .d{font-size:12px;color:var(--muted);margin-top:4px}
.good{color:var(--good)} .warn{color:var(--warn)} .bad{color:var(--bad)} .muted{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:14px 0}
.panel.bad{border-left:4px solid var(--bad)}
.panel.warn{border-left:4px solid var(--warn)}
.panel.good{border-left:4px solid var(--good)}
.panel.muted{border-left:4px solid var(--line)}
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:520px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
tr:last-child td{border-bottom:none}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
code{font-size:12.5px;background:var(--bg);padding:1px 5px;border-radius:4px}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;
  overflow-x:auto;font-size:12.5px;white-space:pre-wrap;word-break:break-word;margin:8px 0}
.pill{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;
  border:1px solid currentColor}
.pill.good{background:var(--good-bg)} .pill.warn{background:var(--warn-bg)} .pill.bad{background:var(--bad-bg)}
.meter{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:8px}
.meter>span{display:block;height:100%;border-radius:3px}
ul{margin:8px 0;padding-left:20px} li{margin:3px 0}
.finding h3{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:2px}
.cat{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.rec{margin-top:8px;font-size:13.5px}
a{color:var(--accent)}
.footnote{color:var(--muted);font-size:12.5px;margin-top:8px}
@media print{
  body{background:#fff}
  .wrap{max-width:none;padding:0}
  .panel,.card{break-inside:avoid}
  h2{break-after:avoid}
}
"""


def render(report: AuditReport) -> str:
    src = report.source
    risk, auto = report.risk, report.automation
    parts: list[str] = []
    w = parts.append

    w("<!doctype html><html><head><meta charset='utf-8'>")
    w("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    w(f"<title>Audit - {_e(src.get('name', 'workflow'))}</title>")
    w(f"<style>{CSS}</style></head><body><div class='wrap'>")

    w(f"<h1>ComfyUI workflow audit</h1>")
    w(f"<div class='sub'><strong>{_e(src.get('name', 'workflow'))}</strong> &middot; "
      f"{src.get('nodes_total', 0)} nodes, {src.get('format', '?')} format &middot; "
      f"generated {_dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')} "
      f"by comfyaudit {__version__}</div>")

    # -- headline cards ----------------------------------------------------
    verdict_tone = VERDICT_TONE.get(risk.commercial_verdict, "warn")
    w("<div class='cards'>")
    w(_card("Commercial clearance", VERDICT_LABEL.get(risk.commercial_verdict, "Unknown"),
            risk.commercial_detail[:120], verdict_tone))
    w(_card("Production risk", f"{risk.score}<span style='font-size:14px'>/100</span>",
            risk.band, _risk_tone(risk.score), meter=(risk.score, _risk_tone(risk.score))))
    w(_card("Automation", f"{auto.index}<span style='font-size:14px'>/100</span>",
            auto.band, _auto_tone(auto.index), meter=(auto.index, _auto_tone(auto.index))))
    counts = risk.counts()
    w(_card("Findings",
            str(sum(counts.values())),
            ", ".join(f"{counts[s]} {s}" for s in
                      ("critical", "high", "medium", "low", "info") if counts.get(s)) or "none",
            "bad" if counts.get("critical") else ("warn" if counts.get("high") else "good")))
    w("</div>")

    if risk.commercial_detail:
        w(f"<div class='panel {verdict_tone}'>{_e(risk.commercial_detail)}</div>")

    top = [f for f in risk.findings if f.severity in ("critical", "high")][:3]
    if top:
        w("<h2>Do these first</h2><ol>")
        for finding in top:
            w(f"<li><strong>{_e(finding.title)}</strong> - "
              f"{_e(finding.recommendation or finding.detail)}</li>")
        w("</ol>")

    # -- models ------------------------------------------------------------
    w("<h2>1. Models and licensing</h2>")
    if not report.models:
        w("<p class='muted'>No model references found.</p>")
    else:
        rows = []
        for model in report.models:
            lic = model.license
            comm = lic.commercial_use if lic else "unknown"
            rows.append(
                f"<tr><td><code>{_e(model.filename)}</code>"
                + ("" if model.enabled else " <span class='muted'>(disabled)</span>")
                + f"</td><td>{_e(model.role)}</td>"
                f"<td>{_e(lic.name if lic else 'Unknown')}"
                + (f"<div class='muted' style='font-size:11.5px'>confidence: {lic.confidence}"
                   + (f", matched on <code>{_e(lic.matched_on)}</code>" if lic.matched_on else "")
                   + "</div>" if lic else "")
                + f"</td><td><span class='pill {COMMERCIAL_TONE.get(comm, 'warn')}'>"
                f"{_e(comm)}</span></td>"
                f"<td>{_source_link(model.provenance)}</td></tr>"
            )
        w(_table(["Model", "Role", "Licence", "Commercial", "Source"], rows))

        detail = [m for m in report.models
                  if m.license and (m.license.restrictions
                                    or m.license.commercial_use in ("no", "conditional", "unknown"))]
        if detail:
            w("<h3>Licence detail</h3>")
            for model in detail:
                lic = model.license
                tone = COMMERCIAL_TONE.get(lic.commercial_use, "warn")
                w(f"<div class='panel {tone}'><strong>{_e(model.filename)}</strong> "
                  f"&mdash; {_e(lic.name)}")
                if lic.summary:
                    w(f"<p>{_e(lic.summary)}</p>")
                if lic.restrictions:
                    w("<ul>" + "".join(f"<li>{_e(r)}</li>" for r in lic.restrictions) + "</ul>")
                links = []
                if lic.url:
                    links.append(f"<a href='{_e(lic.url)}'>licence</a>")
                if model.provenance and model.provenance.url:
                    links.append(f"<a href='{_e(model.provenance.url)}'>source</a>")
                if links:
                    w(f"<div class='footnote'>{' &middot; '.join(links)}</div>")
                w("</div>")

    # -- prompts -----------------------------------------------------------
    w("<h2>2. Prompts</h2>")
    if not report.prompts:
        w("<p class='muted'>No prompt text found.</p>")
    for polarity in ("positive", "negative", "both", "system", "unknown"):
        group = [p for p in report.prompts if p.polarity == polarity]
        if not group:
            continue
        w(f"<h3>{polarity.capitalize()} ({len(group)})</h3>")
        for prompt in group:
            flags = []
            if prompt.driven_by_link:
                flags.append("driven from upstream")
            if prompt.dynamic_syntax:
                flags.append("random alternation")
            if not prompt.enabled:
                flags.append("node disabled")
            head = f"<strong>{_e(prompt.node_label)}</strong> <code>{_e(prompt.widget)}</code>"
            if flags:
                head += f" <span class='muted'>({_e('; '.join(flags))})</span>"
            w(f"<div class='panel muted'>{head}<pre>{_e(prompt.text.strip()[:1600])}</pre>")
            if prompt.consumers:
                w(f"<div class='footnote'>Consumed by {_e(', '.join(prompt.consumers))}</div>")
            w("</div>")

    if report.notes:
        w("<h3>Notes left in the graph</h3><ul>")
        for note in report.notes:
            w(f"<li><strong>{_e(note.node_label)}</strong>: "
              f"{_e(' '.join(note.text.split())[:400])}</li>")
        w("</ul>")

    # -- assets ------------------------------------------------------------
    w("<h2>3. Assets</h2>")
    if report.inputs:
        rows = []
        for asset in report.inputs:
            how = "upload widget" if asset.upload_widget else "path in graph"
            if asset.kind == "url":
                how = "downloaded at run time"
            if asset.absolute_path:
                how += " &middot; <span class='bad'>absolute path</span>"
            rows.append(f"<tr><td><code>{_e(asset.value)}</code></td><td>{_e(asset.kind)}</td>"
                        f"<td>{_e(asset.node_label)}</td><td>{how}</td></tr>")
        w(_table(["Asset", "Kind", "Node", "Supplied how"], rows))
    else:
        w("<p class='muted'>No external inputs - this workflow generates from scratch.</p>")

    if report.outputs:
        w("<h3>Outputs</h3><ul>")
        for out in report.outputs:
            w(f"<li><code>{_e(out.value)}</code> from {_e(out.node_label)}</li>")
        w("</ul>")

    # -- dependencies ------------------------------------------------------
    w("<h2>4. Node dependencies</h2>")
    w(f"<p>{len(report.core_node_types)} core node types"
      + (f", {len(report.api_node_types)} hosted API node types" if report.api_node_types else "")
      + f", {len([p for p in report.packs if p.identified])} custom packs.</p>")
    if report.packs:
        rows = []
        for pack in report.packs:
            if not pack.identified:
                rows.append(f"<tr><td><code>{_e(pack.title)}</code> "
                            f"<span class='pill bad'>unidentified</span></td><td>-</td>"
                            f"<td>{pack.node_count}</td><td>-</td><td>-</td><td>-</td></tr>")
                continue
            ver = (f"<code>{_e(pack.pinned_version)}</code>" if pack.pinned_version
                   else "<span class='bad'>not pinned</span>")
            rows.append(
                f"<tr><td><a href='{_e(pack.reference or '#')}'>{_e(pack.title)}</a></td>"
                f"<td>{_e(pack.author or '-')}</td><td>{pack.node_count}</td>"
                f"<td>{ver}</td><td>{pack.stars if pack.stars is not None else '-'}</td>"
                f"<td>{_e((pack.last_update or '-').split(' ')[0])}</td></tr>"
            )
        w(_table(["Pack", "Author", "Nodes", "Version", "Stars", "Last commit"], rows))
        notes = [(p.title, n) for p in report.packs for n in p.notes]
        if notes:
            w("<ul>" + "".join(f"<li><strong>{_e(t)}</strong>: {_e(n)}</li>"
                               for t, n in notes) + "</ul>")
    else:
        w("<div class='panel good'>Core nodes only - the strongest position for "
          "portability and long-term maintenance.</div>")

    # -- automation --------------------------------------------------------
    w("<h2>5. Automation vs human intervention</h2>")
    w(f"<div class='panel {_auto_tone(auto.index)}'><strong>{auto.index}/100 &mdash; "
      f"{_e(auto.band)}.</strong> {_e(auto.band_detail)}"
      f"<div class='footnote'>Per-run human cost {auto.per_run_cost:.1f} &middot; "
      f"one-off setup cost {auto.setup_cost:.1f}</div></div>")

    per_run = auto.per_run_touchpoints
    if per_run:
        rows = [f"<tr><td>{t.cost:.1f}</td><td>{_e(t.stage)}</td>"
                f"<td>{_e(t.label)}</td><td class='muted'>{_e(t.detail)}</td></tr>"
                for t in per_run]
        w("<h3>Human touchpoints on every run</h3>")
        w(_table(["Weight", "When", "Touchpoint", "Why"], rows))
    else:
        w("<div class='panel good'>No per-run human touchpoints detected: this graph "
          "can be queued as-is.</div>")

    setup = auto.setup_touchpoints
    if setup:
        w("<h3>One-off setup</h3><ul>")
        for tp in setup:
            w(f"<li><strong>{_e(tp.label)}</strong> &mdash; {_e(tp.detail)}</li>")
        w("</ul>")

    if auto.automation_signals:
        w("<h3>Already automated</h3><ul>")
        for sig in auto.automation_signals:
            w(f"<li>{_e(sig)}</li>")
        w("</ul>")

    # -- risks -------------------------------------------------------------
    w("<h2>6. Production risks</h2>")
    if not risk.findings:
        w("<div class='panel good'>No risks identified.</div>")
    for finding in risk.findings:
        tone = SEVERITY_TONE.get(finding.severity, "warn")
        w(f"<div class='panel {tone} finding'>")
        w(f"<h3><span class='pill {tone}'>{_e(finding.severity)}</span> "
          f"{_e(finding.title)} <span class='cat'>{_e(finding.category)}</span></h3>")
        w(f"<p>{_e(finding.detail)}</p>")
        if finding.evidence:
            w("<ul>" + "".join(f"<li><code>{_e(str(e))}</code></li>"
                               for e in finding.evidence[:12]) + "</ul>")
            if len(finding.evidence) > 12:
                w(f"<div class='footnote'>...and {len(finding.evidence) - 12} more</div>")
        if finding.recommendation:
            w(f"<div class='rec'><strong>What to do:</strong> {_e(finding.recommendation)}</div>")
        w("</div>")

    # -- appendix ----------------------------------------------------------
    know = report.knowledge
    lic_meta = know.get("licences", {})
    diag = report.diagnostics
    w("<h2>Appendix</h2>")
    w("<h3>Knowledge sources</h3><ul>")
    w(f"<li>Core node schemas from ComfyUI {_e(know.get('comfyui_catalog_version', '?'))}</li>")
    w(f"<li>{know.get('node_packs_indexed', 0)} custom node packs indexed from the "
      "ComfyUI-Manager registry</li>")
    w(f"<li>Licence knowledge base v{_e(lic_meta.get('version', '?'))} "
      f"({lic_meta.get('model_rules', 0)} model rules), verified "
      f"{_e(lic_meta.get('checked', '?'))}</li>")
    w("</ul>")
    w("<h3>Audit coverage</h3><ul>")
    w(f"<li>Online lookups: {'enabled' if diag.get('online') else 'disabled (offline knowledge base only)'}</li>")
    w(f"<li>Local models directory: "
      + (f"<code>{_e(diag['models_dir'])}</code>, {diag.get('models_scanned_locally', 0)} "
         f"weights indexed" if diag.get("models_dir")
         else "not supplied, so model presence was not verified") + "</li>")
    if diag.get("parser_warning_count"):
        w(f"<li>{diag['parser_warning_count']} parser warning(s)</li>")
    w("</ul>")
    w("<div class='panel muted'><p>Licence findings are derived by matching model "
      "filenames against a curated knowledge base. Filenames are not authoritative, so "
      "every verdict carries the pattern it matched and a confidence level. Treat a low "
      "confidence verdict as a prompt to check the source, not as an answer.</p>"
      "<p>This is an engineering tool, not legal advice. It exists to surface the "
      "questions worth asking before a delivery, and to make the answers reproducible.</p>"
      "</div>")

    w("</div></body></html>")
    return "\n".join(parts)


# --------------------------------------------------------------------------


def _card(key: str, value: str, detail: str, tone: str,
          meter: tuple[int, str] | None = None) -> str:
    bar = ""
    if meter:
        pct, mtone = meter
        colour = {"good": "var(--good)", "warn": "var(--warn)", "bad": "var(--bad)"}.get(mtone, "var(--muted)")
        bar = f"<div class='meter'><span style='width:{max(2, min(100, pct))}%;background:{colour}'></span></div>"
    return (f"<div class='card'><div class='k'>{_e(key)}</div>"
            f"<div class='v {tone}'>{value}</div>"
            f"<div class='d'>{_e(detail)}</div>{bar}</div>")


def _table(headers: Iterable[str], rows: Iterable[str]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    return ("<div class='tablewrap'><table><thead><tr>" + head
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def _source_link(prov: Any) -> str:
    if prov is None or prov.source == "unknown":
        return "<span class='muted'>unresolved</span>"
    label = _e(prov.source)
    if prov.gated:
        label += " <span class='pill warn'>gated</span>"
    if prov.url:
        return f"<a href='{_e(prov.url)}'>{label}</a>"
    return label


def _risk_tone(score: int) -> str:
    return "bad" if score >= 50 else ("warn" if score >= 25 else "good")


def _auto_tone(index: int) -> str:
    return "good" if index >= 65 else ("warn" if index >= 40 else "bad")


def _e(text: Any) -> str:
    return _html.escape(str(text if text is not None else ""), quote=True)
