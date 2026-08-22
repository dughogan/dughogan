"""Run a full audit: parse, extract, resolve, score."""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from typing import Any

from . import catalog, graph
from .extract import assets as assets_extract
from .extract import models as models_extract
from .extract import packs as packs_extract
from .extract import prompts as prompts_extract
from .knowledge import licences as licences_mod
from .records import AssetRef, ModelRef, PackRef, PromptRef, to_jsonable
from .resolve import local as local_mod
from .resolve.cache import HttpCache
from .resolve.online import Resolver, hf_licence_tag
from .score import automation as automation_mod
from .score import risk as risk_mod


@dataclass
class AuditOptions:
    online: bool = False
    models_dir: str = ""
    licences_path: str = ""
    hf_token: str = ""
    hash_models: bool = True
    cache_ttl: int | None = None


@dataclass
class AuditReport:
    source: dict[str, Any] = field(default_factory=dict)
    models: list[ModelRef] = field(default_factory=list)
    prompts: list[PromptRef] = field(default_factory=list)
    notes: list[PromptRef] = field(default_factory=list)
    inputs: list[AssetRef] = field(default_factory=list)
    outputs: list[AssetRef] = field(default_factory=list)
    packs: list[PackRef] = field(default_factory=list)
    core_node_types: list[str] = field(default_factory=list)
    api_node_types: list[str] = field(default_factory=list)
    missing_models: list[ModelRef] = field(default_factory=list)
    automation: automation_mod.AutomationScore = field(default_factory=automation_mod.AutomationScore)
    risk: risk_mod.RiskScore = field(default_factory=risk_mod.RiskScore)
    prompt_dependencies: dict[str, Any] = field(default_factory=dict)
    knowledge: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "comfyaudit/1",
            "generated": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": self.source,
            "verdict": {
                "commercial_use": self.risk.commercial_verdict,
                "commercial_detail": self.risk.commercial_detail,
                "risk_score": self.risk.score,
                "risk_band": self.risk.band,
                "automation_index": self.automation.index,
                "automation_band": self.automation.band,
            },
            "models": to_jsonable(self.models),
            "prompts": to_jsonable(self.prompts),
            "notes": to_jsonable(self.notes),
            "inputs": to_jsonable(self.inputs),
            "outputs": to_jsonable(self.outputs),
            "custom_node_packs": to_jsonable(self.packs),
            "core_node_types": self.core_node_types,
            "api_node_types": self.api_node_types,
            "missing_models": to_jsonable(self.missing_models),
            "prompt_dependencies": self.prompt_dependencies,
            "automation": {
                "index": self.automation.index,
                "band": self.automation.band,
                "band_detail": self.automation.band_detail,
                "per_run_cost": round(self.automation.per_run_cost, 2),
                "setup_cost": round(self.automation.setup_cost, 2),
                "touchpoints": to_jsonable(self.automation.touchpoints),
                "automation_signals": self.automation.automation_signals,
            },
            "risk": {
                "score": self.risk.score,
                "band": self.risk.band,
                "band_detail": self.risk.band_detail,
                "by_category": self.risk.by_category,
                "counts": self.risk.counts(),
                "findings": to_jsonable(self.risk.findings),
            },
            "knowledge": self.knowledge,
            "diagnostics": self.diagnostics,
        }


def run(path: str, options: AuditOptions | None = None) -> AuditReport:
    opts = options or AuditOptions()
    wf = graph.load(path)
    return run_workflow(wf, opts)


def run_workflow(wf: graph.Workflow, opts: AuditOptions) -> AuditReport:
    report = AuditReport()

    # -- extract -----------------------------------------------------------
    raw_models = models_extract.extract(wf)
    prompts, notes = prompts_extract.extract(wf)
    inputs, outputs = assets_extract.extract(wf)
    packs, core_types, api_types = packs_extract.extract(wf)

    # Prompt-embedded dependencies are real model references too.
    for prompt in prompts:
        raw_models.extend(models_extract.from_prompt_embeddings(prompt.embeddings, prompt))
        raw_models.extend(models_extract.from_prompt_loras(prompt.inline_loras, prompt))

    models = models_extract.deduplicate(raw_models)
    models.sort(key=lambda m: (m.folder, m.filename.lower()))

    report.prompts = sorted(prompts, key=lambda p: (p.polarity, p.node_id))
    report.notes = notes
    report.inputs = inputs
    report.outputs = outputs
    report.packs = packs
    report.core_node_types = core_types
    report.api_node_types = api_types
    report.prompt_dependencies = prompts_extract.collect_prompt_dependencies(prompts)

    # -- local install check ----------------------------------------------
    index = local_mod.ModelIndex()
    if opts.models_dir:
        index = local_mod.scan(opts.models_dir)

    # -- resolve provenance and licences ----------------------------------
    matcher = licences_mod.LicenceMatcher(opts.licences_path or None)
    cache = HttpCache(ttl=opts.cache_ttl) if opts.cache_ttl else HttpCache()
    resolver = Resolver(cache=cache, hf_token=opts.hf_token, enabled=opts.online)

    hashed = 0
    for model in models:
        sha = ""
        if index.available and model.folder != "hosted-api":
            found = index.find(model.filename, model.folder)
            if found is None:
                report.missing_models.append(model)
                model.notes.append("not found under the scanned models directory")
            else:
                model.notes.append(f"found locally: {found.path} ({_human_size(found.size)})")
                if opts.hash_models and opts.online:
                    sha = local_mod.sha256(found.path)
                    if sha:
                        hashed += 1
                        model.notes.append(f"sha256: {sha}")

        model.provenance = resolver.resolve_model(model, sha256=sha)
        model.license = matcher.for_model(model)

        # An upstream licence tag can settle a model the KB did not recognise.
        if model.license.commercial_use == "unknown":
            tag = hf_licence_tag(model.provenance)
            if tag:
                model.license = matcher.apply_hf_licence(
                    model.license, tag, model.provenance.url
                )

    report.models = models

    # -- registry lookups for packs ---------------------------------------
    if opts.online:
        for pack in packs:
            if not pack.registry_id:
                continue
            info = resolver.comfy_registry_pack(pack.registry_id)
            if not info:
                continue
            if info.get("licence"):
                pack.notes.append(f"registry licence: {info['licence']}")
            if info.get("latest_version") and pack.pinned_version:
                if info["latest_version"] != pack.pinned_version:
                    pack.notes.append(
                        f"pinned {pack.pinned_version}, latest published {info['latest_version']}"
                    )
            if info.get("status") and info["status"].lower() not in ("active", "nodestatusactive"):
                pack.notes.append(f"registry status: {info['status']}")

    # -- score -------------------------------------------------------------
    report.automation = automation_mod.score(
        wf, models=models, prompts=prompts, assets=inputs, outputs=outputs,
        notes=notes, packs=packs, api_node_types=api_types,
        missing_models=report.missing_models,
    )
    report.risk = risk_mod.assess(
        wf, models=models, packs=packs, prompts=prompts, assets=inputs,
        outputs=outputs, api_node_types=api_types,
        missing_models=report.missing_models, models_dir_checked=index.available,
    )

    # -- metadata ----------------------------------------------------------
    active = wf.active()
    report.source = {
        "path": wf.source_path or "",
        "name": os.path.basename(wf.source_path or "") or "workflow",
        "format": wf.source_format,
        "nodes_total": len(wf),
        "nodes_active": len(active),
        "nodes_disabled": len(wf) - len(active),
        "subgraphs": wf.subgraph_count,
        "groups": [g.title for g in wf.groups if g.title],
        "frontend_version": wf.extra.get("frontend") or "",
    }
    report.knowledge = {
        "comfyui_catalog_version": catalog.comfyui_version(),
        "licences": licences_mod.kb_metadata(opts.licences_path or None),
        "node_packs_indexed": len(catalog.node_packs()["packs"]),
    }
    report.diagnostics = {
        "parser_warnings": wf.warnings[:40],
        "parser_warning_count": len(wf.warnings),
        "online": opts.online,
        "models_dir": opts.models_dir,
        "models_scanned_locally": index.scanned,
        "models_hashed": hashed,
        "http_cache_hits": cache.hits,
        "http_requests": cache.misses,
        "lookup_errors": cache.errors[:20],
    }
    if index.available:
        report.diagnostics["local_weights_bytes"] = index.total_bytes(
            (m.filename, m.folder) for m in models
        )
    return report


def _human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit not in ("B", "KB") else f"{num:.0f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"
