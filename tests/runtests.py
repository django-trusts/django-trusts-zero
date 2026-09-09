# see https://docs.djangoproject.com/en/stable/topics/testing/advanced/#using-the-django-test-runner-to-test-reusable-applications
import os
import sys
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tests.settings')
root = Path(__file__).resolve().parents[1].resolve()
kernel = Path(os.environ.get('KERNEL_CHECKOUT', root / '.deps' / 'django-trusts')).resolve()

# This checkout has trusts/zero without trusts/__init__.py (a PEP 420
# namespace). If it precedes the kernel package, ``import trusts`` never
# loads kernel ``extend_path`` and ``trusts.context`` is missing. Keep the
# kernel checkout first; append this root so ``tests`` stays importable.
# Drop other django-trusts checkouts (PYTHONPATH / leftover editable paths).
cleaned = []
for p in sys.path:
    if '__editable__.django_trusts' in str(p):
        continue
    abs_p = Path(p or os.getcwd()).resolve()
    if abs_p in {root, kernel}:
        continue
    if (abs_p / 'trusts' / '__init__.py').is_file():
        continue
    cleaned.append(p)
sys.path[:] = cleaned
sys.meta_path[:] = [
    f for f in sys.meta_path
    if '__editable___django_trusts' not in getattr(f, '__module__', '')
]
sys.path_hooks[:] = [h for h in sys.path_hooks if '__editable___django_trusts' not in repr(h)]
if kernel.is_dir():
    sys.path.insert(0, str(kernel))
sys.path.append(str(root))

import django
from django.test.utils import get_runner
from django.conf import settings


NORMAL_SUITE = [
    'tests.test_appconfig',
    'tests.test_migrations',
    'tests.test_packaging',
    'tests.test_smoke',
    'tests.test_s5_leftover_check',
]


def runtests():
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=1, interactive=False)
    failures = test_runner.run_tests(NORMAL_SUITE)
    sys.exit(bool(failures))


if __name__ == '__main__':
    runtests()
