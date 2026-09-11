#!/usr/bin/env python3
"""Wheel/editable uninstall isolation for Zero IIa + Step I core."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KERNEL = Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')).resolve()


def _run(cmd, **kwargs):
    subprocess.check_call(cmd, **kwargs)


def _build_wheels(dist_dir: Path) -> tuple[Path, Path]:
    dist_dir.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, '-m', 'pip', 'install', '-q', 'build'])
    _run(
        [sys.executable, '-m', 'build', '--wheel', '--outdir', str(dist_dir), str(KERNEL)],
    )
    _run(
        [sys.executable, '-m', 'build', '--wheel', '--outdir', str(dist_dir), str(ROOT)],
    )
    kernel_wheels = sorted(dist_dir.glob('django_trusts-*.whl'))
    zero_wheels = sorted(dist_dir.glob('django_trusts_zero-*.whl'))
    if not kernel_wheels or not zero_wheels:
        raise SystemExit('missing companion wheels in %s' % dist_dir)
    return kernel_wheels[-1], zero_wheels[-1]


PAIR_PROBE = r'''
from pathlib import Path
from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="iia-pair")
import trusts
from trusts.zero.apps import ZeroConfig
assert ZeroConfig.name == "trusts.zero"
assert ZeroConfig.label == "trusts"
assert (Path(trusts.__file__).parent / "zero" / "backends.py").is_file()
print("pair-import-ok")
'''

KERNEL_ONLY_PROBE = r'''
from pathlib import Path
from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="iia-kernel-only")
import trusts
from trusts.apps import TrustsImplementationConfig
assert TrustsImplementationConfig is not None
assert Path(trusts.__file__).name == "__init__.py"
print("kernel-survived-ok")
'''

ZERO_WITHOUT_CORE_PROBE = r'''
from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="iia-zero-only")
try:
    from trusts.apps import TrustsImplementationConfig  # noqa: F401
except ImportError:
    print("core-required-ok")
    raise SystemExit(0)
print("unexpected-zero-without-core")
raise SystemExit(1)
'''


def _venv_python(venv: Path) -> str:
    return str(venv / 'bin' / 'python')


def main() -> int:
    if not KERNEL.is_dir():
        raise SystemExit('KERNEL_CHECKOUT missing at %s' % KERNEL)
    tmp = Path(tempfile.mkdtemp(prefix='trusts-zero-uninstall-'))
    try:
        dist = tmp / 'dist'
        kernel_wheel, zero_wheel = _build_wheels(dist)

        if '2.0.0.dev2' not in zero_wheel.name:
            raise SystemExit('Zero wheel is not 2.0.0.dev2: %s' % zero_wheel.name)

        venv = tmp / 'venv'
        _run([sys.executable, '-m', 'virtualenv', str(venv)])
        py = _venv_python(venv)
        _run([py, '-m', 'pip', 'install', '-q', 'Django>=6.1,<6.2', str(kernel_wheel), str(zero_wheel)])
        out = subprocess.check_output([py, '-c', PAIR_PROBE], text=True)
        if 'pair-import-ok' not in out:
            raise SystemExit('paired import failed: %r' % out)

        _run([py, '-m', 'pip', 'uninstall', '-y', '-q', 'django-trusts-zero'])
        gone = subprocess.run(
            [py, '-m', 'pip', 'show', 'django-trusts-zero'],
            capture_output=True, text=True,
        )
        if gone.returncode == 0:
            raise SystemExit('django-trusts-zero still installed after uninstall')
        out = subprocess.check_output([py, '-c', KERNEL_ONLY_PROBE], text=True)
        if 'kernel-survived-ok' not in out:
            raise SystemExit('uninstall Zero isolation failed: %r' % out)

        venv2 = tmp / 'venv2'
        _run([sys.executable, '-m', 'virtualenv', str(venv2)])
        py2 = _venv_python(venv2)
        _run([py2, '-m', 'pip', 'install', '-q', 'Django>=6.1,<6.2', str(kernel_wheel), str(zero_wheel)])
        _run([py2, '-m', 'pip', 'uninstall', '-y', '-q', 'django-trusts'])
        result = subprocess.run(
            [py2, '-c', ZERO_WITHOUT_CORE_PROBE],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or 'core-required-ok' not in result.stdout:
            raise SystemExit(
                'uninstall core isolation failed: stdout=%s stderr=%s'
                % (result.stdout, result.stderr)
            )

        print('uninstall isolation ok')
        print('kernel', kernel_wheel.name)
        print('zero', zero_wheel.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == '__main__':
    os.chdir(ROOT)
    raise SystemExit(main())
