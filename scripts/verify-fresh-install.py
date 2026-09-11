#!/usr/bin/env python3
"""Fresh Zero install on core 1.0.0.dev3: no kernel AppConfig, identity, --check."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.pop('DJANGO_SETTINGS_MODULE', None)


def _put_kernel_first():
    kernel = Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')).resolve()
    root = ROOT.resolve()
    cleaned = []
    for p in sys.path:
        if '__editable__.django_trusts' in str(p):
            continue
        abs_p = Path(p or os.getcwd()).resolve()
        if abs_p in {root, kernel}:
            continue
        if (abs_p / 'trusts' / '__init__.py').is_file() and abs_p != kernel:
            continue
        cleaned.append(p)
    sys.path[:] = cleaned
    if kernel.is_dir():
        sys.path.insert(0, str(kernel))
    sys.path.append(str(root))


_put_kernel_first()

TRUSTS_TABLES = (
    'trusts_trust',
    'trusts_trustuserpermission',
    'trusts_trust_groups',
    'trusts_trustgrouppermission',
    'trusts_role',
    'trusts_rolepermission',
)

CONTENT_TYPE_KEYS = (
    ('trusts', 'trust'),
    ('trusts', 'trustuserpermission'),
    ('trusts', 'trustgroup'),
    ('trusts', 'trustgrouppermission'),
    ('trusts', 'role'),
    ('trusts', 'rolepermission'),
)


def configure(db_path: Path) -> None:
    from django.conf import settings

    if settings.configured:
        raise SystemExit('Django already configured')
    settings.configure(
        SECRET_KEY='zero-fresh-install',
        USE_TZ=True,
        DEFAULT_AUTO_FIELD='django.db.models.AutoField',
        SILENCED_SYSTEM_CHECKS=['fields.W342'],
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'django.contrib.sessions',
            'django.contrib.admin',
            'trusts.zero.apps.ZeroConfig',
        ],
        AUTHENTICATION_BACKENDS=[
            'django.contrib.auth.backends.ModelBackend',
            'trusts.zero.backends.TrustModelBackend',
        ],
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': str(db_path),
            }
        },
    )


def _applied_trusts(connection) -> set[str]:
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    return {name for app, name in recorder.applied_migrations() if app == 'trusts'}


def _trusts_plan(connection):
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return [
        (migration.app_label, migration.name, backwards)
        for migration, backwards in plan
        if migration.app_label == 'trusts'
    ]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='django-trusts-zero-fresh-') as tmp:
        db_path = Path(tmp) / 'fresh.sqlite3'
        configure(db_path)

        import django
        from django.core.management import call_command
        from django.db import connection
        from io import StringIO

        django.setup()
        call_command('migrate', verbosity=0, interactive=False)

        applied = _applied_trusts(connection)
        if applied != {'0001_initial', '0002_trustgroup'}:
            raise SystemExit('fresh applied set %s' % applied)
        if _trusts_plan(connection):
            raise SystemExit('fresh install still has pending Trusts migrations: %s' % (
                _trusts_plan(connection),
            ))

        tables = set(connection.introspection.table_names())
        missing = [name for name in TRUSTS_TABLES if name not in tables]
        if missing:
            raise SystemExit('missing tables: %s' % missing)

        from trusts.zero.models import Trust
        from django.contrib.contenttypes.models import ContentType
        from django.apps import apps as django_apps
        import trusts.apps as trusts_apps
        from trusts.apps import implementation_configs
        from trusts.zero.apps import ZeroConfig, zero_config

        config = django_apps.get_app_config('trusts')
        if type(config) is not ZeroConfig:
            raise SystemExit('get_app_config("trusts") is not ZeroConfig')
        if config.name != 'trusts.zero' or config.label != 'trusts':
            raise SystemExit('ZeroConfig identity drifted')
        owners = implementation_configs()
        if owners != (zero_config(),) or len(owners) != 1:
            raise SystemExit('expected exactly one implementation owner, got %r' % (owners,))
        if hasattr(trusts_apps, 'AppConfig') or hasattr(trusts_apps, 'kernel_config'):
            raise SystemExit('core still exposes AppConfig or kernel_config')
        labels = {row.label for row in django_apps.get_app_configs()}
        if 'trusts_core' in labels:
            raise SystemExit('core AppConfig label trusts_core is installed')

        root = Trust.objects.get(pk=1)
        if root.trust_id != root.pk:
            raise SystemExit('root is not self-referential')

        found = {
            (ct.app_label, ct.model)
            for ct in ContentType.objects.filter(app_label='trusts')
        }
        missing_ct = set(CONTENT_TYPE_KEYS) - found
        if missing_ct:
            raise SystemExit('missing content types: %s' % missing_ct)

        sql_0001 = StringIO()
        call_command('sqlmigrate', 'trusts', '0001_initial', stdout=sql_0001)
        sql_0002 = StringIO()
        call_command('sqlmigrate', 'trusts', '0002_trustgroup', stdout=sql_0002)
        sql1 = sql_0001.getvalue()
        sql2 = sql_0002.getvalue()
        for table in (
            'trusts_trust',
            'trusts_trustuserpermission',
            'trusts_role',
            'trusts_rolepermission',
        ):
            if table not in sql1:
                raise SystemExit('sqlmigrate 0001 missing %s' % table)
        if 'trusts_trustgrouppermission' not in sql2:
            raise SystemExit('sqlmigrate 0002 missing trusts_trustgrouppermission')
        lowered = sql2.lower()
        if 'create table' in lowered and 'trusts_trust_groups' in lowered:
            create_groups = (
                'create table "trusts_trust_groups"' in lowered
                or 'create table trusts_trust_groups' in lowered
            )
            if create_groups:
                raise SystemExit('sqlmigrate 0002 must not CREATE trusts_trust_groups')

        from django.core.management.base import CommandError
        try:
            call_command('makemigrations', 'trusts', check=True, verbosity=1)
        except CommandError as exc:
            raise SystemExit('makemigrations --check failed: %s' % exc)

        if _trusts_plan(connection):
            raise SystemExit('already-current plan not empty')

        print('fresh install ok')
        print('django', django.get_version())
        print('applied', sorted(applied))
        print('tables', ' '.join(TRUSTS_TABLES))
        print('root', root.pk, root.title)
        print('makemigrations --check quiet')
        print('already-current migrate --plan empty')
        print('no core AppConfig; one ZeroConfig owner')
    return 0


if __name__ == '__main__':
    os.chdir(ROOT)
    raise SystemExit(main())
