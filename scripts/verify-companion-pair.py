#!/usr/bin/env python3
"""Cross-repo proof: this Zero wheel + the exact companion kernel HEAD.

This repository is authoritative for django-trusts-zero metadata
(version 2.0.0.dev0, Requires-Dist django-trusts>=1.0.0.dev0). If the
kernel checkout still contains packaging/django-trusts-zero/, that
mirror must match or this script fails.

Also proves:

1. Zero wheel METADATA declares django-trusts>=1.0.0.dev0
2. Empty venv + one resolver-driven ``pip install`` of the Zero wheel
   from a local wheelhouse (``--no-index --find-links``) pulls in the
   companion kernel wheel. Does not preinstall the kernel, does not use
   ``--no-deps``, and does not treat PyPI absence of 1.x as success.
3. wheel+wheel / editable+editable / uninstall via verify-install-matrix
4. AppConfig, migration plan, and import checks against those artifacts
   using THIS repository's ``trusts.zero`` (in-tree kernel Zero is stripped
   on a copy so it cannot shadow this package)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / 'scripts' / 'verify-install-matrix.py'
OVERLAY = ROOT / 'scripts' / 'apply-kernel-namespace-overlay.py'

AUTHORITATIVE_NAME = 'django-trusts-zero'
AUTHORITATIVE_VERSION = '2.0.0.dev0'
KERNEL_REQ = 'django-trusts>=1.0.0.dev0'
DJANGO_REQ = 'Django>=6.1,<6.2'


def run(cmd, **kwargs):
    kwargs.setdefault('check', True)
    return subprocess.run(cmd, **kwargs)


def _toml_name_version_deps(text: str) -> tuple[str, str, list[str]]:
    name = re.search(r'(?m)^name\s*=\s*"([^"]+)"', text)
    version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    deps_block = re.search(r'(?ms)^dependencies\s*=\s*\[(.*?)\]', text)
    if not name or not version or not deps_block:
        raise SystemExit('could not parse name/version/dependencies from pyproject')
    deps = re.findall(r'"([^"]+)"', deps_block.group(1))
    return name.group(1), version.group(1), deps


def assert_this_repo_is_authoritative() -> tuple[str, str, list[str]]:
    text = (ROOT / 'pyproject.toml').read_text()
    name, version, deps = _toml_name_version_deps(text)
    if name != AUTHORITATIVE_NAME:
        raise SystemExit('authoritative name is %s, pyproject has %s' % (
            AUTHORITATIVE_NAME, name,
        ))
    if version != AUTHORITATIVE_VERSION:
        raise SystemExit('authoritative version is %s, pyproject has %s' % (
            AUTHORITATIVE_VERSION, version,
        ))
    if KERNEL_REQ not in deps:
        raise SystemExit(
            'pyproject.toml must declare %r in dependencies (got %s)' % (
                KERNEL_REQ, deps,
            )
        )
    if DJANGO_REQ not in deps:
        raise SystemExit('pyproject.toml must declare %r (got %s)' % (
            DJANGO_REQ, deps,
        ))
    return name, version, deps


def assert_kernel_mirror_matches(kernel_root: Path, name: str, version: str, deps: list[str]) -> None:
    """Fail if a retained kernel packaging mirror diverges from this repo."""
    mirror = kernel_root / 'packaging' / 'django-trusts-zero' / 'pyproject.toml'
    if not mirror.is_file():
        print('kernel Zero packaging mirror absent (ok)')
        return
    m_name, m_version, m_deps = _toml_name_version_deps(mirror.read_text())
    errors = []
    if m_name != name:
        errors.append('name %r != authoritative %r' % (m_name, name))
    if m_version != version:
        errors.append('version %r != authoritative %r' % (m_version, version))
    if sorted(m_deps) != sorted(deps):
        errors.append('dependencies %s != authoritative %s' % (m_deps, deps))
    if errors:
        raise SystemExit(
            'retained kernel mirror %s diverges from this Zero repository:\n  %s'
            % (mirror, '\n  '.join(errors))
        )
    print('kernel Zero packaging mirror matches this repository')


def assert_split_kernel(kernel_root: Path) -> None:
    apps = kernel_root / 'trusts' / 'apps.py'
    init = kernel_root / 'trusts' / '__init__.py'
    if not apps.is_file() or not init.is_file():
        raise SystemExit('kernel checkout missing trusts/apps.py or __init__.py')
    apps_text = apps.read_text()
    if "label = 'trusts_kernel'" not in apps_text and 'label = "trusts_kernel"' not in apps_text:
        raise SystemExit(
            'companion kernel must provide KernelConfig label=trusts_kernel; got %s'
            % kernel_root
        )
    if 'extend_path' not in init.read_text():
        raise SystemExit('companion kernel trusts/__init__.py must call pkgutil.extend_path')
    print('companion kernel KernelConfig + extend_path ok', kernel_root)


def copy_kernel(kernel_root: Path, dest: Path, *, strip_zero: bool = False) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        kernel_root,
        dest,
        ignore=shutil.ignore_patterns(
            '.git', '.venv', 'venv', 'dist', 'build', '*.egg-info', '__pycache__',
        ),
    )
    if strip_zero:
        run([sys.executable, str(OVERLAY), '--strip-in-tree-zero', str(dest)], check=True)
    return dest


def wheel_requires_dist(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as zf:
        metas = [n for n in zf.namelist() if n.endswith('.dist-info/METADATA')]
        if len(metas) != 1:
            raise SystemExit('expected one METADATA in %s, got %s' % (wheel, metas))
        parsed = Parser().parsestr(zf.read(metas[0]).decode())
    return parsed.get_all('Requires-Dist') or []


def prove_zero_wheel_declares_kernel(zero_wheel: Path) -> None:
    reqs = wheel_requires_dist(zero_wheel)
    compact = [r.replace(' ', '') for r in reqs]
    if not any(r.startswith('django-trusts') for r in compact):
        raise SystemExit('Zero wheel METADATA missing django-trusts Requires-Dist: %s' % reqs)
    if not any(
        'django-trusts>=1.0.0.dev0' in r
        or r.startswith('django-trusts(>=1.0.0.dev0')
        for r in compact
    ):
        raise SystemExit('Zero wheel kernel pin missing 1.0.0.dev0: %s' % reqs)
    print('Zero wheel Requires-Dist', reqs)


def venv_python(venv_dir: Path) -> Path:
    return venv_dir / 'bin' / 'python'


def make_venv(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    run([sys.executable, '-m', 'virtualenv', str(path)], check=True)
    py = venv_python(path)
    run([str(py), '-m', 'pip', 'install', '--upgrade', 'pip'], check=True)
    return py


def pip_list_names(py: Path, env: dict) -> set[str]:
    out = run(
        [str(py), '-m', 'pip', 'list', '--format=json'],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return {row['name'].lower() for row in json.loads(out.stdout)}


def pip_show(py: Path, dist: str, env: dict) -> str:
    out = run(
        [str(py), '-m', 'pip', 'show', dist],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return out.stdout


def prove_empty_env_resolution(work: Path, kernel_wheel: Path, zero_wheel: Path) -> None:
    """Resolver-driven install; independent of whether 1.x is on PyPI.

    Clean venv, neither dist installed. One ``pip install`` of the Zero
    wheel with ``--no-index --find-links`` on both local dist directories
    (kernel wheel + Zero wheel) plus Django wheels so the index is
    complete. Do not preinstall the kernel. Do not ``--no-deps``.
    """
    print('=== resolver-driven install from local wheelhouse ===')
    django_links = work / 'django-links'
    django_links.mkdir()

    py = make_venv(work / 'venv-resolved')
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['PYTHONNOUSERSITE'] = '1'

    run(
        [str(py), '-m', 'pip', 'download', '-d', str(django_links),
         '--only-binary=:all:', DJANGO_REQ],
        check=True,
        env=env,
        cwd=str(work),
    )

    before = pip_list_names(py, env)
    if 'django-trusts' in before or 'django-trusts-zero' in before:
        raise SystemExit('clean venv already has django-trusts distributions: %s' % sorted(before))

    kernel_links = str(kernel_wheel.parent)
    zero_links = str(zero_wheel.parent)
    installed = run(
        [
            str(py), '-m', 'pip', 'install',
            '--no-index',
            '--find-links', kernel_links,
            '--find-links', zero_links,
            '--find-links', str(django_links),
            str(zero_wheel),
        ],
        check=True,
        env=env,
        cwd=str(work),
        capture_output=True,
        text=True,
    )
    log = (installed.stdout or '') + (installed.stderr or '')
    if kernel_wheel.name not in log:
        raise SystemExit(
            'pip did not pull the companion kernel wheel %s:\n%s'
            % (kernel_wheel.name, log)
        )
    if '--no-deps' in log:
        raise SystemExit('resolver install must not use --no-deps:\n%s' % log)

    after = pip_list_names(py, env)
    if 'django-trusts' not in after or 'django-trusts-zero' not in after:
        raise SystemExit('expected both distributions after resolver install, got %s' % sorted(after))

    kernel_show = pip_show(py, 'django-trusts', env)
    zero_show = pip_show(py, 'django-trusts-zero', env)
    if 'Version: 1.0.0.dev0' not in kernel_show:
        raise SystemExit('companion kernel version missing:\n%s' % kernel_show)
    if 'Version: 2.0.0.dev0' not in zero_show:
        raise SystemExit('authoritative Zero version missing:\n%s' % zero_show)
    print('resolver pulled', kernel_wheel.name, 'and', zero_wheel.name)

    run(
        [
            str(py), '-P', '-c',
            'from django.conf import settings\n'
            'settings.configure(SECRET_KEY="pair", USE_TZ=True, '
            'INSTALLED_APPS=["django.contrib.contenttypes","django.contrib.auth",'
            '"trusts.apps.KernelConfig","trusts.zero.apps.ZeroConfig"], '
            'AUTHENTICATION_BACKENDS=["trusts.zero.backends.TrustModelBackend"], '
            'DATABASES={"default":{"ENGINE":"django.db.backends.sqlite3","NAME":":memory:"}})\n'
            'import django; django.setup()\n'
            'import trusts, trusts.context, trusts.trustee, trusts.path, trusts.conditions, trusts.zero\n'
            'from trusts.apps import KernelConfig\n'
            'from trusts.zero.apps import ZeroConfig\n'
            'from trusts.zero.models import Trust\n'
            'assert KernelConfig.label == "trusts_kernel"\n'
            'assert ZeroConfig.name == "trusts.zero" and ZeroConfig.label == "trusts"\n'
            'assert Trust._meta.app_label == "trusts"\n'
            'print("resolved wheel import ok", trusts.__file__, Trust)'
        ],
        check=True,
        env=env,
        cwd=str(work),
    )
    print('wheelhouse resolver install ok')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--kernel',
        type=Path,
        default=Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')),
    )
    args = parser.parse_args()
    kernel_root = args.kernel.resolve()
    if not (kernel_root / 'pyproject.toml').is_file():
        raise SystemExit('kernel checkout not found: %s' % kernel_root)

    try:
        import django  # noqa: F401
    except ImportError:
        raise SystemExit('install Django>=6.1,<6.2 in this environment before running')

    name, version, deps = assert_this_repo_is_authoritative()
    assert_kernel_mirror_matches(kernel_root, name, version, deps)
    assert_split_kernel(kernel_root)

    env = os.environ.copy()
    env.pop('DJANGO_SETTINGS_MODULE', None)
    env.pop('PYTHONPATH', None)

    with tempfile.TemporaryDirectory(prefix='django-trusts-zero-pair-') as tmp:
        work = Path(tmp)
        build_venv = work / 'venv-build'
        py_build = make_venv(build_venv)
        run([str(py_build), '-m', 'pip', 'install', 'build', 'wheel'], check=True)
        kdist, zdist = work / 'dist-kernel', work / 'dist-zero'
        kdist.mkdir()
        zdist.mkdir()
        run(
            [str(py_build), '-m', 'build', '--wheel', '--outdir', str(kdist), str(kernel_root)],
            check=True,
        )
        run(
            [str(py_build), '-m', 'build', '--wheel', '--outdir', str(zdist), str(ROOT)],
            check=True,
        )
        kernel_wheels = [w for w in kdist.glob('*.whl') if 'zero' not in w.name]
        zero_wheels = list(zdist.glob('django_trusts_zero-*.whl'))
        if len(kernel_wheels) != 1 or len(zero_wheels) != 1:
            raise SystemExit('expected one kernel wheel and one Zero wheel, got %s %s' % (
                kernel_wheels, zero_wheels,
            ))
        kernel_wheel, zero_wheel = kernel_wheels[0], zero_wheels[0]
        print('kernel wheel', kernel_wheel.name)
        print('zero wheel', zero_wheel.name)
        prove_zero_wheel_declares_kernel(zero_wheel)
        prove_empty_env_resolution(work, kernel_wheel, zero_wheel)

        print('=== install matrix against companion kernel ===')
        matrix_env = env.copy()
        matrix_env['KERNEL_CHECKOUT'] = str(kernel_root)
        run([sys.executable, str(MATRIX), '--kernel', str(kernel_root)], check=True, env=matrix_env)

        # upgrade-current mutates KERNEL_CHECKOUT (strips in-tree zero between
        # phases). Use a copy so the original companion checkout stays intact.
        upgrade_kernel = copy_kernel(kernel_root, work / 'kernel-upgrade')
        print('=== AppConfig / migration / import against companion ===')
        mig_env = env.copy()
        mig_env['KERNEL_CHECKOUT'] = str(upgrade_kernel)
        run([sys.executable, str(ROOT / 'scripts' / 'verify-upgrade-current.py')], check=True, env=mig_env)

        # Fresh/legacy/unit tests must load THIS package's trusts.zero, not a
        # vendored kernel copy. Strip on a second copy.
        test_kernel = copy_kernel(kernel_root, work / 'kernel-stripped', strip_zero=True)
        test_env = env.copy()
        test_env['KERNEL_CHECKOUT'] = str(test_kernel)
        run([sys.executable, str(ROOT / 'scripts' / 'verify-fresh-install.py')], check=True, env=test_env)
        run([sys.executable, str(ROOT / 'scripts' / 'verify-legacy-upgrade.py')], check=True, env=test_env)
        run([sys.executable, '-m', 'tests.runtests'], check=True, env=test_env, cwd=str(ROOT))
    print('companion pair ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
