#!/usr/bin/env python
"""Standalone test runner for django-trusts-zero."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import django
from django.conf import settings
from django.test.utils import get_runner


def _configure(*, with_kernel: bool) -> None:
    installed_apps = [
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "trusts.zero",
        "tests",
    ]
    if with_kernel:
        installed_apps.insert(2, "trusts")

    settings.configure(
        SECRET_KEY="django-trusts-zero-tests",
        INSTALLED_APPS=installed_apps,
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        USE_TZ=True,
        PASSWORD_HASHERS=[
            "django.contrib.auth.hashers.MD5PasswordHasher",
        ],
        MIDDLEWARE=[],
        ROOT_URLCONF="",
    )


def run_tests(verbosity: int = 1, failfast: bool = False, with_kernel: bool = False) -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "")
    _configure(with_kernel=with_kernel)
    django.setup()
    TestRunner = get_runner(settings)
    runner = TestRunner(verbosity=verbosity, failfast=failfast)
    labels = ["tests"]
    failures = runner.run_tests(labels)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run django-trusts-zero tests.")
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        default=1,
        dest="verbosity",
    )
    parser.add_argument(
        "--failfast",
        action="store_true",
        dest="failfast",
    )
    parser.add_argument(
        "--with-kernel",
        action="store_true",
        dest="with_kernel",
        help="Install django-trusts KernelConfig next to ZeroConfig.",
    )
    args = parser.parse_args(argv)
    return run_tests(
        verbosity=args.verbosity,
        failfast=args.failfast,
        with_kernel=args.with_kernel,
    )


if __name__ == "__main__":
    raise SystemExit(main())
