"""Neg-Z1-C1: installing ZeroConfig next to unpatched C1 is duplicate-label."""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


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
    if "trusts" in text.lower() or "label" in text.lower() or "duplicate" in text.lower():
        print("duplicate-label-gate", text)
        raise SystemExit(0)
    print("wrong ImproperlyConfigured", text)
    raise SystemExit(2)
print("populate-succeeded")
raise SystemExit(1)
'''


class DuplicateLabelGateTests(SimpleTestCase):
    def test_c1_plus_zeroconfig_raises_improperly_configured(self):
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
        self.assertEqual(
            result.returncode, 0,
            'neg-Z1-C1 gate failed:\nstdout=%s\nstderr=%s' % (
                result.stdout, result.stderr,
            ),
        )
        self.assertIn('duplicate-label-gate', result.stdout)
