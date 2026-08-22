"""Live provenance lookups: HuggingFace, Civitai and the Comfy Registry.

These are opt-in (``--online``).  Each returns a
:class:`~comfyaudit.records.Provenance` and, where the source states one, a
licence tag that can upgrade an unmatched verdict from the bundled knowledge
base.

Design notes:

* Every lookup is best effort.  If a source is unreachable the audit still
  completes using the offline knowledge base, and the report says which lookups
  failed rather than quietly presenting a thinner result as a complete one.
* Civitai is queried by SHA-256 when a local model directory is available,
  because filename search on Civitai is unreliable - the same filename is
  reused by many unrelated uploads.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

from .. import catalog
from ..records import ModelRef, Provenance
from .cache import HttpCache

HF_API = "https://huggingface.co/api"
CIVITAI_API = "https://civitai.com/api/v1"
COMFY_REGISTRY_API = "https://api.comfy.org"


class Resolver:
    """Bundles the three sources behind one call."""

    def __init__(self, cache: HttpCache | None = None, hf_token: str = "",
                 enabled: bool = True) -> None:
        self.cache = cache or HttpCache()
        self.hf_token = hf_token or os.environ.get("HF_TOKEN", "")
        self.enabled = enabled

    # -- models ------------------------------------------------------------

    def resolve_model(self, ref: ModelRef, sha256: str = "") -> Provenance:
        """Best available provenance for one model reference."""
        prov = self._from_bundled_index(ref)

        if not self.enabled:
            return prov

        if sha256:
            found = self.civitai_by_hash(sha256)
            if found is not None:
                return found

        if ref.repo_id:
            found = self.huggingface_repo(ref.repo_id)
            if found is not None:
                return found

        # The bundled index often already knows the HF repo for this filename.
        repo = _repo_from_url(prov.url) if prov.source == "comfy-manager" else ""
        if repo:
            found = self.huggingface_repo(repo)
            if found is not None:
                found.notes.append(f"matched from the ComfyUI-Manager model index by filename '{ref.filename}'")
                return found

        found = self.huggingface_search(ref.filename)
        if found is not None:
            return found

        return prov

    def _from_bundled_index(self, ref: ModelRef) -> Provenance:
        """Offline provenance from the ComfyUI-Manager model list."""
        known = catalog.known_model(ref.filename)
        if not known:
            return Provenance(source="unknown", confidence="low",
                              notes=["not present in the bundled model index"])
        return Provenance(
            source="comfy-manager",
            identifier=known.get("name", ""),
            url=known.get("reference") or known.get("url", ""),
            resolved_by="bundled-index",
            confidence="medium",
            notes=[n for n in [
                f"base model family: {known['base']}" if known.get("base") else "",
                f"published size: {known['size']}" if known.get("size") else "",
            ] if n],
        )

    # -- HuggingFace -------------------------------------------------------

    def huggingface_repo(self, repo_id: str) -> Provenance | None:
        url = f"{HF_API}/models/{urllib.parse.quote(repo_id, safe='/')}"
        data = self.cache.get_json(url, headers=self._hf_headers())
        if not isinstance(data, dict) or "id" not in data:
            return None
        return _hf_provenance(data)

    def huggingface_search(self, filename: str) -> Provenance | None:
        """Find the repo that actually contains this file.

        A name search alone is not evidence, so each candidate is opened and its
        file list checked before the match is accepted.
        """
        stem = _stem(filename)
        if len(stem) < 4:
            return None
        url = f"{HF_API}/models?search={urllib.parse.quote(stem)}&limit=5"
        results = self.cache.get_json(url, headers=self._hf_headers())
        if not isinstance(results, list):
            return None

        target = os.path.basename(filename).lower()
        for entry in results:
            repo_id = entry.get("id") if isinstance(entry, dict) else None
            if not repo_id:
                continue
            detail = self.cache.get_json(
                f"{HF_API}/models/{urllib.parse.quote(repo_id, safe='/')}",
                headers=self._hf_headers(),
            )
            if not isinstance(detail, dict):
                continue
            siblings = {
                os.path.basename(str(s.get("rfilename", ""))).lower()
                for s in detail.get("siblings", []) if isinstance(s, dict)
            }
            if target in siblings:
                prov = _hf_provenance(detail)
                prov.confidence = "high"
                prov.notes.append(f"repository contains a file named '{target}'")
                return prov

        return None

    def _hf_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.hf_token}"} if self.hf_token else {}

    # -- Civitai -----------------------------------------------------------

    def civitai_by_hash(self, sha256: str) -> Provenance | None:
        url = f"{CIVITAI_API}/model-versions/by-hash/{sha256}"
        data = self.cache.get_json(url)
        if not isinstance(data, dict) or "modelId" not in data:
            return None

        model = self.cache.get_json(f"{CIVITAI_API}/models/{data['modelId']}")
        model = model if isinstance(model, dict) else {}

        prov = Provenance(
            source="civitai",
            identifier=f"model {data.get('modelId')} version {data.get('id')}",
            url=f"https://civitai.com/models/{data.get('modelId')}",
            author=(model.get("creator") or {}).get("username", ""),
            downloads=(model.get("stats") or {}).get("downloadCount"),
            likes=(model.get("stats") or {}).get("thumbsUpCount"),
            last_modified=str(data.get("publishedAt", "")),
            resolved_by="civitai-sha256",
            confidence="high",
            notes=[f"exact file hash match: {sha256[:16]}..."],
        )
        prov.notes.extend(_civitai_permission_notes(model))
        return prov

    # -- Comfy Registry ----------------------------------------------------

    def comfy_registry_pack(self, pack_id: str) -> dict[str, Any] | None:
        """Publisher, latest version and licence for a registry node pack."""
        if not self.enabled or not pack_id:
            return None
        data = self.cache.get_json(f"{COMFY_REGISTRY_API}/nodes/{urllib.parse.quote(pack_id)}")
        if not isinstance(data, dict) or not data.get("id"):
            return None
        latest = data.get("latest_version") or {}
        return {
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "publisher": (data.get("publisher") or {}).get("name", ""),
            "licence": data.get("license", ""),
            "repository": data.get("repository", ""),
            "downloads": data.get("downloads"),
            "latest_version": latest.get("version", ""),
            "latest_released": latest.get("createdAt", ""),
            "status": data.get("status", ""),
        }


# --------------------------------------------------------------------------


def _hf_provenance(data: dict[str, Any]) -> Provenance:
    card = data.get("cardData") or {}
    licence = card.get("license") or ""
    if isinstance(licence, list):
        licence = licence[0] if licence else ""
    if not licence:
        for tag in data.get("tags", []):
            if isinstance(tag, str) and tag.startswith("license:"):
                licence = tag.split(":", 1)[1]
                break

    repo_id = data.get("id", "")
    prov = Provenance(
        source="huggingface",
        identifier=repo_id,
        url=f"https://huggingface.co/{repo_id}",
        author=data.get("author", "") or repo_id.split("/")[0],
        downloads=data.get("downloads"),
        likes=data.get("likes"),
        last_modified=str(data.get("lastModified", "")),
        gated=bool(data.get("gated")),
        resolved_by="huggingface-api",
        confidence="medium",
    )
    if licence:
        prov.notes.append(f"hub licence tag: {licence}")
    if prov.gated:
        prov.notes.append(
            "repository is gated - access must be requested and a token supplied, "
            "which will block an unattended render node"
        )
    return prov


def hf_licence_tag(prov: Provenance) -> str:
    for note in prov.notes:
        if note.startswith("hub licence tag: "):
            return note.split(": ", 1)[1]
    return ""


def _civitai_permission_notes(model: dict[str, Any]) -> list[str]:
    """Civitai records the uploader's own permission flags - report them."""
    notes: list[str] = []
    allow = model.get("allowCommercialUse")
    if isinstance(allow, list):
        notes.append(
            "uploader's commercial-use flags: " + (", ".join(allow) if allow else "none (no commercial use)")
        )
    elif isinstance(allow, str):
        notes.append(f"uploader's commercial-use flag: {allow}")
    if model.get("allowNoCredit") is False:
        notes.append("uploader requires credit")
    if model.get("allowDerivatives") is False:
        notes.append("uploader forbids derivatives (merges, further training)")
    if model.get("nsfw"):
        notes.append("flagged NSFW on Civitai")
    notes.append("Civitai permission flags are set by the uploader and are not a verified licence")
    return notes


def _stem(filename: str) -> str:
    base = os.path.basename(filename or "")
    return re.sub(r"\.[A-Za-z0-9]{2,12}$", "", base)


def _repo_from_url(url: str) -> str:
    match = re.match(r"https?://huggingface\.co/([\w.-]+/[\w.-]+)", url or "")
    return match.group(1) if match else ""
