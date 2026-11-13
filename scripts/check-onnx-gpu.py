"""Run every delivered ONNX model and prove CUDA kernel execution via profiling."""
from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
os.environ["NVIDIA_TF32_OVERRIDE"] = "0"

import numpy as np
import onnxruntime as ort
import yaml


def main() -> None:
    ort.preload_dlls()
    destination = ROOT / "data" / "gpu-check"
    destination.mkdir(parents=True, exist_ok=True)
    models = sorted((ROOT / "models").glob("*/model.onnx"))
    if not models:
        raise RuntimeError("No models/*/model.onnx found")
    report = {"python": sys.executable, "onnxruntime": ort.__version__, "models": []}
    for model in models:
        config = yaml.safe_load(model.with_name("deploy_config.yaml").read_text(encoding="utf-8"))
        width, height = config["input"]["image_size_wh"]
        options = ort.SessionOptions()
        options.enable_profiling = True
        options.profile_file_prefix = str(destination / model.parent.name)
        options.log_severity_level = 3
        session = ort.InferenceSession(
            str(model), sess_options=options,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            provider_options=[{"use_tf32": "0"}, {}],
        )
        if "CUDAExecutionProvider" not in session.get_providers():
            raise RuntimeError(f"CUDA provider missing: {model}")
        image = np.random.default_rng(0).random((1, 3, height, width), dtype=np.float32)
        started = time.perf_counter()
        outputs = session.run(None, {session.get_inputs()[0].name: image})
        seconds = time.perf_counter() - started
        if not all(np.isfinite(output).all() for output in outputs):
            raise RuntimeError(f"Non-finite output: {model}")
        profile = Path(session.end_profiling())
        events = json.loads(profile.read_text(encoding="utf-8"))
        cuda_kernels = sum(event.get("args", {}).get("provider") == "CUDAExecutionProvider" for event in events)
        if not cuda_kernels:
            raise RuntimeError(f"No CUDA kernels executed: {model}")
        result = {
            "model": str(model.relative_to(ROOT)), "providers": session.get_providers(),
            "input_shape": list(image.shape), "output_shapes": [list(output.shape) for output in outputs],
            "cuda_kernel_events": cuda_kernels, "first_run_seconds": round(seconds, 3),
        }
        report["models"].append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        del session, outputs, events
        gc.collect()
    path = destination / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"GPU validation passed; report: {path}")


if __name__ == "__main__":
    main()
