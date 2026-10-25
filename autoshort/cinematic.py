"""Frame-exact cinematic shot planning. No cloud service or GPU dependency.

Scene IDs, narrated text and documentary references are immutable. Shot IDs stay
stable across resumptions; human overrides are applied only to their own shot.
"""
from __future__ import annotations

import math
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MediaType(str, Enum):
    animated_image = "animated_image"
    generated_video = "generated_video"
    archive_image = "archive_image"
    archive_video = "archive_video"


Movement = Literal["push_in", "pull_out", "pan_left", "pan_right",
                   "tilt_up", "tilt_down", "diagonal", "still", "reveal"]
Transition = Literal["cut", "fade"]


class Shot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shot_id: str = Field(pattern=r"^s[0-9]{2}-p[0-9]{2}$")
    scene_id: int = Field(ge=1)
    narration_segment: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    frames: int = Field(ge=1)
    media_type: MediaType = MediaType.animated_image
    media_source: str = ""
    visual_prompt: str = ""
    motion_prompt: str = ""
    camera_movement: Movement = "push_in"
    framing: str = "cinematic vertical composition"
    transition: Transition = "cut"
    sound_effects: list[str] = Field(default_factory=list)
    importance: int = Field(default=50, ge=0, le=100)
    continuity_refs: list[str] = Field(default_factory=list)
    is_reconstruction: bool = True
    source_refs: list[str] = Field(default_factory=list)
    video_path: str | None = None
    fallback_reason: str | None = None


class CinematicPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fps: int = Field(gt=0, le=120)
    shots: list[Shot] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [s.shot_id for s in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate cinematic shot IDs")
        return self


MOVEMENTS = ("push_in", "pan_left", "pull_out", "pan_right",
             "tilt_up", "diagonal", "reveal", "tilt_down")


def preview_shots(script, audio=None, production=None):
    """Only advertise shots known to exist from measured TTS duration.

    Without audio, return no planned shots; guessing the count from word length
    would offer edits to non-existing IDs.
    """
    if audio is None:
        return []
    plan = build_plan(script, audio, production or {"fps":25})
    return [{"shot_id": shot.shot_id, "scene_id": shot.scene_id,
             "frames": shot.frames, "duration_seconds": shot.duration_seconds,
             "camera_movement": shot.camera_movement,
             "media_type": shot.media_type.value} for shot in plan.shots]


def build_plan(script, audio, production, overrides=None):
    """Use measured TTS durations, distributing *integer frames* without drift."""
    fps = int(production["fps"])
    seconds_per_shot = max(1.0, float(production.get("shot_seconds", 3.3)))
    overrides = overrides or {}
    narration = script["scenes"]
    audios = audio["scenes"]
    if len(narration) != len(audios):
        raise ValueError("Audio and scene counts differ")
    shots = []
    for si, (scene, voice) in enumerate(zip(narration, audios)):
        if scene["id"] != voice["scene"]:
            raise ValueError("Audio/scene order mismatch")
        frames = max(1, math.ceil(float(voice["duration"]) * fps))
        count = min(3, max(1, math.ceil(frames / (fps * seconds_per_shot))))
        count = min(count, frames)
        sizes = [frames // count + (i < frames % count) for i in range(count)]
        for i, size in enumerate(sizes, 1):
            sid = f"s{scene['id']:02d}-p{i:02d}"
            movement = MOVEMENTS[(si + i - 1) % len(MOVEMENTS)]
            override = overrides.get(sid, {})
            if not isinstance(override, dict):
                raise ValueError("Invalid shot override")
            movement = override.get("camera_movement", movement)
            media = override.get("media_type", "animated_image")
            shot = Shot(shot_id=sid, scene_id=scene["id"],
                        narration_segment=scene["narration"],
                        duration_seconds=round(size / fps, 6), frames=size,
                        media_type=media, camera_movement=movement,
                        visual_prompt=scene.get("image_prompt", ""),
                        motion_prompt=override.get("motion_prompt", "subtle, natural cinematic motion, preserve objects and identity"),
                        video_path=override.get("video_path"),
                        importance=95 if si == 0 and i == 1 else (85 if si == len(narration) - 1 else 55),
                        source_refs=list(scene.get("claim_ids", [])),
                        continuity_refs=[script.get("visual_bible", "")] if script.get("visual_bible") else [])
            shots.append(shot)
    return CinematicPlan(fps=fps, shots=shots)


def camera_filter(width, height, fps, frames, movement):
    """Deterministic zoom/pan with ease-in-out. FFmpeg zoompan input is an image."""
    Shot(shot_id="s01-p01", scene_id=1, narration_segment="test",
         frames=1, duration_seconds=1, camera_movement=movement)
    duration = max(1, frames - 1)
    # Eased progress is monotonic and reproducible across identical frames.
    ease = f"(0.5-0.5*cos(PI*on/{duration}))"
    if movement == "pull_out":
        z = f"1.18-0.12*{ease}"
    elif movement == "still":
        z = "1.06"
    else:
        z = f"1.06+0.12*{ease}"
    if movement == "pan_left":
        x = f"(iw-iw/zoom)*(1-{ease})"
    elif movement in ("pan_right", "diagonal", "reveal"):
        x = f"(iw-iw/zoom)*{ease}"
    else:
        x = "(iw-iw/zoom)/2"
    if movement == "tilt_up":
        y = f"(ih-ih/zoom)*(1-{ease})"
    elif movement in ("tilt_down", "diagonal"):
        y = f"(ih-ih/zoom)*{ease}"
    else:
        y = "(ih-ih/zoom)/2"
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,"
            f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},"
            "format=yuv420p")
