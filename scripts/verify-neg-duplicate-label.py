#!/usr/bin/env python3
"""Neg-Z1-C1: C1 + ZeroConfig must fail populate (duplicate label='trusts')."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KERNEL = Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')).resolve()

PROBE = r'''
import os, sys
from pathlib import Path
root = Path(%r).resolve()
kernel = Path(%r).resolve()
sys.path.insert(0, str(kernel))
sys.path.append(str(root))
os.environ["TRUSTS_ZERO_SKIP_C2_SHAPE"] = "1"
from django.conf import settings
settings.configure(
    SECRET_KEY="neg-z1-c1",
    USE_TZ=True,
    DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "trusts",
        "trusts.zero.apps.ZeroConfig",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)
import django
from django.core.exceptions import ImproperlyConfigured
try:
    django.setup()
except ImproperlyConfigured as exc:
    text = str(exc)
    print("duplicate-label-gate", text)
    raise SystemExit(0)
print("populate-succeeded")
raise SystemExit(1)
'''


def main() -> int:
    env = os.environ.copy()
    env['TRUSTS_ZERO_SKIP_C2_SHAPE'] = '1'
    env.pop('DJANGO_SETTINGS_MODULE', None)
    result = subprocess.run(
        [sys.executable, '-c', PROBE % (str(ROOT), str(KERNEL))],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit('neg-Z1-C1 gate failed')
    if 'duplicate-label-gate' not in result.stdout:
        raise SystemExit('neg-Z1-C1 did not print duplicate-label-gate')
    print(result.stdout.strip())
    print('neg-Z1-C1 ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
