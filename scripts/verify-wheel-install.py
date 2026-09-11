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


ISOLATED_PROBE = r'''
import sys
from pathlib import Path
from django.conf import settings

extracted = Path(%r)
kept = []
for p in sys.path:
    if Path(p, "trusts", "__init__.py").is_file():
        continue
    kept.append(p)
sys.path[:] = kept
sys.path.insert(0, str(extracted))
for name in list(sys.modules):
    if name == "trusts" or name.startswith("trusts."):
        del sys.modules[name]
if not settings.configured:
    settings.configure(SECRET_KEY="zero-wheel-isolated")
from trusts.zero.apps import ZeroConfig
assert ZeroConfig.name == "trusts.zero"
assert ZeroConfig.label == "trusts"
print("zero-wheel-import-ok")
'''

OVERLAY_PROBE = r'''
from django.conf import settings
from pathlib import Path

if not settings.configured:
    settings.configure(SECRET_KEY="zero-wheel-overlay")
import trusts
from trusts.zero.apps import ZeroConfig
assert ZeroConfig.label == "trusts"
assert ZeroConfig.name == "trusts.zero"
init = Path(trusts.__file__)
assert init.name == "__init__.py"
assert (init.parent / "zero" / "apps.py").is_file()
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
    if not any('django_trusts_zero-1.0.0.dev0' in n for n in names):
        if 'django_trusts_zero-1.0.0.dev0' not in wheel.name:
            raise SystemExit('Zero wheel is not 1.0.0.dev0: %s' % wheel.name)
    metadata = next(
        (n for n in names if n.endswith('.dist-info/METADATA')),
        None,
    )
    if metadata is None:
        raise SystemExit('Zero wheel missing METADATA')
    with zipfile.ZipFile(wheel) as zf:
        meta = zf.read(metadata).decode('utf-8')
    if 'Name: django-trusts-zero' not in meta:
        raise SystemExit('wheel METADATA missing Name: django-trusts-zero')
    if 'Version: 1.0.0.dev0' not in meta:
        raise SystemExit('wheel METADATA is not Version: 1.0.0.dev0')
    if 'Requires-Dist: django-trusts<2,>=1.0.0.dev3' not in meta and (
        'Requires-Dist: django-trusts>=1.0.0.dev3,<2' not in meta
    ):
        raise SystemExit('wheel METADATA missing core floor django-trusts>=1.0.0.dev3,<2')
    sdists = sorted((ROOT / 'dist').glob('django_trusts_zero-1.0.0.dev0.tar.gz'))
    if sdists:
        import tarfile

        with tarfile.open(sdists[-1]) as tf:
            pkg = next(
                (
                    m for m in tf.getmembers()
                    if m.name.endswith('PKG-INFO')
                ),
                None,
            )
            if pkg is None:
                raise SystemExit('sdist missing PKG-INFO')
            info = tf.extractfile(pkg).read().decode('utf-8')
        if 'Version: 1.0.0.dev0' not in info:
            raise SystemExit('sdist PKG-INFO is not Version: 1.0.0.dev0')
        if 'Requires-Dist: django-trusts<2,>=1.0.0.dev3' not in info and (
            'Requires-Dist: django-trusts>=1.0.0.dev3,<2' not in info
        ):
            raise SystemExit('sdist PKG-INFO missing core floor')
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
    tmp = Path(tempfile.mkdtemp(prefix='trusts-zero-wheel-'))
    try:
        extracted = tmp / 'extracted'
        extracted.mkdir()
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(extracted)

        # Isolated PEP 420: drop every path that owns trusts/__init__.py so a
        # preinstalled kernel cannot shadow the wheel portion.
        env = os.environ.copy()
        env.pop('DJANGO_SETTINGS_MODULE', None)
        out = subprocess.check_output(
            [sys.executable, '-c', ISOLATED_PROBE % str(extracted)],
            env=env,
            cwd=str(tmp),
            text=True,
        )
        if 'zero-wheel-import-ok' not in out:
            raise SystemExit('isolated wheel import probe failed: %r' % out)

        # Real overlay: C1 still ships trusts/__init__.py. pip --target
        # refuses to merge a second distribution into an existing trusts/
        # directory; extracting the Zero wheel on top of the kernel install
        # is the layout `pip install django-trusts && pip install
        # django-trusts-zero` produces in site-packages.
        if kernel.is_dir():
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
        else:
            print('skip overlay probe (no KERNEL_CHECKOUT at %s)' % kernel)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('wheel install ok')
    print('wheel', wheel)
    return 0


if __name__ == '__main__':
    os.chdir(ROOT)
    raise SystemExit(main())
