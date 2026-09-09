#!/usr/bin/env python3
"""Upgrade an already-applied 1.x (0001+0002) kernel database onto Zero.

Phase 1 uses the in-tree django-trusts concrete app (``INSTALLED_APPS=['trusts']``)
when the kernel checkout still ships ``trusts/migrations``. Phase 2 reopens
the same SQLite file with ``trusts.zero.apps.ZeroConfig``.

Expects ``KERNEL_CHECKOUT`` or ``.deps/django-trusts`` at
``624daa198d1922a43c775a814a3ff213cf5bd4d7`` (or a later kernel that still
exposes historical migrations under the ``trusts`` label).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    'trusts_trust',
    'trusts_trustuserpermission',
    'trusts_trust_groups',
    'trusts_trustgrouppermission',
    'trusts_role',
    'trusts_rolepermission',
)
TABLE_LITERAL = repr(TABLES)


PHASE1 = r'''
import json
import os
import sys
from pathlib import Path

kernel = Path(os.environ["KERNEL_CHECKOUT"]).resolve()
db_path = Path(os.environ["ZERO_UPGRADE_DB"]).resolve()
sys.path.insert(0, str(kernel))
os.environ.pop("DJANGO_SETTINGS_MODULE", None)

from django.conf import settings
settings.configure(
    SECRET_KEY="kernel-phase1",
    USE_TZ=True,
    DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    SILENCED_SYSTEM_CHECKS=["fields.W342"],
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django.contrib.sessions",
        "django.contrib.admin",
        "trusts",
    ],
    AUTHENTICATION_BACKENDS=["trusts.backends.TrustModelBackend"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(db_path)}},
)
import django
from django.core.management import call_command
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

django.setup()
from django.contrib.contenttypes.models import ContentType
call_command("migrate", verbosity=0, interactive=False)
applied = sorted(
    name for app, name in MigrationRecorder(connection).applied_migrations()
    if app == "trusts"
)
if applied != ["0001_initial", "0002_trustgroup"]:
    raise SystemExit("phase1 applied %s" % applied)
counts = {}
for table in __TABLES__:
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM %s" % table)
        counts[table] = c.fetchone()[0]
ctypes = sorted(
    (ct.app_label, ct.model)
    for ct in ContentType.objects.filter(app_label="trusts")
)
print(json.dumps({"applied": applied, "counts": counts, "content_types": ctypes}))
'''.replace('__TABLES__', TABLE_LITERAL)


PHASE2 = r'''
import json
import os
import sys
from pathlib import Path

from django.core.management.base import CommandError

zero = Path(os.environ["ZERO_CHECKOUT"]).resolve()
kernel = Path(os.environ["KERNEL_CHECKOUT"]).resolve()
db_path = Path(os.environ["ZERO_UPGRADE_DB"]).resolve()
sys.path.insert(0, str(kernel))
sys.path.append(str(zero))
os.environ.pop("DJANGO_SETTINGS_MODULE", None)

from django.conf import settings

apps = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.admin",
    "trusts.zero.apps.ZeroConfig",
]
apps_py = kernel / "trusts" / "apps.py"
if apps_py.is_file():
    text = apps_py.read_text()
    if "label = 'trusts_kernel'" in text or 'label = "trusts_kernel"' in text:
        apps.insert(4, "trusts.apps.KernelConfig")

settings.configure(
    SECRET_KEY="zero-phase2",
    USE_TZ=True,
    DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    SILENCED_SYSTEM_CHECKS=["fields.W342"],
    INSTALLED_APPS=apps,
    AUTHENTICATION_BACKENDS=["trusts.zero.backends.TrustModelBackend"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(db_path)}},
)
import django
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

django.setup()
from django.contrib.contenttypes.models import ContentType
before = json.loads(os.environ["PHASE1_SNAPSHOT"])
applied = sorted(
    name for app, name in MigrationRecorder(connection).applied_migrations()
    if app == "trusts"
)
if applied != before["applied"]:
    raise SystemExit("phase2 applied set changed: %s vs %s" % (applied, before["applied"]))

executor = MigrationExecutor(connection)
plan = [
    (m.app_label, m.name, backwards)
    for m, backwards in executor.migration_plan(executor.loader.graph.leaf_nodes())
    if m.app_label == "trusts"
]
if plan:
    raise SystemExit("already-applied 1.x plan not empty: %s" % plan)

call_command("migrate", verbosity=0, interactive=False)
applied_after = sorted(
    name for app, name in MigrationRecorder(connection).applied_migrations()
    if app == "trusts"
)
if applied_after != applied:
    raise SystemExit("migrate changed applied set: %s" % applied_after)

counts = {}
for table in __TABLES__:
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM %s" % table)
        counts[table] = c.fetchone()[0]
if counts != before["counts"]:
    raise SystemExit("row counts changed: %s vs %s" % (counts, before["counts"]))

ctypes = sorted((ct.app_label, ct.model) for ct in ContentType.objects.filter(app_label="trusts"))
need = {tuple(row) for row in before["content_types"]}
have = set(ctypes)
if not need.issubset(have):
    raise SystemExit("content types lost: %s" % (need - have))

try:
    call_command("makemigrations", "trusts", check=True, verbosity=1)
except CommandError as exc:
    raise SystemExit("makemigrations --check failed: %s" % exc)

print(json.dumps({"applied": applied, "counts": counts, "plan": plan}))
'''.replace('__TABLES__', TABLE_LITERAL)


def main() -> int:
    os.environ.pop('DJANGO_SETTINGS_MODULE', None)
    kernel = Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')).resolve()
    if not (kernel / 'trusts' / 'migrations' / '0001_initial.py').is_file():
        print('skip kernel→Zero already-applied upgrade (kernel checkout has no historical migrations)')
        return 0
    env_base = os.environ.copy()
    env_base['KERNEL_CHECKOUT'] = str(kernel)
    env_base['ZERO_CHECKOUT'] = str(ROOT)
    env_base.pop('DJANGO_SETTINGS_MODULE', None)
    with tempfile.TemporaryDirectory(prefix='django-trusts-zero-upgrade-current-') as tmp:
        db_path = Path(tmp) / 'current.sqlite3'
        env_base['ZERO_UPGRADE_DB'] = str(db_path)
        phase1 = subprocess.run(
            [sys.executable, '-c', PHASE1],
            env=env_base,
            capture_output=True,
            text=True,
        )
        if phase1.returncode != 0:
            sys.stderr.write(phase1.stdout)
            sys.stderr.write(phase1.stderr)
            raise SystemExit('phase1 failed')
        snapshot_line = phase1.stdout.strip().splitlines()[-1]
        snapshot = json.loads(snapshot_line)
        env_base['PHASE1_SNAPSHOT'] = snapshot_line
        phase2 = subprocess.run(
            [sys.executable, '-c', PHASE2],
            env=env_base,
            capture_output=True,
            text=True,
        )
        if phase2.returncode != 0:
            sys.stderr.write(phase2.stdout)
            sys.stderr.write(phase2.stderr)
            raise SystemExit('phase2 failed')
        print('phase1', snapshot)
        print('phase2', phase2.stdout.strip().splitlines()[-1])
        print('already-applied 1.x upgrade ok (empty trusts plan, unchanged counts)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
