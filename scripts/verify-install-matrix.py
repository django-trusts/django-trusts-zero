#!/usr/bin/env python3
"""Prove wheel+wheel, editable+editable, and Zero uninstall isolation.

Zero's wheel RECORD must never own kernel paths (especially
``trusts/__init__.py``). Uninstalling Zero must leave ``import trusts``
working and must not delete kernel files.

Installs the Zero wheel **with dependency resolution** after the local
kernel wheel (``django-trusts>=1.0.0.dev0``). Do not use ``--no-deps``
for the publishable proof.

Kernel checkout defaults to ``KERNEL_CHECKOUT`` or ``.deps/django-trusts``.
Primary companion: django-trusts PR #46. Overlay vs ``624daa1`` is extra.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / 'scripts' / 'apply-kernel-namespace-overlay.py'


def django_setup_snippet(kernel_root: Path, *, kernel_only: bool = False) -> str:
    apps_py = kernel_root / 'trusts' / 'apps.py'
    split = False
    if apps_py.is_file():
        text = apps_py.read_text()
        split = "label = 'trusts_kernel'" in text or 'label = "trusts_kernel"' in text
    if kernel_only:
        extra = '"trusts.apps.KernelConfig"' if split else '"trusts"'
        return (
            'from django.conf import settings\n'
            'if not settings.configured:\n'
            '    settings.configure(\n'
            '        SECRET_KEY="zero-matrix-kernel",\n'
            '        USE_TZ=True,\n'
            '        INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth", %s],\n'
            '        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},\n'
            '    )\n'
            'import django\n'
            'django.setup()\n' % extra
        )
    apps = [
        '"django.contrib.contenttypes"',
        '"django.contrib.auth"',
    ]
    if split:
        apps.append('"trusts.apps.KernelConfig"')
    apps.append('"trusts.zero.apps.ZeroConfig"')
    return (
        'from django.conf import settings\n'
        'if not settings.configured:\n'
        '    settings.configure(\n'
        '        SECRET_KEY="zero-matrix",\n'
        '        USE_TZ=True,\n'
        '        INSTALLED_APPS=[%s],\n'
        '        AUTHENTICATION_BACKENDS=["trusts.zero.backends.TrustModelBackend"],\n'
        '        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},\n'
        '    )\n'
        'import django\n'
        'django.setup()\n' % ', '.join(apps)
    )


KERNEL_OWNED_PATHS = (
    'trusts/__init__.py',
    'trusts/apps.py',
    'trusts/context.py',
    'trusts/trustee.py',
    'trusts/path.py',
    'trusts/conditions.py',
    'trusts/models.py',
    'trusts/backends.py',
    'trusts/admin.py',
    'trusts/query.py',
    'trusts/authorization.py',
    'django_trusts.py',
)


def run(cmd, **kwargs):
    kwargs.setdefault('check', True)
    return subprocess.run(cmd, **kwargs)


def isolated_env() -> dict:
    """Drop PYTHONPATH so a checkout cannot shadow site-packages."""
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['PYTHONNOUSERSITE'] = '1'
    return env


def venv_eval(py: Path, code: str, *, cwd: Path) -> None:
    """Run ``code`` in the venv with the Zero/kernel checkouts off ``sys.path``.

    ``python -c`` prepends cwd to ``sys.path``. Running from this repo would
    keep ``trusts.zero`` importable after uninstall (false isolation).
    ``-P`` (Python 3.11+) skips that prepend; ``cwd`` is a scratch dir.
    """
    run(
        [str(py), '-P', '-c', code],
        cwd=str(cwd),
        env=isolated_env(),
        check=True,
    )


def venv_python(venv_dir: Path) -> Path:
    return venv_dir / 'bin' / 'python'


def make_venv(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    # stdlib venv requires ensurepip (python3-venv). virtualenv works here and in CI.
    run([sys.executable, '-m', 'virtualenv', str(path)], check=True)
    py = venv_python(path)
    run([str(py), '-m', 'pip', 'install', '--upgrade', 'pip', 'build', 'wheel'], check=True)
    return py


def build_wheel(py: Path, project: Path, dist_dir: Path) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    for old in dist_dir.glob('*.whl'):
        old.unlink()
    run(
        [str(py), '-m', 'build', '--wheel', '--outdir', str(dist_dir), str(project)],
        check=True,
    )
    wheels = list(dist_dir.glob('*.whl'))
    if len(wheels) != 1:
        raise SystemExit('expected one wheel in %s, got %s' % (dist_dir, wheels))
    return wheels[0]


def record_paths(dist_info: Path) -> list[str]:
    record = dist_info / 'RECORD'
    rows = []
    for line in record.read_text().splitlines():
        if not line.strip():
            continue
        rows.append(line.split(',', 1)[0])
    return rows


def find_dist_info(site_packages: Path, dist_prefix: str) -> Path:
    matches = list(site_packages.glob(dist_prefix + '*.dist-info'))
    if len(matches) != 1:
        raise SystemExit('expected one %s dist-info in %s, got %s' % (
            dist_prefix, site_packages, matches,
        ))
    return matches[0]


def site_packages_of(py: Path) -> Path:
    out = run(
        [str(py), '-c', 'import site; print(site.getsitepackages()[0])'],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def wheel_names(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as zf:
        return zf.namelist()


def assert_zero_wheel_owns_only_zero(wheel: Path) -> None:
    names = wheel_names(wheel)
    illegal = []
    for name in names:
        if name.startswith('django_trusts_zero') and '.dist-info/' in name:
            continue
        if name.startswith('trusts/zero/'):
            continue
        illegal.append(name)
    if illegal:
        raise SystemExit('Zero wheel owns non-zero paths: %s' % illegal)
    for owned in KERNEL_OWNED_PATHS:
        if owned in names or owned + '/' in names:
            raise SystemExit('Zero wheel RECORD/payload owns kernel path %s' % owned)
    if 'trusts/__init__.py' in names:
        raise SystemExit('Zero wheel ships trusts/__init__.py')


def prove_wheel_wheel(py_build: Path, kernel_root: Path, work: Path) -> None:
    print('=== wheel+wheel ===')
    kernel_wheel = build_wheel(py_build, kernel_root, work / 'dist-kernel')
    zero_wheel = build_wheel(py_build, ROOT, work / 'dist-zero')
    assert_zero_wheel_owns_only_zero(zero_wheel)
    setup = django_setup_snippet(kernel_root)
    setup_kernel = django_setup_snippet(kernel_root, kernel_only=True)

    venv_dir = work / 'venv-wheel'
    py = make_venv(venv_dir)
    run([str(py), '-m', 'pip', 'install', str(kernel_wheel)], check=True)
    # Dependency resolution: kernel 1.0.0.dev0 already installed satisfies Requires-Dist.
    run([str(py), '-m', 'pip', 'install', str(zero_wheel)], check=True)

    site = site_packages_of(py)
    zero_info = find_dist_info(site, 'django_trusts_zero-')
    kernel_info = find_dist_info(site, 'django_trusts-')
    zero_files = record_paths(zero_info)
    kernel_files = record_paths(kernel_info)
    for path in zero_files:
        if path.startswith('trusts/') and not path.startswith('trusts/zero/'):
            raise SystemExit('Zero RECORD owns non-zero module path: %s' % path)
        for owned in KERNEL_OWNED_PATHS:
            if path == owned or path.startswith(owned):
                raise SystemExit('Zero RECORD owns kernel path: %s' % path)

    kernel_init = site / 'trusts' / '__init__.py'
    if not kernel_init.is_file():
        raise SystemExit('kernel trusts/__init__.py missing after wheel+wheel')
    kernel_init_hash_before = kernel_init.read_bytes()

    venv_eval(
        py,
        setup
        + 'import trusts, trusts.zero, trusts.context, trusts.trustee, trusts.path\n'
        'from trusts.zero.models import Trust\n'
        'from trusts.zero.backends import TrustModelBackend\n'
        'from trusts.zero.apps import ZeroConfig\n'
        'assert ZeroConfig.name == "trusts.zero" and ZeroConfig.label == "trusts"\n'
        'print("wheel+wheel import ok", trusts.__file__, Trust, TrustModelBackend)',
        cwd=work,
    )

    run([str(py), '-m', 'pip', 'uninstall', '-y', 'django-trusts-zero'], check=True)
    if not kernel_init.is_file():
        raise SystemExit('uninstall Zero deleted kernel trusts/__init__.py')
    if kernel_init.read_bytes() != kernel_init_hash_before:
        raise SystemExit('uninstall Zero mutated kernel trusts/__init__.py')
    # Kernel RECORD must still list the same kernel-owned files.
    kernel_info_after = find_dist_info(site, 'django_trusts-')
    after_files = set(record_paths(kernel_info_after))
    before_kernel = set(kernel_files)
    missing = before_kernel - after_files
    if missing:
        raise SystemExit('kernel RECORD lost paths after Zero uninstall: %s' % sorted(missing))

    venv_eval(
        py,
        setup_kernel
        + 'import trusts, trusts.context\n'
        'import importlib.util\n'
        'spec = importlib.util.find_spec("trusts.zero")\n'
        'assert spec is None, "trusts.zero still present: %s" % spec\n'
        'print("uninstall isolation ok", trusts.__file__)',
        cwd=work,
    )

    run([str(py), '-m', 'pip', 'install', str(zero_wheel)], check=True)
    venv_eval(
        py,
        setup
        + 'import trusts.zero\n'
        'from trusts.zero.models import Trust\n'
        'print("reinstall ok", Trust)',
        cwd=work,
    )
    print('wheel+wheel ok')


def prove_editable_editable(py_build: Path, kernel_root: Path, work: Path) -> None:
    print('=== editable+editable ===')
    kernel_copy = work / 'kernel-editable'
    if kernel_copy.exists():
        shutil.rmtree(kernel_copy)
    shutil.copytree(
        kernel_root,
        kernel_copy,
        ignore=shutil.ignore_patterns('.git', '.venv', 'dist', 'build', '*.egg-info'),
    )
    run(
        [str(py_build), str(OVERLAY), '--strip-in-tree-zero', str(kernel_copy)],
        check=True,
    )

    venv_dir = work / 'venv-editable'
    py = make_venv(venv_dir)
    # compat: default strict editable turns trusts into a PEP 420 namespace
    # (trusts.__file__ is None) and hides kernel trusts/__init__.py.
    run(
        [str(py), '-m', 'pip', 'install', '-e', str(kernel_copy),
         '--config-settings', 'editable_mode=compat'],
        check=True,
    )
    # Kernel 1.0.0.dev0 is already installed; resolution must accept it and
    # must not fall back to --no-deps (that hid a missing Requires-Dist).
    run(
        [str(py), '-m', 'pip', 'install', '-e', str(ROOT),
         '--config-settings', 'editable_mode=compat'],
        check=True,
    )
    venv_eval(
        py,
        django_setup_snippet(kernel_root)
        + 'import trusts, trusts.zero, trusts.context\n'
        'from trusts.zero.models import Trust\n'
        'assert trusts.__file__, "kernel must own trusts/__init__.py, got namespace"\n'
        'print("editable+editable import ok", trusts.__file__, trusts.zero.__file__, Trust)\n'
        'assert "zero" in trusts.zero.__file__',
        cwd=work,
    )
    print('editable+editable ok')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--kernel',
        type=Path,
        default=Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')),
        help='django-trusts checkout (default KERNEL_CHECKOUT or .deps/django-trusts)',
    )
    args = parser.parse_args()
    kernel_root = args.kernel.resolve()
    if not (kernel_root / 'pyproject.toml').is_file():
        raise SystemExit('kernel checkout not found: %s' % kernel_root)

    with tempfile.TemporaryDirectory(prefix='django-trusts-zero-matrix-') as tmp:
        work = Path(tmp)
        py_build = make_venv(work / 'venv-build')
        prove_wheel_wheel(py_build, kernel_root, work)
        prove_editable_editable(py_build, kernel_root, work)
    print('install matrix ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
