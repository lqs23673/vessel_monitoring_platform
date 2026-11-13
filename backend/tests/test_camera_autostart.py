import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app import main
from app.config import get_settings


@pytest.mark.parametrize('enabled,fail', [(False, False), (True, False), (True, True)])
def test_camera_autostart_respects_setting_and_keeps_lifecycle_available(monkeypatch, enabled, fail, caplog):
    events = []
    settings = replace(get_settings(), live_capture_autostart=enabled)
    monkeypatch.setattr(main, 'get_settings', lambda: settings)
    monkeypatch.setattr(main.Base.metadata, 'create_all', lambda **kwargs: None)
    monkeypatch.setattr(main, 'job_manager', SimpleNamespace(
        start=lambda: events.append('queue_start'), stop=lambda: events.append('queue_stop')))

    async def start():
        events.append('camera_start')
        if fail:
            raise RuntimeError('capture not ready')

    async def stop():
        events.append('realtime_stop')

    monkeypatch.setattr(main, 'start_camera', start)
    monkeypatch.setattr(main, 'shutdown_realtime', stop)

    async def exercise():
        async with main.lifespan(main.app):
            events.append('serving')

    asyncio.run(exercise())
    assert events == ['queue_start', *(['camera_start'] if enabled else []),
                      'serving', 'realtime_stop', 'queue_stop']
    if fail:
        assert 'Camera autostart failed' in caplog.text
