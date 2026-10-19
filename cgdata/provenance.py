"""Provenance for dataset clips, recorded with ComfyAudit's shot history.

Every clip, asset kit and look gets a ComfyAudit history: a hash-chained,
optionally signed and ledger-witnessed record. Pipeline steps go in as
machine entries (``rendered``), which credit nobody. The four approval gates
Doug confirmed on 2026-10-18 go in as a named person's decision:

    asset_approved   a procedural kit / asset family accepted (per asset)
    look_locked      a look (shading, lighting, comp finish) accepted (per look)
    shot_curated     a clip kept for, or cut from, the dataset (per clip)
    comp_finished    a clip's finished comp accepted (per clip)

A decision must carry a note saying why. ComfyAudit does not count blank
notes, and the reasons are the evidence of creative control.

ComfyAudit is used as-is, so its integrity rules apply unchanged: the chain is
the authority, mixed signed/unsigned entries are damage, a damaged history
cannot be extended, and signing proves the studio key, not the person.
Secrets come from ComfyAudit's environment variables only:
COMFYAUDIT_HISTORY_KEY (or _KEY_FILE, _KEYRING) and COMFYAUDIT_HISTORY_LEDGER.

ComfyAudit must import as ``comfyaudit``. If it isn't installed, set
COMFYAUDIT_PATH to the folder that contains the ``comfyaudit`` folder, e.g.
C:\\ai\\ComfyUI\\custom_nodes.

Layout:
    <shot>/provenance/history.json                  one per clip
    <library>/provenance/assets/<name>.history.json one per asset kit
    <library>/provenance/looks/<name>.history.json  one per look
"""

import json
import os
import sys
from pathlib import Path

TOOL = "cgdata pipeline"
PROJECT = "cgdata"

GATES = {
    "asset_approved": "Asset approved",
    "look_locked": "Look locked",
    "shot_curated": "Shot curated",
    "comp_finished": "Comp finished",
}
SHOT_GATES = ("shot_curated", "comp_finished")
DECISIONS = {"approve": "approved", "reject": "rejected"}

# ComfyAudit's history is attached to a workflow document. Dataset records
# have no ComfyUI graph, so they use an empty one; every entry snapshots the
# same (empty) graph and the substance lives in each entry's data and outputs.
_EMPTY_DOC = {"nodes": [], "links": [], "extra": {}, "version": 0.4}


def comfyaudit():
    """Import ComfyAudit's history module, honoring COMFYAUDIT_PATH."""
    extra = os.environ.get("COMFYAUDIT_PATH")
    if extra and extra not in sys.path:
        sys.path.insert(0, extra)
    try:
        from comfyaudit.core import history
    except ImportError as e:
        raise RuntimeError(
            "ComfyAudit is not importable as 'comfyaudit'. Set COMFYAUDIT_PATH to the "
            "folder containing it (e.g. C:\\ai\\ComfyUI\\custom_nodes).") from e
    return history


def shot_history_path(shot_dir):
    return Path(shot_dir) / "provenance" / "history.json"


def subject_history_path(library, kind, name):
    if kind not in ("assets", "looks"):
        raise ValueError("kind must be 'assets' or 'looks'")
    return Path(library) / "provenance" / kind / f"{name}.history.json"


def _load(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else None


def _save(path, history):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=1))
    os.replace(tmp, path)


def _keys_for(H, person=""):
    keys = H.Keys.from_environment()
    if person:
        keys = keys.for_person(person) or keys
    return keys


def _stamp(path, *, event, actor, name, external_ids, note="", outputs=(), payload=None):
    H = comfyaudit()
    history = _load(path)
    keys = _keys_for(H, actor.name if event in DECISIONS.values() else "")
    result = H.stamp(_EMPTY_DOC, event=event, actor=actor, note=note, outputs=list(outputs),
                     keys=keys, name=name, project=PROJECT, external_ids=external_ids,
                     ledger=os.environ.get("COMFYAUDIT_HISTORY_LEDGER", ""),
                     data_payload=payload or {}, history=history)
    _save(path, result.history)
    return result.entry


def _machine():
    H = comfyaudit()
    return H.Actor(name="cgdata", tool=TOOL, declared_by="explicit")


def _person(name, role=""):
    if not name.strip():
        raise ValueError("a gate decision needs the name of the person making it")
    H = comfyaudit()
    actor = H.Actor.current(name=name, role=role, tool=TOOL)
    actor.declared_by = "explicit"
    return actor


def _files(meta, prefixes):
    """Output rows from meta.json's file list (already hashed by qa.py)."""
    return [{"file": f["path"], "sha256": f.get("sha256"), "bytes": f["bytes"]}
            for f in meta["files"] if f["path"].split("/")[0] in prefixes]


# ------------------------------------------------------------- machine steps

def record_render(shot_dir, meta):
    """The Blender render and QA, as a machine step: spec, scene and renders."""
    shot_dir = Path(shot_dir)
    payload = {
        "step": "render",
        "renderer": meta["renderer"],
        "spec_seed": meta["spec"]["seed"],
        "qa_passed": meta["qa"]["passed"],
        "uses": meta.get("uses", {}),
    }
    files = _files(meta, ("spec.json", "scene.json", "scene", "renders"))
    return _stamp(shot_history_path(shot_dir), event="rendered", actor=_machine(),
                  name=meta["id"], external_ids={"cgdata": meta["id"]},
                  outputs=files, payload=payload)


def record_comp(shot_dir, meta):
    """The generated Nuke comp, as a machine step: script and final frames."""
    files = _files(meta, ("comp", "final"))
    if not files:
        return None
    return _stamp(shot_history_path(shot_dir), event="rendered", actor=_machine(),
                  name=meta["id"], external_ids={"cgdata": meta["id"]},
                  outputs=files, payload={"step": "comp", "params": meta["comp"]["params"]})


# ---------------------------------------------------------------- decisions

def decide(path, *, gate, decision, person, note, name, role="", evidence=()):
    """Record one gate decision by a named person. Returns the entry."""
    if gate not in GATES:
        raise ValueError(f"unknown gate {gate!r}; expected one of {', '.join(GATES)}")
    if decision not in DECISIONS:
        raise ValueError("decision must be 'approve' or 'reject'")
    if not note.strip():
        raise ValueError("a gate decision needs a note saying why: the reasons are the "
                         "evidence of creative control, and blank notes don't count")
    return _stamp(path, event=DECISIONS[decision], actor=_person(person, role),
                  name=name, external_ids={"cgdata": name}, note=note.strip(),
                  outputs=list(evidence), payload={"gate": gate, "gate_label": GATES[gate]})


def decide_shot(shot_dir, *, gate, decision, person, note, role=""):
    if gate not in SHOT_GATES:
        raise ValueError(f"{gate} is decided per asset or look, not per shot")
    shot_dir = Path(shot_dir)
    evidence = [p for p in (shot_dir / "qa").glob("*.png")] if gate == "shot_curated" else []
    entry = decide(shot_history_path(shot_dir), gate=gate, decision=decision, person=person,
                   note=note, name=shot_dir.name, role=role,
                   evidence=[str(p) for p in evidence])
    refresh_meta(shot_dir)
    return entry


def decide_subject(library, kind, subject, *, decision, person, note, role="", evidence=()):
    gate = "asset_approved" if kind == "assets" else "look_locked"
    return decide(subject_history_path(library, kind, subject), gate=gate, decision=decision,
                  person=person, note=note, name=subject, role=role, evidence=evidence)


# ----------------------------------------------------------------- reading

def recorded_steps(shot_dir):
    """Machine steps already in a shot's history, e.g. {"render", "comp"}."""
    history = _load(shot_history_path(shot_dir)) or {}
    return {(e.get("data") or {}).get("step") for e in history.get("entries", [])
            if e["event"] == "rendered"} - {None}


def gate_status(history):
    """Latest decision per gate: {gate: {"decision", "by", "at", "note"}}."""
    status = {}
    for e in (history or {}).get("entries", []):
        gate = (e.get("data") or {}).get("gate")
        if gate and e["event"] in DECISIONS.values():
            status[gate] = {"decision": "approve" if e["event"] == "approved" else "reject",
                            "by": e["actor"].get("name", ""), "at": e["at"], "note": e["note"]}
    return status


def summary(path):
    """Verification and gate status for a history file, for meta.json."""
    H = comfyaudit()
    history = _load(path)
    if not history:
        return {"history": None, "assurance": "absent"}
    v = H.verify({}, keys=H.Keys.from_environment(),
                 ledger=os.environ.get("COMFYAUDIT_HISTORY_LEDGER", ""), history=history)
    entries = history["entries"]
    return {
        "schema": history["schema"],
        "assurance": v.assurance,
        "problems": v.problems,
        "entries": len(entries),
        "head": entries[-1]["hash"] if entries else "",
        "human_decisions": sum(1 for e in entries if e["event"] in DECISIONS.values()),
        "gates": gate_status(history),
    }


def record_html(path, out):
    """ComfyAudit's provenance record (HTML) for one history, for buyers and legal."""
    comfyaudit()
    from comfyaudit.core.report import history_html
    history = _load(path)
    if not history:
        raise ValueError(f"no history at {path}")
    Path(out).write_text(history_html.render(
        history, ledger=os.environ.get("COMFYAUDIT_HISTORY_LEDGER", "")), encoding="utf-8")
    return out


def refresh_meta(shot_dir):
    """Write the shot's current provenance summary into its meta.json."""
    shot_dir = Path(shot_dir)
    meta_path = shot_dir / "meta.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text())
    meta["provenance"] = {"history": "provenance/history.json",
                          **summary(shot_history_path(shot_dir))}
    meta_path.write_text(json.dumps(meta, indent=2))
