#!/usr/bin/env python3
"""Fail unless KERNEL_CHECKOUT HEAD equals COMPANION_KERNEL_SHA.

Resolves ``git rev-parse HEAD`` at the checkout. Does not treat the
pin constant as proven merely by printing it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Exact django-trusts / kernel candidate.
KERNEL_HEAD = '91e1fb690e14a88626ff3c1c05b137da96c6b254'


def resolved_kernel_head(kernel_root: Path) -> str:
    """Return ``git rev-parse HEAD`` for the django-trusts checkout.

    Raises ``SystemExit`` if the path is not a git checkout whose HEAD
    can be resolved. Does not treat ``KERNEL_HEAD`` as proven.
    """
    try:
        completed = subprocess.run(
            ['git', '-C', str(kernel_root), 'rev-parse', 'HEAD'],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, 'stderr', None) or exc
        if isinstance(detail, str):
            detail = detail.strip() or exc
        raise SystemExit(
            'KERNEL_CHECKOUT HEAD could not be resolved at %s: %s'
            % (kernel_root, detail)
        ) from exc
    head = completed.stdout.strip()
    if not head:
        raise SystemExit('KERNEL_CHECKOUT HEAD is empty at %s' % kernel_root)
    return head


def assert_kernel_checkout_matches_head(kernel_root: Path, expected=None) -> str:
    """Fail unless the checkout at *kernel_root* is the exact candidate."""
    if expected is None:
        expected = KERNEL_HEAD
    head = resolved_kernel_head(kernel_root)
    if head != expected:
        raise SystemExit(
            'KERNEL_CHECKOUT HEAD %s does not match COMPANION_KERNEL_SHA %s'
            % (head, expected)
        )
    return head


def main() -> int:
    kernel_root = Path(
        os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')
    )
    expected = os.environ.get('COMPANION_KERNEL_SHA', KERNEL_HEAD)
    if expected != KERNEL_HEAD:
        raise SystemExit(
            'COMPANION_KERNEL_SHA %s does not match exact django-trusts '
            'candidate %s' % (expected, KERNEL_HEAD)
        )
    if not kernel_root.is_dir():
        raise SystemExit(
            'KERNEL_CHECKOUT missing: %s (expected exact django-trusts '
            'candidate %s)' % (kernel_root, KERNEL_HEAD)
        )
    head = assert_kernel_checkout_matches_head(kernel_root, expected)
    print('kernel_head', head)
    return 0


if __name__ == '__main__':
    sys.exit(main())
