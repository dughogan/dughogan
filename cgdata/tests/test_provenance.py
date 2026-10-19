"""cgdata provenance on ComfyAudit histories. Needs ComfyAudit importable
(directly, or via COMFYAUDIT_PATH); skipped otherwise."""

import json

import pytest

from cgdata import provenance

try:
    H = provenance.comfyaudit()
except RuntimeError:
    pytest.skip("ComfyAudit not importable", allow_module_level=True)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("COMFYAUDIT_HISTORY_KEY", "COMFYAUDIT_HISTORY_KEY_FILE",
                "COMFYAUDIT_HISTORY_KEYRING", "COMFYAUDIT_HISTORY_LEDGER",
                "COMFYAUDIT_HISTORY_ENC_KEY", "COMFYAUDIT_HISTORY_CONFIDENTIALITY"):
        monkeypatch.delenv(var, raising=False)


def make_shot(tmp_path, shot_id="CG_000001", comp=False):
    shot = tmp_path / "cg" / shot_id
    (shot / "renders").mkdir(parents=True)
    (shot / "qa").mkdir()
    (shot / "renders" / f"{shot_id}_light.1001.exr").write_bytes(b"exr")
    (shot / "qa" / f"{shot_id}_passes.png").write_bytes(b"png")
    files = [{"path": f"renders/{shot_id}_light.1001.exr", "bytes": 3, "sha256": "a" * 64},
             {"path": "spec.json", "bytes": 2, "sha256": "b" * 64}]
    if comp:
        files.append({"path": f"final/{shot_id}_final.1001.exr", "bytes": 3, "sha256": "c" * 64})
    meta = {"id": shot_id, "renderer": "Cycles", "spec": {"seed": 1}, "qa": {"passed": True},
            "files": files, "comp": {"rendered": comp, "params": {"style": "toon"}}}
    (shot / "meta.json").write_text(json.dumps(meta))
    return shot, meta


def test_render_is_a_machine_step_and_credits_nobody(tmp_path):
    shot, meta = make_shot(tmp_path)
    entry = provenance.record_render(shot, meta)
    assert entry["event"] == "rendered"
    assert entry["breakpoints"] == []
    assert entry["actor"]["name"] == "cgdata"
    assert {o["file"] for o in entry["outputs"]} == {"renders/CG_000001_light.1001.exr", "spec.json"}
    assert provenance.recorded_steps(shot) == {"render"}


def test_comp_step_only_lists_comp_outputs(tmp_path):
    shot, meta = make_shot(tmp_path, comp=True)
    provenance.record_render(shot, meta)
    entry = provenance.record_comp(shot, meta)
    assert [o["file"] for o in entry["outputs"]] == ["final/CG_000001_final.1001.exr"]
    assert provenance.recorded_steps(shot) == {"render", "comp"}


def test_shot_decision_is_a_named_selection_with_evidence(tmp_path):
    shot, meta = make_shot(tmp_path)
    provenance.record_render(shot, meta)
    entry = provenance.decide_shot(shot, gate="shot_curated", decision="approve",
                                   person="Doug Hogan", note="Hero reads clearly")
    assert entry["event"] == "approved"
    assert entry["actor"]["name"] == "Doug Hogan"
    assert "selection" in entry["breakpoints"]
    assert entry["data"]["gate"] == "shot_curated"
    assert entry["outputs"][0]["file"] == "CG_000001_passes.png"
    summary = json.loads((shot / "meta.json").read_text())["provenance"]
    assert summary["gates"]["shot_curated"]["decision"] == "approve"
    assert summary["human_decisions"] == 1
    assert summary["assurance"] == "consistency"


@pytest.mark.parametrize("kwargs, message", [
    ({"note": "   "}, "needs a note"),
    ({"person": ""}, "name of the person"),
    ({"decision": "maybe"}, "approve' or 'reject"),
    ({"gate": "asset_approved"}, "per asset or look"),
])
def test_bad_decisions_are_refused(tmp_path, kwargs, message):
    shot, _ = make_shot(tmp_path)
    args = {"gate": "shot_curated", "decision": "approve", "person": "Doug Hogan", "note": "ok"}
    with pytest.raises(ValueError, match=message):
        provenance.decide_shot(shot, **{**args, **kwargs})


def test_asset_and_look_histories_are_separate(tmp_path):
    provenance.decide_subject(tmp_path, "assets", "city_kit_v1", decision="approve",
                              person="Doug Hogan", note="Enough variety")
    provenance.decide_subject(tmp_path, "looks", "toon_v2", decision="reject",
                              person="Doug Hogan", note="Ramp too soft")
    asset = provenance.summary(provenance.subject_history_path(tmp_path, "assets", "city_kit_v1"))
    look = provenance.summary(provenance.subject_history_path(tmp_path, "looks", "toon_v2"))
    assert asset["gates"]["asset_approved"]["decision"] == "approve"
    assert look["gates"]["look_locked"]["decision"] == "reject"


def test_signed_and_witnessed(tmp_path, monkeypatch):
    monkeypatch.setenv("COMFYAUDIT_HISTORY_KEY", "studio-secret")
    monkeypatch.setenv("COMFYAUDIT_HISTORY_LEDGER", str(tmp_path / "ledger.jsonl"))
    shot, meta = make_shot(tmp_path)
    provenance.record_render(shot, meta)
    provenance.decide_shot(shot, gate="shot_curated", decision="approve",
                           person="Doug Hogan", note="Keep")
    assert provenance.summary(provenance.shot_history_path(shot))["assurance"] == "witnessed"


def test_edited_decision_is_damage_and_blocks_new_entries(tmp_path):
    shot, meta = make_shot(tmp_path)
    provenance.record_render(shot, meta)
    provenance.decide_shot(shot, gate="shot_curated", decision="reject",
                           person="Doug Hogan", note="Too dark")
    path = provenance.shot_history_path(shot)
    history = json.loads(path.read_text())
    history["entries"][1]["event"] = "approved"
    path.write_text(json.dumps(history))
    summary = provenance.summary(path)
    assert summary["assurance"] == "none"
    assert summary["problems"]
    with pytest.raises(ValueError, match="damaged"):
        provenance.decide_shot(shot, gate="comp_finished", decision="approve",
                               person="Doug Hogan", note="Looks finished")


def test_record_html(tmp_path):
    shot, meta = make_shot(tmp_path)
    provenance.record_render(shot, meta)
    provenance.decide_shot(shot, gate="shot_curated", decision="approve",
                           person="Doug Hogan", note="Keep")
    out = provenance.record_html(provenance.shot_history_path(shot), tmp_path / "r.html")
    html = out.read_text()
    assert "Doug Hogan" in html and "CG_000001" in html


def test_caption_edit_is_logged_and_overrides(tmp_path):
    shot, meta = make_shot(tmp_path)
    spec = {"seed": 5, "shot_id": "CG_000001", "style": "photoreal",
            "environment": {"type": "meadow"}, "hero": {"type": "stone_monolith", "hue": 0.1},
            "lighting": {"time_of_day": "noon"}, "camera": {"move": "orbit"},
            "atmosphere": {"fog": False}}
    (shot / "spec.json").write_text(json.dumps(spec))
    (shot / "scene.json").write_text(json.dumps({"camera": {"focal_mm": 35, "fstop": 4.0}}))
    provenance.record_render(shot, meta)
    entry = provenance.edit_caption(shot, key="long", text="A monolith at noon.", person="Doug Hogan")
    assert entry["event"] == "note" and entry["data"]["text"] == "A monolith at noon."
    assert "note" in entry["breakpoints"]
    meta_now = json.loads((shot / "meta.json").read_text())
    assert meta_now["captions"]["long"] == "A monolith at noon."
    assert meta_now["captions"]["edited"]["long"]["by"] == "Doug Hogan"
    assert meta_now["provenance"]["caption_edits"] == 1
    with pytest.raises(ValueError, match="empty"):
        provenance.edit_caption(shot, key="long", text="  ", person="Doug Hogan")
