import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    'zoom_measurement', Path(__file__).resolve().parents[2] / 'scripts/measure-camera-zoom.py')
measurement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measurement)


def test_native_measurement_rejects_out_of_range_before_moving():
    with pytest.raises(ValueError, match='outside'):
        measurement.move_native(SimpleNamespace(), SimpleNamespace(), {'min': 0, 'max': 1}, 1.1)


def test_native_measurement_stops_if_device_changes_coordinate_space():
    events = []
    controller = SimpleNamespace(
        PTZ='ptz', _request=lambda *args: events.append('move'),
        _read_zoom_status=lambda *args: (.1, 'IDLE', 'another-space'),
        _stop_zoom=lambda *args: events.append('stop'))
    with pytest.raises(RuntimeError, match='coordinate space'):
        measurement.move_native(controller, SimpleNamespace(camera_onvif_profile_token='main'),
                                {'min': 0, 'max': 1, 'space': 'optical'}, .1)
    assert events == ['move', 'stop']


def test_native_measurement_requires_stable_feedback(monkeypatch):
    positions = iter([(.08, 'MOVING', 'optical'), (.1, 'IDLE', 'optical'),
                      (.1, 'IDLE', 'optical'), (.1, 'IDLE', 'optical')])
    monkeypatch.setattr(measurement.time, 'sleep', lambda seconds: None)
    controller = SimpleNamespace(PTZ='ptz', _request=lambda *args: None,
        _read_zoom_status=lambda *args: next(positions))
    assert measurement.move_native(controller, SimpleNamespace(camera_onvif_profile_token='main'),
                                   {'min': 0, 'max': 1, 'space': 'optical'}, .1) == .1
