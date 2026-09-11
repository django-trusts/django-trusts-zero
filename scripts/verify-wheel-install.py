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
    if not any(n.endswith('trusts/zero/migrations/0001_initial.py') for n in names):
        raise SystemExit('Zero wheel missing 0001_initial')

    kernel = Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts'))
    tmp = Path(tempfile.mkdtemp(prefix='trusts-zero-wheel-'))
    try:
        venv = tmp / 'venv'
        subprocess.check_call([sys.executable, '-m', 'venv', str(venv)])
        pip = venv / 'bin' / 'pip'
        py = venv / 'bin' / 'python'
        subprocess.check_call(
            [str(pip), 'install', '-q', 'pip', 'Django>=6.1,<6.2'],
        )

        extracted = tmp / 'extracted'
        extracted.mkdir()
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(extracted)

        # Isolated PEP 420: Django only, no kernel on the path. The current
        # interpreter may already have django-trusts installed; a venv plus
        # PYTHONPATH=extracted is the probe that CI's package job needs.
        probe = (
            'from trusts.zero.apps import ZeroConfig\n'
            'assert ZeroConfig.name == "trusts.zero"\n'
            'assert ZeroConfig.label == "trusts"\n'
            'print("zero-wheel-import-ok")\n'
        )
        env = os.environ.copy()
        env['PYTHONPATH'] = str(extracted)
        env.pop('DJANGO_SETTINGS_MODULE', None)
        out = subprocess.check_output(
            [str(py), '-c', probe],
            env=env,
            cwd=str(tmp),
            text=True,
        )
        if 'zero-wheel-import-ok' not in out:
            raise SystemExit('isolated wheel import probe failed: %r' % out)

        # Real pip overlay: C1 still ships trusts/__init__.py, so installing
        # the kernel then the Zero wheel places trusts/zero/ next to it.
        if kernel.is_dir():
            subprocess.check_call([str(pip), 'install', '-q', str(kernel)])
            subprocess.check_call(
                [str(pip), 'install', '-q', '--no-deps', str(wheel)],
            )
            overlay = (
                'import trusts\n'
                'from pathlib import Path\n'
                'from trusts.zero.apps import ZeroConfig\n'
                'assert ZeroConfig.label == "trusts"\n'
                'assert ZeroConfig.name == "trusts.zero"\n'
                'init = Path(trusts.__file__)\n'
                'assert init.name == "__init__.py"\n'
                'assert (init.parent / "zero" / "apps.py").is_file()\n'
                'print("zero-wheel-overlay-ok")\n'
            )
            out2 = subprocess.check_output([str(py), '-c', overlay], text=True)
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
