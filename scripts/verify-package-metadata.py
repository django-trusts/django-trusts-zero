#!/usr/bin/env python3
"""Prove wheel/sdist identity: Zero 1.0.0.dev0, core floor, BSD-2-Clause, LICENSE."""

from __future__ import annotations

import os
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = '1.0.0.dev0'
EXPECTED_NAME = 'django-trusts-zero'
EXPECTED_CORE = 'django-trusts>=1.0.0.dev3,<2'


def _dist() -> Path:
    return ROOT / 'dist'


def _require_dist(files: list[Path], kind: str) -> Path:
    if not files:
        raise SystemExit('no %s in dist/' % kind)
    return files[-1]


def _core_floor_ok(requires: list[str]) -> bool:
    compact = [item.replace(' ', '') for item in requires]
    return any(
        'django-trusts' in item
        and '>=1.0.0.dev3' in item
        and '<2' in item
        for item in compact
    )


def _check_metadata(meta_text: str, origin: str) -> None:
    meta = Parser().parsestr(meta_text)
    if meta.get('Name') != EXPECTED_NAME:
        raise SystemExit('%s Name is %r, expected %s' % (origin, meta.get('Name'), EXPECTED_NAME))
    if meta.get('Version') != EXPECTED_VERSION:
        raise SystemExit(
            '%s Version is %r, expected %s' % (origin, meta.get('Version'), EXPECTED_VERSION)
        )
    requires = meta.get_all('Requires-Dist') or []
    if not _core_floor_ok(requires):
        raise SystemExit('%s missing core floor %s; got %r' % (origin, EXPECTED_CORE, requires))
    license_expr = meta.get('License-Expression') or meta.get('License') or ''
    if 'BSD-2-Clause' not in license_expr:
        raise SystemExit('%s license is %r, expected BSD-2-Clause' % (origin, license_expr))
    description = meta.get('Description') or meta_text
    if 'pip install django-trusts-zero' not in description:
        raise SystemExit('%s long description is not the user README' % origin)
    if 'IIa' in description or '2.0.0.dev' in description or 'kernel_config' in description:
        raise SystemExit('%s long description still contains internal-status language' % origin)


def _check_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        meta_name = next(
            (name for name in names if name.endswith('.dist-info/METADATA')),
            None,
        )
        if meta_name is None:
            raise SystemExit('wheel missing METADATA: %s' % wheel.name)
        _check_metadata(zf.read(meta_name).decode(), wheel.name)
        license_hits = [
            name for name in names
            if name.endswith('/LICENSE') or name.endswith('.dist-info/LICENSE')
        ]
        if not license_hits:
            raise SystemExit('wheel missing LICENSE: %s' % names[-20:])
        notice = zf.read(license_hits[0]).decode()
        if 'Copyright (c) 2015-2026, BeeDesk, Inc.' not in notice:
            raise SystemExit('wheel LICENSE notice is not BeeDesk 2015-2026')
        if 'django_trusts_zero-1.0.0.dev0' not in wheel.name:
            raise SystemExit('wheel filename is not 1.0.0.dev0: %s' % wheel.name)
        if any(name.endswith('migrates.md') for name in names):
            raise SystemExit('wheel must not vendor migrates.md: %s' % wheel.name)
    print('wheel metadata ok', wheel.name)


def _check_sdist(sdist: Path) -> None:
    with tarfile.open(sdist, 'r:gz') as tf:
        names = tf.getnames()
        prefix = 'django_trusts_zero-1.0.0.dev0'
        if not any(name == prefix or name.startswith(prefix + '/') for name in names):
            raise SystemExit('sdist is not 1.0.0.dev0: %s' % sdist.name)
        license_name = next((name for name in names if name.endswith('/LICENSE')), None)
        if license_name is None:
            raise SystemExit('sdist missing LICENSE')
        notice = tf.extractfile(license_name).read().decode()
        if 'Copyright (c) 2015-2026, BeeDesk, Inc.' not in notice:
            raise SystemExit('sdist LICENSE notice is not BeeDesk 2015-2026')
        pkg_info = next((name for name in names if name.endswith('/PKG-INFO')), None)
        if pkg_info is None:
            raise SystemExit('sdist missing PKG-INFO')
        _check_metadata(tf.extractfile(pkg_info).read().decode(), sdist.name)
        readme_name = next((name for name in names if name.endswith('/README.md')), None)
        if readme_name is None:
            raise SystemExit('sdist missing README.md')
        migrates_name = next((name for name in names if name.endswith('/migrates.md')), None)
        if migrates_name is None:
            raise SystemExit('sdist missing migrates.md')
        migrates = tf.extractfile(migrates_name).read()
        if len(migrates) > 80000:
            raise SystemExit(
                'sdist migrates.md is %s bytes; executable route must stay '
                'far below the Core archive' % len(migrates)
            )
        migrates_text = migrates.decode()
        required_urls = (
            'https://github.com/django-trusts/django-trusts/blob/'
            'migration-archive-pre-1.0/migrates.md',
            'https://github.com/django-trusts/django-trusts/blob/'
            '7414886263faafb6edfb44c0c5fcf9fc8fa14e79/migrates.md',
        )
        for url in required_urls:
            if url not in migrates_text:
                raise SystemExit('sdist migrates.md missing archaeology URL %s' % url)
        for banned in ('# Issue #151 C1', '# Issue #8 recovery', '2.0.0.dev2'):
            if banned in migrates_text:
                raise SystemExit('sdist migrates.md still contains %r' % banned)
    print('sdist metadata ok', sdist.name)


def main() -> int:
    dist = _dist()
    wheels = sorted(dist.glob('django_trusts_zero-*.whl'))
    sdists = sorted(dist.glob('django_trusts_zero-*.tar.gz'))
    wheel = _require_dist(wheels, 'wheel')
    sdist = _require_dist(sdists, 'sdist')
    _check_wheel(wheel)
    _check_sdist(sdist)
    print('package metadata ok')
    print('zero', EXPECTED_NAME + '==' + EXPECTED_VERSION)
    print('requires', EXPECTED_CORE)
    print('license BSD-2-Clause')
    return 0


if __name__ == '__main__':
    os.chdir(ROOT)
    raise SystemExit(main())
