#!/usr/bin/env python3
"""Old core backend path must fail startup with ImproperlyConfigured."""

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
os.environ.pop("DJANGO_SETTINGS_MODULE", None)
from django.conf import settings
settings.configure(
    SECRET_KEY="neg-old-backend",
    USE_TZ=True,
    DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "trusts.zero.apps.ZeroConfig",
    ],
    AUTHENTICATION_BACKENDS=[
        "django.contrib.auth.backends.ModelBackend",
        "trusts.backends.TrustModelBackend",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)
import django
from django.core.exceptions import ImproperlyConfigured
try:
    django.setup()
except ImproperlyConfigured as exc:
    text = str(exc)
    print("old-backend-gate", text)
    raise SystemExit(0)
print("populate-succeeded")
raise SystemExit(1)
'''


def main() -> int:
    env = os.environ.copy()
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
        raise SystemExit('old-backend-path gate failed')
    if 'old-backend-gate' not in result.stdout:
        raise SystemExit('old-backend-path did not print old-backend-gate')
    if 'trusts.zero.backends.TrustModelBackend' not in result.stdout:
        raise SystemExit('error did not name the canonical backend path')
    print(result.stdout.strip())
    print('neg-old-backend-path ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
