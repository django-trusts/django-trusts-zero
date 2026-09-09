#!/usr/bin/env python3
"""Insert pkgutil.extend_path into a django-trusts ``trusts/__init__.py``.

Editable+editable installs need the kernel package to extend ``__path__``
so ``trusts.zero`` can load from a second sys.path entry. The kernel
Step 3 PR ships this itself (noun-independent-kernel-r3 §2). This
overlay is idempotent: if ``extend_path`` is already present, it is a
no-op.

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


def strip_in_tree_zero(kernel_root: Path) -> bool:
    """Remove companion-vendored ``trusts/zero`` so this package is not shadowed."""
    zero = kernel_root / 'trusts' / 'zero'
    if not zero.exists():
        return False
    import shutil
    shutil.rmtree(zero)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'kernel_root',
        type=Path,
        help='Checkout of django-trusts (kernel)',
    )
    parser.add_argument(
        '--strip-in-tree-zero',
        action='store_true',
        help='Delete trusts/zero from the kernel checkout if still vendored',
    )
    args = parser.parse_args()
    kernel_root = args.kernel_root.resolve()
    if args.strip_in_tree_zero:
        stripped = strip_in_tree_zero(kernel_root)
        print('in-tree trusts/zero', 'stripped' if stripped else 'absent')
    changed = apply(kernel_root)
    print('kernel namespace overlay', 'applied' if changed else 'already present')
    print('init', kernel_root / 'trusts' / '__init__.py')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
