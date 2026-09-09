# see https://docs.djangoproject.com/en/stable/topics/testing/advanced/#using-the-django-test-runner-to-test-reusable-applications
import os
import sys
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tests.settings')
root = Path(__file__).resolve().parents[1]
kernel = Path(os.environ.get('KERNEL_CHECKOUT', root / '.deps' / 'django-trusts'))

# This checkout has trusts/zero without trusts/__init__.py (a PEP 420
# namespace). If it precedes the kernel package, ``import trusts`` never
# loads kernel ``extend_path`` and ``trusts.context`` is missing. Keep the
# kernel checkout first; append this root so ``tests`` stays importable.
abs_root = str(root)
abs_kernel = str(kernel) if kernel.is_dir() else ''
sys.path = [
    p for p in sys.path
    if os.path.abspath(p or os.getcwd()) not in {abs_root, abs_kernel}
]
if abs_kernel:
    sys.path.insert(0, abs_kernel)
sys.path.append(abs_root)

import django
from django.test.utils import get_runner
from django.conf import settings


NORMAL_SUITE = [
    'tests.test_appconfig',
    'tests.test_migrations',
    'tests.test_packaging',
    'tests.test_smoke',
]


def runtests():
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=1, interactive=False)
    failures = test_runner.run_tests(NORMAL_SUITE)
    sys.exit(bool(failures))


if __name__ == '__main__':
    runtests()
