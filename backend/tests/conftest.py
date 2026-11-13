from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def isolate_monitoring_events(tmp_path, monkeypatch):
    from app import monitoring_audit
    monkeypatch.setattr(monitoring_audit, "AUDIT_PATH", tmp_path / "monitoring-events.jsonl")


@pytest.fixture(autouse=True)
def disable_deployed_camera_autostart(monkeypatch):
    # TestClient startup must never connect to the deployed physical camera.
    main = sys.modules.get("app.main")
    if main is not None:
        settings = main.get_settings()
        monkeypatch.setattr(main, "get_settings", lambda: replace(settings, live_capture_autostart=False))

