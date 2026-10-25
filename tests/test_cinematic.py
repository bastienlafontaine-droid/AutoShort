"""Cinematic V2 invariants; CPU only (no Ollama, FFmpeg or ComfyUI service)."""
import pytest
from pydantic import ValidationError

from autoshort.cinematic import Shot, CinematicPlan, build_plan, camera_filter
from autoshort.video_provider import DisabledVideoProvider, ComfyUIVideoProvider, VideoGenerationError


def sample():
    script = {"visual_bible": "Dark archival illustration", "scenes": [
        {"id": 1, "narration": "A documented incident happened.", "claim_ids": ["c1"], "image_prompt": "Old machine"},
        {"id": 2, "narration": "The inquiry found the cause.", "claim_ids": ["c2"], "image_prompt": "Old papers"},
    ]}
    audio = {"scenes": [{"scene": 1, "duration": 7.11}, {"scene": 2, "duration": 2.0}]}
    return script, audio


def test_frame_exact_plan_and_stable_identity():
    script, audio = sample()
    result = build_plan(script, audio, {"fps": 25, "shot_seconds": 3.3})
    assert [s.shot_id for s in result.shots] == [
        "s01-p01", "s01-p02", "s01-p03", "s02-p01"]
    assert sum(s.frames for s in result.shots if s.scene_id == 1) == 178
    assert sum(s.frames for s in result.shots if s.scene_id == 2) == 50
    assert all(s.narration_segment == script["scenes"][s.scene_id-1]["narration"] for s in result.shots)
    assert [s.source_refs for s in result.shots] == [["c1"]]*3 + [["c2"]]
    assert build_plan(script, audio, {"fps": 25}).model_dump() == build_plan(script,audio,{"fps":25}).model_dump()


def test_overrides_are_strict_and_not_inherited():
    script, audio = sample()
    opts = {"s01-p02": {"camera_movement": "tilt_up", "media_type": "generated_video"}}
    plan = build_plan(script, audio, {"fps": 25}, opts)
    assert plan.shots[1].camera_movement == "tilt_up"
    assert plan.shots[1].media_type.value == "generated_video"
    assert plan.shots[0].media_type.value == "animated_image"
    with pytest.raises(ValidationError):
        build_plan(script,audio,{"fps":25},{"s01-p01":{"camera_movement":"invalid"}})
    with pytest.raises(ValidationError):
        Shot(shot_id="bad",scene_id=1,narration_segment="x",frames=1,duration_seconds=1)


def test_audio_scene_mismatch_is_not_hidden():
    script,audio=sample()
    audio["scenes"][1]["scene"]=99
    with pytest.raises(ValueError,match="order"):
        build_plan(script,audio,{"fps":25})


def test_camera_filter_deterministic_and_restricted():
    a=camera_filter(1080,1920,25,80,"pan_left")
    assert a==camera_filter(1080,1920,25,80,"pan_left")
    assert "zoompan=" in a and "cos(" in a
    with pytest.raises(ValidationError):
        camera_filter(1080,1920,25,80,"invalid")


def test_provider_disabled_and_loopback_only():
    p=DisabledVideoProvider()
    assert not p.available()
    with pytest.raises(VideoGenerationError):
        p.generate()
    for url in ["http://example.com:8188", "https://127.0.0.1:8188", "http://127.0.0.1:5555"]:
        with pytest.raises(ValueError):
            ComfyUIVideoProvider(url)
    assert not ComfyUIVideoProvider().capabilities()["image_to_video"]


def test_duplicate_shots_refused():
    script,audio=sample()
    plan=build_plan(script,audio,{"fps":25})
    with pytest.raises(ValidationError):
        CinematicPlan(fps=25,shots=[plan.shots[0],plan.shots[0]])
