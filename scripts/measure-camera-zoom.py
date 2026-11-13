"""Capture explicit native zoom stops for manual verification of device OSD magnification.

This tool moves the lens, temporarily pauses capture/recording, and restores the
original native position and saved recording policy. It never writes calibration
values: inspect each device-generated Z readout before applying a mapping.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL', '-8')
import cv2
import httpx

from app.config import get_settings
from app.image_io import write_image
from app.live_capture import OnvifControl, safe_camera_error


def move_native(control, settings, options, target):
    if not options['min'] <= target <= options['max']:
        raise ValueError('Target outside the declared native optical zoom range')
    body = (f'<t:ProfileToken>{escape(settings.camera_onvif_profile_token)}</t:ProfileToken>'
            f'<t:Position><tt:Zoom x="{target:.12g}" space="{escape(options["space"])}"/></t:Position>')
    settled = False
    try:
        control._request(settings, control.PTZ, 'AbsoluteMove', body)
        deadline = time.monotonic() + 20
        stable = 0
        while time.monotonic() < deadline:
            position, movement, space = control._read_zoom_status(settings)
            if space and space != options['space']:
                raise RuntimeError('Device changed its zoom coordinate space')
            if abs(position - target) <= 0.0002 and movement in (None, 'IDLE'):
                stable += 1
                if stable >= 3:
                    settled = True
                    return position
            else:
                stable = 0
            time.sleep(.2)
        raise TimeoutError('Native lens position did not settle')
    finally:
        if not settled:
            try:
                control._stop_zoom(settings)
            except Exception:
                pass


def snapshot(settings, path):
    capture = cv2.VideoCapture()
    try:
        if not capture.open(settings.live_capture_url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000,
        ]):
            raise RuntimeError('Unable to open the saved private camera source')
        for _ in range(35):
            ok, image = capture.read()
            if not ok:
                raise RuntimeError('Unable to read a fresh calibration frame')
        if not write_image(path, image):
            raise RuntimeError('Unable to save calibration frame')
        return image.shape[1], image.shape[0]
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--positions', nargs='+', type=float, required=True,
                        help='Explicit native positions; labels are not magnification claims')
    args = parser.parse_args()
    settings = get_settings()
    root = ROOT / 'data' / 'camera-calibration'
    root.mkdir(parents=True, exist_ok=True)
    control = OnvifControl()
    records = []
    with httpx.Client(base_url='http://127.0.0.1:8010', trust_env=False, timeout=20) as client:
        policy = client.get('/api/recording/settings').json()
        camera = client.get('/api/realtime/camera').json()
        original, _, _ = control._read_zoom_status(settings)
        options = control._zoom_options(settings)
        if not all(options['min'] <= target <= options['max'] for target in args.positions):
            raise ValueError('A requested position is outside the declared range')
        (root / 'recording-before-measurement.json').write_text(json.dumps(policy, indent=2), encoding='utf-8')
        backup = root / 'env-before-measurement.bak'
        if not backup.exists():
            shutil.copy2(ROOT / '.env', backup)
        try:
            response = client.put('/api/recording/settings', json={'enabled': False})
            response.raise_for_status()
            response = client.post('/api/realtime/camera/stop')
            response.raise_for_status()
            time.sleep(2)
            for index, target in enumerate(args.positions):
                actual = move_native(control, settings, options, target)
                time.sleep(1)
                path = root / f'stop-{index:02d}.jpg'
                width, height = snapshot(settings, path)
                after, movement, _ = control._read_zoom_status(settings)
                if abs(after - actual) > .0002 or movement not in (None, 'IDLE'):
                    raise RuntimeError('Lens moved during measurement')
                result = {'index': index, 'commanded_native_position': target,
                          'reported_native_position': actual, 'image': path.name,
                          'width': width, 'height': height, 'osd_magnification': None}
                records.append(result)
                (root / 'measured-stops.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
                print(json.dumps(result), flush=True)
        finally:
            try:
                move_native(control, settings, options, original)
            finally:
                control.close()
                response = client.put('/api/recording/settings', json=policy)
                response.raise_for_status()
                if camera['status'] in ('running', 'starting', 'reconnecting'):
                    # Capture.stop is asynchronous; allow the existing worker to exit.
                    for _ in range(15):
                        response = client.post('/api/realtime/camera/start')
                        if response.status_code == 202:
                            break
                        time.sleep(1)
                    response.raise_for_status()
    print('Native-stop measurement complete; original lens position and policy restored.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(safe_camera_error(exc, get_settings()), file=sys.stderr)
        sys.exit(1)
