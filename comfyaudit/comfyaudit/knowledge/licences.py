"""Match model files to licence terms.

Weight files carry no licence metadata, so the mapping is done on the filename
and, where available, the upstream repository id.  Matching is deliberately
conservative: a hit must be a recognisable model-family token, and everything
reports the pattern it matched on plus a confidence, so a reader can see why a
verdict was reached and disagree with it.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from ..records import LicenseInfo, ModelRef

DEFAULT_KB = os.path.join(os.path.dirname(__file__), "data", "licences.json")


@lru_cache(maxsize=8)
def load_kb(path: str | None = None) -> dict[str, Any]:
    """Load the licence knowledge base, optionally merging a studio override.

    A studio file may add or replace both ``licences`` and ``models`` entries.
    Overrides are matched first so a local rule always wins.
    """
    with open(DEFAULT_KB, "r", encoding="utf-8") as fh:
        kb = json.load(fh)

    if path:
        with open(path, "r", encoding="utf-8") as fh:
            extra = json.load(fh)
        kb = dict(kb)
        kb["licences"] = {**kb.get("licences", {}), **extra.get("licences", {})}
        by_id = {m["id"]: m for m in kb.get("models", [])}
        overrides = []
        for entry in extra.get("models", []):
            by_id.pop(entry.get("id"), None)
            overrides.append(entry)
        kb["models"] = overrides + [m for m in kb.get("models", []) if m["id"] in by_id]
        kb["folder_defaults"] = {**kb.get("folder_defaults", {}), **extra.get("folder_defaults", {})}
        kb["overrides_from"] = path
    return kb


def _normalise(text: str) -> str:
    """Lowercase, drop the extension, and flatten separator noise."""
    base = os.path.basename((text or "").strip()).lower()
    base = re.sub(r"\.(safetensors|ckpt|pt|pth|bin|gguf|sft|onnx|engine|pkl|npz)$", "", base)
    return re.sub(r"[\s_.]+", "-", base)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


#: Below this length a squashed pattern is too generic to trust without
#: separators - "ae" would otherwise match every ``*_vae`` file in existence.
MIN_SQUASH_LEN = 6
MIN_TOKEN_LEN = 3


def _token_match(name: str, pattern: str) -> bool:
    """Substring match that has to land on separator boundaries.

    Both strings are already normalised to ``-`` separated tokens.  Requiring a
    boundary on each side is what stops ``clip-l`` matching ``clip-large`` and
    ``ae`` matching ``flux2-vae``, while still allowing the version and
    quantisation suffixes that real filenames carry (``flux1-dev-fp8``).
    """
    if len(pattern) < MIN_TOKEN_LEN:
        return name == pattern
    for match in re.finditer(re.escape(pattern), name):
        left_ok = match.start() == 0 or name[match.start() - 1] == "-"
        right_ok = match.end() == len(name) or name[match.end()] == "-"
        if left_ok and right_ok:
            return True
    return False


class LicenceMatcher:
    """Resolves :class:`~comfyaudit.records.ModelRef` objects to licence terms."""

    def __init__(self, kb_path: str | None = None) -> None:
        self.kb = load_kb(kb_path)
        self.licences: dict[str, Any] = self.kb["licences"]
        self.rules: list[dict[str, Any]] = self.kb["models"]
        self.folder_defaults: dict[str, Any] = self.kb.get("folder_defaults", {})

    # -- public API --------------------------------------------------------

    def for_model(self, ref: ModelRef) -> LicenseInfo:
        """Resolve terms for one model, consulting provenance where it disambiguates."""
        if ref.folder == "hosted-api":
            info = self._build("proprietary-api", matched_on=ref.filename, confidence="high")
            info.summary = (
                f"'{ref.filename}' runs on the vendor's servers. "
                + info.summary
            )
            return info

        hit = self.match_name(ref.filename, ref.repo_id)
        if hit is not None:
            rule, matched_on, confidence = hit
            info = self._build(rule["licence"], matched_on=matched_on, confidence=confidence)
            info.name = f"{info.name} ({rule['family']})"
            for note in rule.get("notes", []):
                info.restrictions.append(note)
            if rule.get("source"):
                info.url = rule["source"]
            return self._apply_provenance_override(info, rule, ref)

        return self._unmatched(ref)

    def _apply_provenance_override(self, info: LicenseInfo, rule: dict[str, Any],
                                   ref: ModelRef) -> LicenseInfo:
        """Let a resolved source correct a filename-only guess.

        Some files are byte-identical across repositories with different terms -
        the FLUX autoencoder ships in both the dev and schnell repos - so where
        we know which repository a copy came from, that beats the filename.
        """
        overrides = rule.get("provenance_overrides") or []
        if not overrides or ref.provenance is None:
            return info
        haystack = f"{ref.provenance.url} {ref.provenance.identifier}".lower()
        for override in overrides:
            needle = str(override.get("url_contains", "")).lower()
            if needle and needle in haystack:
                resolved = self._build(
                    override["licence"],
                    matched_on=f"resolved source {ref.provenance.url}",
                    confidence="medium",
                )
                resolved.name = f"{resolved.name} ({rule['family']})"
                if override.get("note"):
                    resolved.restrictions.append(override["note"])
                resolved.url = ref.provenance.url or resolved.url
                return resolved
        return info

    def match_name(self, filename: str, repo_id: str = "") -> tuple[dict[str, Any], str, str] | None:
        """Best matching rule for a filename, or ``None``.

        The longest matching token wins so that ``flux1-schnell`` is not
        swallowed by a shorter ``flux1`` style pattern.
        """
        name = _normalise(filename)
        squashed = _squash(filename)
        repo = (repo_id or "").strip().lower()

        best: tuple[dict[str, Any], str, str] | None = None
        best_len = 0

        base = os.path.basename((filename or "").strip()).lower()

        for rule in self.rules:
            match = rule.get("match", {})

            for pattern in match.get("repo", []):
                if repo and repo == pattern.lower():
                    return rule, f"repository {repo_id}", "high"

            # An exact-filename rule is for files whose name is the only clue,
            # such as FLUX's bare "ae.safetensors".
            for pattern in match.get("filename_exact", []):
                if base == pattern.lower():
                    return rule, f"exact filename {pattern}", rule.get("confidence", "medium")

            for pattern in match.get("filename", []):
                norm = _normalise(pattern)
                if not norm:
                    continue
                squashed_pattern = _squash(pattern)
                hit = _token_match(name, norm) or (
                    len(squashed_pattern) >= MIN_SQUASH_LEN and squashed_pattern in squashed
                )
                if hit and len(norm) > best_len:
                    best = (rule, pattern, rule.get("confidence", "medium"))
                    best_len = len(norm)

        return best

    # -- internals ---------------------------------------------------------

    def _build(self, licence_id: str, matched_on: str, confidence: str) -> LicenseInfo:
        terms = self.licences.get(licence_id) or self.licences["unknown"]
        return LicenseInfo(
            name=terms.get("name", "Unknown"),
            spdx=terms.get("spdx", ""),
            commercial_use=terms.get("commercial_use", "unknown"),
            fee=terms.get("fee", "unknown"),
            redistribution=terms.get("redistribution", "unknown"),
            output_ownership=terms.get("output_ownership", "unknown"),
            attribution_required=terms.get("attribution_required"),
            restrictions=list(terms.get("restrictions", [])),
            url=terms.get("url", ""),
            matched_on=matched_on,
            confidence=confidence,
            summary=terms.get("summary", ""),
        )

    def _unmatched(self, ref: ModelRef) -> LicenseInfo:
        info = self._build("unknown", matched_on="", confidence="low")
        default = self.folder_defaults.get(ref.folder)
        if default:
            info.summary = default["note"]
        else:
            info.summary = (
                "No licence rule matched this filename. Identify the source before "
                "using it in a commercial delivery."
            )
        return info

    def apply_hf_licence(self, info: LicenseInfo, hf_licence: str, url: str) -> LicenseInfo:
        """Upgrade an unmatched verdict using a licence tag fetched from the hub."""
        if not hf_licence:
            return info
        key = hf_licence.strip().lower()
        alias = {
            "apache-2.0": "apache-2.0",
            "mit": "mit",
            "bsd-3-clause": "bsd-3-clause",
            "cc-by-4.0": "cc-by-4.0",
            "cc-by-nc-4.0": "cc-by-nc-4.0",
            "cc-by-nc-sa-4.0": "cc-by-nc-sa-4.0",
            "creativeml-openrail-m": "creativeml-openrail-m",
            "openrail": "creativeml-openrail-m",
            "openrail++": "creativeml-openrail-plus-plus-m",
            "agpl-3.0": "agpl-3.0-ultralytics",
            "llama3": "llama-community",
            "llama3.1": "llama-community",
            "llama3.2": "llama-community",
        }.get(key)

        if alias:
            resolved = self._build(alias, matched_on=f"hub licence tag '{hf_licence}'", confidence="medium")
            resolved.url = url or resolved.url
            return resolved

        # An unrecognised tag is still better than nothing: report it verbatim
        # rather than pretending we know what it permits.
        info.name = f"{hf_licence} (as tagged upstream)"
        info.matched_on = f"hub licence tag '{hf_licence}'"
        info.confidence = "low"
        info.url = url or info.url
        info.summary = (
            f"Upstream tags this model '{hf_licence}', which is not in the knowledge base. "
            "Read the licence file on the model page before commercial use."
        )
        return info


def kb_metadata(kb_path: str | None = None) -> dict[str, Any]:
    kb = load_kb(kb_path)
    return {
        "version": kb.get("version", ""),
        "checked": kb.get("checked", ""),
        "licence_terms": len(kb.get("licences", {})),
        "model_rules": len(kb.get("models", [])),
        "overrides_from": kb.get("overrides_from", ""),
    }
