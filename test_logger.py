"""掌中智戲第四章測試事件紀錄器：非同步以外的極小同步 CSV 寫入。"""
import csv
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent / 'test_logs'
_LOCK = threading.Lock()
_RUN_ID = datetime.now().strftime('%Y%m%d_%H%M%S')
_PATH = _LOG_DIR / f'events_{_RUN_ID}.csv'
_FIELDS = ['run_id', 'wall_time', 'monotonic_ns', 'event', 'hand',
           'fingers', 'command', 'value', 'detail']


def record_event(event, hand='', fingers='', command='', value='', detail=''):
    """寫入一筆事件；例：record_event('SERIAL_SENT', command='R1')。"""
    now = datetime.now().astimezone().isoformat(timespec='milliseconds')
    row = {
        'run_id': _RUN_ID,
        'wall_time': now,
        'monotonic_ns': time.monotonic_ns(),
        'event': str(event),
        'hand': str(hand),
        'fingers': str(fingers),
        'command': str(command),
        'value': str(value),
        'detail': str(detail),
    }
    with _LOCK:
        _LOG_DIR.mkdir(exist_ok=True)
        new_file = not _PATH.exists() or _PATH.stat().st_size == 0
        with _PATH.open('a', newline='', encoding='utf-8-sig' if new_file else 'utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    return _PATH


def run_info():
    """回傳目前紀錄檔案及程式版本。"""
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=Path(__file__).resolve().parent,
            stderr=subprocess.DEVNULL, timeout=2, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        commit = 'unknown'
    return {'run_id': _RUN_ID, 'file': str(_PATH), 'commit': commit}


if __name__ == '__main__':
    print(run_info())
    record_event('TEST_START', detail='logger self-test')
    record_event('SERIAL_SENT', command='R1', value='OK')
    record_event('ARDUINO_REPLY', detail='ACTION_START:P1_WAVE')
    print('測試紀錄完成:', _PATH)
