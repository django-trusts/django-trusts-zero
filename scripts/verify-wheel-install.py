#!/usr/bin/env python3
"""Prove the Zero wheel does not own kernel paths and imports ZeroConfig."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


FORBIDDEN = (
    'trusts/__init__.py',
    'trusts/apps.py',
    'trusts/models.py',
    'trusts/backends.py',
    'trusts/core.py',
    'trusts/query.py',
)


def _ensure_wheel() -> Path:
    dist = ROOT / 'dist'
    wheels = sorted(dist.glob('django_trusts_zero-*.whl'))
    if not wheels:
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', 'build'],
            check=True,
        )
        subprocess.run(
            [sys.executable, '-m', 'build', '--wheel'],
            cwd=str(ROOT),
            check=True,
        )
        wheels = sorted(dist.glob('django_trusts_zero-*.whl'))
    if not wheels:
        raise SystemExit('no Zero wheel in dist/')
    return wheels[-1]


# Importing Zero's app config pulls in Core. Without the Core wheel that
# import must fail as ModuleNotFoundError. The success path installs the
# Core checkout into the same target and extracts the Zero wheel on top.
ISOLATED_PROBE = r'''
import sys
from pathlib import Path

from django.conf import settings

extracted = Path(%r)
kept = []
for entry in sys.path:
    candidate = Path(entry)
    if (candidate / "trusts" / "__init__.py").is_file():
        continue
    if (candidate / "trusts" / "zero" / "apps.py").is_file():
        continue
    kept.append(entry)
sys.path[:] = kept
sys.path.insert(0, str(extracted))
for name in list(sys.modules):
    if name == "trusts" or name.startswith("trusts."):
        del sys.modules[name]
if not settings.configured:
    settings.configure(SECRET_KEY="zero-wheel-isolated")
try:
    import trusts.zero.apps  # noqa: F401
except ModuleNotFoundError as exc:
    missing = exc.name or ""
    if missing == "trusts.apps" or missing.startswith("trusts"):
        print("zero-without-core-fails-clean")
    else:
        raise
else:
    raise SystemExit("importing trusts.zero.apps without Core succeeded")
'''


# Views and URLconfs import decorators after django.setup(). The probe
# does the same: configure an installed Zero app, set Django up, then
# import the decorator surface. It also checks that the wheel sat on
# top of the kernel (kernel trusts/__init__.py, Zero trusts/zero/).
OVERLAY_PROBE = r'''
from pathlib import Path

from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="zero-wheel-overlay",
        USE_TZ=True,
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "trusts.zero.apps.ZeroConfig",
        ],
        AUTHENTICATION_BACKENDS=[
            "django.contrib.auth.backends.ModelBackend",
            "trusts.zero.backends.TrustModelBackend",
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            },
        },
    )

import django
django.setup()

import trusts
from trusts.zero.apps import ZeroConfig
from trusts.zero.decorators import P, R, K, G, O, permission_required
assert ZeroConfig.label == "trusts"
assert ZeroConfig.name == "trusts.zero"
assert callable(permission_required)
assert issubclass(K, R)
assert issubclass(G, R)
assert issubclass(O, R)
init = Path(trusts.__file__)
assert init.name == "__init__.py"
assert (init.parent / "zero" / "apps.py").is_file()
assert (init.parent / "zero" / "decorators.py").is_file()
print("zero-wheel-overlay-ok")
'''


def main() -> int:
    wheel = _ensure_wheel()
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    for path in FORBIDDEN:
        if any(n == path or n.endswith('/' + path) for n in names):
            raise SystemExit('Zero wheel owns forbidden path %s' % path)
    init_hits = [n for n in names if n.endswith('trusts/__init__.py')]
    if init_hits:
        raise SystemExit('Zero wheel ships trusts/__init__.py: %s' % init_hits)
    if not any(n.endswith('trusts/zero/apps.py') for n in names):
        raise SystemExit('Zero wheel missing trusts/zero/apps.py')
    if not any(n.endswith('trusts/zero/backends.py') for n in names):
        raise SystemExit('Zero wheel missing trusts/zero/backends.py')
    if not any(n.endswith('trusts/zero/decorators.py') for n in names):
        raise SystemExit('Zero wheel missing trusts/zero/decorators.py')
    if 'django_trusts_zero-0.12.0.dev0' not in wheel.name:
        raise SystemExit('Zero wheel is not 0.12.0.dev0: %s' % wheel.name)
    if not any('django_trusts_zero-0.12.0.dev0' in n for n in names):
        raise SystemExit('Zero wheel RECORD is not 0.12.0.dev0: %s' % names[:12])
    if not any(n.endswith('trusts/zero/migrations/0001_initial.py') for n in names):
        raise SystemExit('Zero wheel missing 0001_initial')

    try:
        import django  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            'verify-wheel-install requires Django on the interpreter '
            '(package CI installs Django>=6.1,<6.2): %s' % exc
        )

    kernel = Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts'))
    if not kernel.is_dir():
        raise SystemExit(
            'KERNEL_CHECKOUT missing at %s; the overlay probe installs '
            'the Core checkout alongside the Zero wheel.' % kernel
        )
    tmp = Path(tempfile.mkdtemp(prefix='trusts-zero-wheel-'))
    try:
        extracted = tmp / 'extracted'
        extracted.mkdir()
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(extracted)
        env = os.environ.copy()
        env.pop('DJANGO_SETTINGS_MODULE', None)
        isolated = subprocess.check_output(
            [sys.executable, '-c', ISOLATED_PROBE % str(extracted)],
            env=env,
            cwd=str(tmp),
            text=True,
        )
        if 'zero-without-core-fails-clean' not in isolated:
            raise SystemExit('isolated wheel import probe failed: %r' % isolated)

        # Install the Core checkout, then extract the Zero wheel on top.
        # pip --target refuses to merge a second distribution into an
        # existing trusts/ directory; this is the layout
        # `pip install django-trusts && pip install django-trusts-zero`
        # produces in site-packages.
        site = tmp / 'overlay-site'
        site.mkdir()
        subprocess.check_call(
            [
                sys.executable, '-m', 'pip', 'install', '-q',
                '--target', str(site), str(kernel),
            ],
        )
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(site)
        if not (site / 'trusts' / 'zero' / 'apps.py').is_file():
            raise SystemExit('overlay missing trusts/zero/apps.py')
        if not (site / 'trusts' / '__init__.py').is_file():
            raise SystemExit('overlay lost kernel trusts/__init__.py')
        overlay_env = os.environ.copy()
        overlay_env['PYTHONPATH'] = str(site)
        overlay_env.pop('DJANGO_SETTINGS_MODULE', None)
        out2 = subprocess.check_output(
            [sys.executable, '-c', OVERLAY_PROBE],
            env=overlay_env,
            cwd=str(tmp),
            text=True,
        )
        if 'zero-wheel-overlay-ok' not in out2:
            raise SystemExit('overlay wheel import probe failed: %r' % out2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('wheel install ok')
    print('wheel', wheel)
    return 0


if __name__ == '__main__':
    os.chdir(ROOT)
    raise SystemExit(main())
