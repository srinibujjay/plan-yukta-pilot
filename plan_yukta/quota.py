"""Daily question quota for the Claude-backed chat.

Each user (tester name when access codes are on, otherwise a hash of the IP address) gets
CHAT_DAILY_LIMIT Claude answers per day (default 10). CHAT_GLOBAL_DAILY_LIMIT caps the whole site
per day (default 200) so the owner's API bill has a hard ceiling. Names in CHAT_UNLIMITED
(comma separated) are not counted against their own limit but still count toward the site cap.

Counts are kept on the server in one small JSON file, so clearing cookies does not reset them.
The day rolls over at midnight in CHAT_TZ_OFFSET_MIN minutes from UTC (default 330 = India).
A server restart on the free hosting tier can clear the file; that only ever gives users more questions.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORE = Path(os.environ.get('WORKSPACE_DIR', '/tmp/planyukta_ws')) / '_chat_quota.json'


def _int(name, default):
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def limit() -> int:
    return _int('CHAT_DAILY_LIMIT', 10)


def global_limit() -> int:
    return _int('CHAT_GLOBAL_DAILY_LIMIT', 200)


def _tz():
    return timezone(timedelta(minutes=_int('CHAT_TZ_OFFSET_MIN', 330)))


def today() -> str:
    return datetime.now(_tz()).strftime('%Y-%m-%d')


def resets_at() -> str:
    return '00:00 ' + ('IST' if _int('CHAT_TZ_OFFSET_MIN', 330) == 330 else 'local server day')


def user_key(tester: str | None, ip: str | None) -> str:
    if tester:
        return 't:' + tester
    return 'ip:' + hashlib.sha256(('py-salt:' + (ip or '-')).encode()).hexdigest()[:16]


def unlimited(tester: str | None) -> bool:
    names = {n.strip() for n in os.environ.get('CHAT_UNLIMITED', '').split(',') if n.strip()}
    return bool(tester) and tester in names


class _Locked:
    """Read-modify-write the quota file under an exclusive lock (safe across threads and workers)."""

    def __enter__(self):
        STORE.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(STORE, 'a+', encoding='utf-8')
        fcntl.flock(self.f, fcntl.LOCK_EX)
        self.f.seek(0)
        try:
            data = json.loads(self.f.read() or '{}')
        except ValueError:
            data = {}
        if data.get('day') != today():
            data = {'day': today(), 'users': {}, 'total': 0}
        self.data = data
        return data

    def __exit__(self, *exc):
        self.f.seek(0)
        self.f.truncate()
        json.dump(self.data, self.f)
        self.f.flush()
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
        return False


def status(key: str, tester: str | None = None) -> dict:
    with _Locked() as d:
        used = int(d['users'].get(key, 0))
        total = int(d['total'])
    free = unlimited(tester)
    left = None if free else max(0, limit() - used)
    site_left = max(0, global_limit() - total)
    return {'used': used, 'limit': None if free else limit(), 'left': left, 'site_left': site_left,
            'unlimited': free, 'resets': resets_at()}


def take(key: str, tester: str | None = None) -> tuple[bool, str]:
    """Reserve one question. Returns (allowed, reason). Call refund() if the API call then fails."""
    with _Locked() as d:
        used = int(d['users'].get(key, 0))
        if int(d['total']) >= global_limit():
            return False, 'site'
        if not unlimited(tester) and used >= limit():
            return False, 'user'
        d['users'][key] = used + 1
        d['total'] = int(d['total']) + 1
    return True, ''


def refund(key: str):
    with _Locked() as d:
        if int(d['users'].get(key, 0)) > 0:
            d['users'][key] -= 1
            d['total'] = max(0, int(d['total']) - 1)
