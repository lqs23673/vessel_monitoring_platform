"""Exercise a running local deployment with synthetic inputs (creates five jobs)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cv2
import httpx
import numpy as np
from websockets.sync.client import connect

from app.config import get_settings
from app.inference.frame_inference import FrameInferenceService
from app.inference.model_registry import ModelRegistry
from app.schemas import TaskKind


def run_job(client, filename: str, content: bytes, task: str, *, tracking=False):
    response = client.post("/api/jobs", files={"files": (filename, content)}, data={
        "task": task, "enable_tracking": str(tracking).lower(),
        "visualize": "true", "max_frames": "3",
    })
    response.raise_for_status()
    job = response.json()
    deadline = time.monotonic() + 180
    while job["status"] in {"queued", "running"}:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Job timed out: {job['id']}")
        time.sleep(0.5)
        response = client.get(f"/api/jobs/{job['id']}")
        response.raise_for_status()
        job = response.json()
    if job["status"] != "completed" or job.get("error"):
        raise RuntimeError(f"Job failed: {job}")
    for item in job["items"]:
        if item["status"] != "completed" or item.get("error"):
            raise RuntimeError(f"Item failed: {item}")
        for key in ("result_uri", "visual_uri"):
            uri = item.get(key)
            if uri:
                result = client.get(f"/api/jobs/{job['id']}/files/{uri}")
                result.raise_for_status()
                if not result.content:
                    raise RuntimeError(f"Empty artifact: {uri}")
                if uri.endswith(".json"):
                    records = [result.json()["frame"]]
                elif uri.endswith(".jsonl"):
                    records = [json.loads(line) for line in result.text.splitlines() if line]
                else:
                    records = []
                if any(record.get("errors") for record in records):
                    raise RuntimeError(f"Inference errors: {records}")
    csv_result = client.get(f"/api/jobs/{job['id']}/files/result.csv")
    csv_result.raise_for_status()
    summary = {"task": task, "tracking": tracking, "job_id": job["id"], "status": job["status"]}
    print(json.dumps(summary), flush=True)
    return summary


def main():
    settings = get_settings()
    if settings.device != "cuda" or settings.demo_mode:
        raise RuntimeError("This check requires DEVICE=cuda and DEMO_MODE=false")
    output = ROOT / "data" / "deployment-check"
    output.mkdir(parents=True, exist_ok=True)
    report = {"jobs": []}
    frame = np.full((192, 320, 3), (150, 95, 50), dtype=np.uint8)
    cv2.rectangle(frame, (60, 60), (260, 130), (175, 175, 175), -1)
    cv2.putText(frame, "DEPLOY TEST", (75, 105), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
    ok, image = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    video = output / "smoke.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 5, (320, 192))
    if not writer.isOpened():
        raise RuntimeError("Video encoding failed")
    try:
        for _ in range(3):
            writer.write(frame)
    finally:
        writer.release()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg not available")
    encoded = output / "smoke-h264.mp4"
    subprocess.run([ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", str(video),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(encoded)], check=True, timeout=30)
    report["ffmpeg_h264"] = encoded.stat().st_size > 0
    models = ModelRegistry(settings)
    try:
        models.load()
        report["model_providers"] = {
            name: getattr(models, name).session.get_providers()
            for name in ("ship_detector", "draft_predictor", "name_recognizer")
        }
        service = FrameInferenceService(models)
        for task in TaskKind:
            result = service.infer(frame, task_id="deployment-smoke", source_filename="smoke.jpg",
                                   task=task, observed_at=datetime.now(timezone.utc))
            if result.errors:
                raise RuntimeError(f"Adapter errors for {task}: {result.errors}")
    finally:
        models.release()
    with httpx.Client(base_url="http://127.0.0.1:8010", timeout=60, trust_env=False) as client:
        response = client.get("/api/health")
        response.raise_for_status()
        health = response.json()
        if health["status"] != "healthy" or health["device"] != "cuda":
            raise RuntimeError(f"Unhealthy deployment: {health}")
        report["health"] = health
        for path in ("/", "/offline"):
            page = client.get(f"http://127.0.0.1:5173{path}")
            page.raise_for_status()
            if '<div id="app">' not in page.text:
                raise RuntimeError(f"UI document missing: {path}")
        proxy = client.get("http://127.0.0.1:5173/api/health")
        proxy.raise_for_status()
        if proxy.json()["device"] != "cuda":
            raise RuntimeError("Frontend API proxy is not using the GPU backend")
        with connect("ws://127.0.0.1:5173/ws/realtime", open_timeout=10, proxy=None) as ws:
            if json.loads(ws.recv(timeout=10))["type"] != "connected":
                raise RuntimeError("WebSocket connection failed")
        report["frontend_and_websocket"] = "passed"
        for task in ("region_detection", "ship_name_recognition", "draft_estimation", "full_pipeline"):
            report["jobs"].append(run_job(client, "deployment-smoke.jpg", image.tobytes(), task))
        report["jobs"].append(run_job(client, "deployment-smoke.avi", video.read_bytes(), "full_pipeline", tracking=True))
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Deployment check passed: {output / 'report.json'}")


if __name__ == "__main__":
    main()
