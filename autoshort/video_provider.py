"""Optional local ComfyUI I2V provider. API workflow is user-supplied/exported.

The provider never downloads models or trusts an arbitrary URL. No cloud fallback.
"""
from __future__ import annotations
import json, time
from pathlib import Path
from urllib.parse import urlparse
import httpx


class VideoGenerationError(RuntimeError):
    pass


class DisabledVideoProvider:
    def available(self): return False
    def capabilities(self): return {"image_to_video": False}
    def generate(self, **kwargs): raise VideoGenerationError("Video generation disabled")


class ComfyUIVideoProvider:
    def __init__(self, url="http://127.0.0.1:8188", workflow_path=""):
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.port != 8188:
            raise ValueError("Only local ComfyUI port 8188 is supported")
        self.url = url.rstrip("/")
        self.workflow_path = workflow_path

    def available(self):
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                return client.get(self.url + "/system_stats").status_code == 200
        except httpx.HTTPError:
            return False

    def capabilities(self):
        return {"image_to_video": bool(self.workflow_path and Path(self.workflow_path).is_file()),
                "requires_exported_workflow": True}

    def diagnose(self):
        result = {"server": self.available(), "workflow": self.capabilities()["image_to_video"]}
        if result["server"]:
            with httpx.Client(timeout=10, trust_env=False) as client:
                result["nodes"] = sorted(client.get(self.url + "/object_info").json())
        return result

    def generate(self, image, output, *, timeout=600, cancellation=None):
        """Needs an actual ComfyUI API-exported workflow and existing LoadImage node.

        The workflow must have its own sampler, video model, output and settings.
        No invented sampler, node type, or undocumented model arguments.
        """
        if not self.capabilities()["image_to_video"]:
            raise VideoGenerationError("Missing exported ComfyUI API workflow")
        source = Path(image)
        if not source.is_file():
            raise VideoGenerationError("Source image missing")
        workflow = json.loads(Path(self.workflow_path).read_text(encoding="utf-8"))
        loaders = [v for v in workflow.values() if isinstance(v, dict) and v.get("class_type") == "LoadImage"]
        if len(loaders) != 1:
            raise VideoGenerationError("Workflow needs exactly one LoadImage node")
        with httpx.Client(timeout=45, trust_env=False) as client:
            with source.open("rb") as f:
                reply = client.post(self.url + "/upload/image", files={"image": (source.name, f, "image/png")}, data={"overwrite": "false"})
            reply.raise_for_status()
            loaders[0]["inputs"]["image"] = reply.json()["name"]
            reply = client.post(self.url + "/prompt", json={"prompt": workflow})
            reply.raise_for_status()
            pid = reply.json()["prompt_id"]
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if cancellation:
                cancellation()
            with httpx.Client(timeout=20, trust_env=False) as client:
                result = client.get(self.url + "/history/" + pid)
                result.raise_for_status()
                history = result.json().get(pid)
            if history:
                for node in history.get("outputs", {}).values():
                    for media in node.get("gifs", []) + node.get("videos", []):
                        name = media.get("filename")
                        if not name: continue
                        with httpx.Client(timeout=60, trust_env=False) as client:
                            response = client.get(self.url + "/view", params={"filename": name, "subfolder": media.get("subfolder", ""), "type": media.get("type", "output")})
                            response.raise_for_status()
                        destination = Path(output)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        tmp = destination.with_suffix(".pending")
                        tmp.write_bytes(response.content)
                        try:
                            from .render import probe
                            data = probe(tmp)
                            if not any(s.get("codec_type") == "video" for s in data.get("streams", [])):
                                raise VideoGenerationError("ComfyUI output is not video")
                            tmp.replace(destination)
                            return {"path": str(destination), "prompt_id": pid, "metadata": data}
                        finally:
                            tmp.unlink(missing_ok=True)
                raise VideoGenerationError("ComfyUI finished without video output; verify SaveVideo node")
            time.sleep(2)
        raise VideoGenerationError("ComfyUI generation timed out")


def provider_from_config(production):
    video = production.get("video_generation", {})
    if not video.get("enabled", False):
        return DisabledVideoProvider()
    return ComfyUIVideoProvider(video.get("url", "http://127.0.0.1:8188"), video.get("workflow_path", ""))
