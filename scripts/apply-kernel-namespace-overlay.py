#!/usr/bin/env python3
"""Insert pkgutil.extend_path into a django-trusts ``trusts/__init__.py``.

C1 does not yet ship ``extend_path`` (C2 requires it). Z1 tests against
C1 APIs need the kernel package to extend ``__path__`` so ``trusts.zero``
can load from this distribution. Idempotent.

Do not use this overlay to add Zero constants or concrete models back
onto the kernel package.
"""

from __future__ import annotations

import argparse
from pathlib import Path


MARKER = 'from pkgutil import extend_path'
SNIPPET = """from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

"""


def apply(kernel_root: Path) -> bool:
    init_path = kernel_root / 'trusts' / '__init__.py'
    if not init_path.is_file():
        raise SystemExit('No trusts/__init__.py in kernel checkout %s' % kernel_root)
    text = init_path.read_text()
    if MARKER in text:
        return False
    init_path.write_text(SNIPPET + text)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'kernel_root',
        type=Path,
        help='Checkout of django-trusts (kernel)',
    )
    args = parser.parse_args()
    changed = apply(args.kernel_root.resolve())
    print('kernel namespace overlay', 'applied' if changed else 'already present')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
