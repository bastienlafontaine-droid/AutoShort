"""Guided cinematic video contracts with synthetic files, no GPU or ComfyUI."""
from pathlib import Path
from copy import deepcopy
import pytest
from autoshort import core, live, live_generation
from autoshort.cinematic import preview_shots


def make_guided(tmp_path, monkeypatch):
    root = tmp_path / "run"
    root.mkdir()
    monkeypatch.setattr(live, "run_info", lambda rid: {"status": "AWAITING_APPROVAL", "cancel": 0})
    monkeypatch.setattr(live, "update", lambda *a, **kw: None)
    board = {"visual_bible": "old photo", "scenes": [
        {"id": 1, "narration": "Short documentary", "claim_ids": ["c1"], "image_prompt": "old train"}
    ]}
    core.dump(root / "config.json", {"production": {"fps": 25, "shot_seconds": 3.3,
        "video_generation": {"enabled": True}}})
    core.dump(root / "audio.json", {"scenes": [{"scene": 1, "duration": 7.1}]})
    img = root / "guided_media" / "image.png"
    img.parent.mkdir()
    img.write_bytes(b"fake image")
    w = live.initial()
    w["stage"] = "images"
    w["chosen"]["storyboard"] = "board"
    w["proposals"]["storyboard"].append({"id": "board", "data": {"script": board}})
    w["proposals"]["images"].append({"id": "image", "target": 1,
        "data": {"path": str(img), "sha256": core.digest(img)}})
    w["image_choices"]["1"] = "image"
    core.dump(root / "live.json", w)
    return root


def test_only_measured_shots(tmp_path, monkeypatch):
    folder = make_guided(tmp_path, monkeypatch)
    w = live.snapshot(folder)
    shots = live.measured_shots(folder, w)
    assert [s["shot_id"] for s in shots] == ["s01-p01", "s01-p02", "s01-p03"]
    assert sum(s["frames"] for s in shots) == 178
    assert preview_shots(w["proposals"]["storyboard"][0]["data"]["script"]) == []
    with pytest.raises(ValueError, match="absent"):
        live.configure_shot(folder, "run", "s01-p04", "still", "animated_image")


def test_generate_then_select_before_render(tmp_path, monkeypatch):
    folder = make_guided(tmp_path, monkeypatch)
    job_id = live.schedule_video(folder, "run", "s01-p01", "gentle camera movement")
    w = live.snapshot(folder)
    job = next(x for x in w["jobs"] if x["id"] == job_id)
    assert job["kind"] == "video" and job["base"]["image_id"] == "image"
    assert w["stage"] == "images"
    out = folder / "generated_clips" / (job_id + ".mp4")
    out.parent.mkdir()
    out.write_bytes(b"synthetic mp4 placeholder")
    core.dump(folder / "live_results" / f"{job_id}.json", {
        "path": str(out), "sha256": core.digest(out), "shot_id": "s01-p01", "image_id": "image"})
    w["jobs"] = [dict(j, status="done") if j["id"] == job_id else j for j in w["jobs"]]
    core.dump(folder / "live.json", w)
    live.select_video(folder, "run", "s01-p01", job_id)
    assert live.snapshot(folder)["video_choices"]["s01-p01"] == job_id
    assert live.available_videos(folder, live.snapshot(folder))[job_id]["shot_id"] == "s01-p01"
    live.validate_images(folder, "run")
    assert live.snapshot(folder)["stage"] == "short"


def test_wrong_image_cannot_be_used_as_video_reference(tmp_path, monkeypatch):
    folder = make_guided(tmp_path, monkeypatch)
    jid = live.schedule_video(folder, "run", "s01-p01", "gentle camera movement")
    w = live.snapshot(folder)
    w["jobs"][0]["status"] = "done"
    w["image_choices"]["1"] = "different image"
    core.dump(folder / "live.json", w)
    with pytest.raises(ValueError, match="ancienne image"):
        live.select_video(folder, "run", "s01-p01", jid)


def test_video_requires_enabled_backend_and_real_audio(tmp_path, monkeypatch):
    folder = make_guided(tmp_path, monkeypatch)
    cfg = core.read(folder / "config.json")
    cfg["production"]["video_generation"]["enabled"] = False
    core.dump(folder / "config.json", cfg)
    with pytest.raises(ValueError, match="Activer"):
        live.schedule_video(folder, "run", "s01-p01", "gentle camera movement")
    cfg["production"]["video_generation"]["enabled"] = True
    core.dump(folder / "config.json", cfg)
    (folder / "audio.json").unlink()
    with pytest.raises(ValueError, match="voix"):
        live.schedule_video(folder, "run", "s01-p01", "gentle camera movement")
