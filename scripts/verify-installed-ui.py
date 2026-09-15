#!/usr/bin/env python3
"""Prove Zero URLs and templates render outside both source checkouts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


PROBE = r'''
import os
import sys
from pathlib import Path

site = Path(%r)
workdir = Path(%r)
os.chdir(workdir)
sys.path.insert(0, str(site))
os.environ.pop("DJANGO_SETTINGS_MODULE", None)

from django.conf import settings
from django.template.loader import get_template
from django.urls import include, path, reverse, set_urlconf

settings.configure(
    SECRET_KEY="zero-installed-ui",
    USE_TZ=True,
    DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django.contrib.sessions",
        "trusts.zero.apps.ZeroConfig",
    ],
    AUTHENTICATION_BACKENDS=[
        "django.contrib.auth.backends.ModelBackend",
        "trusts.zero.backends.TrustModelBackend",
    ],
    TEMPLATES=[{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "DIRS": [str(workdir / "templates")],
        "OPTIONS": {"context_processors": []},
    }],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)

import django
django.setup()

urlpatterns = [path("", include("trusts.zero.urls"))]
set_urlconf(__name__)

assert reverse("trusts:team_create") == "/teams/new/"
assert reverse("trusts:team_detail", args=[1]) == "/teams/1/"

form = get_template("trusts_zero/team_form.html")
detail = get_template("trusts_zero/team_detail.html")
form_html = form.render({})
detail_html = detail.render({
    "object": "Team One",
    "can_manage_members": False,
    "adduserform": None,
})
assert "Create new team" in form_html
assert "Team One" in detail_html
assert "Members" in detail_html
print("zero-installed-ui-ok")
'''


def main() -> int:
    kernel = Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')).resolve()
    if not kernel.is_dir():
        raise SystemExit('KERNEL_CHECKOUT missing at %s' % kernel)

    tmp = Path(tempfile.mkdtemp(prefix='trusts-zero-ui-'))
    try:
        site = tmp / 'site'
        kernel_site = tmp / 'kernel-site'
        zero_site = tmp / 'zero-site'
        work = tmp / 'work'
        site.mkdir()
        kernel_site.mkdir()
        zero_site.mkdir()
        work.mkdir()
        (work / 'templates').mkdir()
        (work / 'templates' / 'base.html').write_text(
            '{% block content %}{% endblock %}\n'
        )
        subprocess.check_call(
            [
                sys.executable, '-m', 'pip', 'install', '-q',
                '--target', str(kernel_site), str(kernel),
            ],
        )
        subprocess.check_call(
            [
                sys.executable, '-m', 'pip', 'install', '-q',
                '--target', str(zero_site), '--no-deps', str(ROOT),
            ],
        )
        # Kernel owns trusts/; Zero contributes trusts/zero/ only.
        shutil.copytree(kernel_site / 'trusts', site / 'trusts')
        if (zero_site / 'trusts' / 'zero').is_dir():
            shutil.copytree(zero_site / 'trusts' / 'zero', site / 'trusts' / 'zero')
        for extra in zero_site.iterdir():
            if extra.name in {'trusts', 'bin', 'share'}:
                continue
            dest = site / extra.name
            if extra.is_dir() and not dest.exists():
                shutil.copytree(extra, dest)
            elif extra.is_file() and not dest.exists():
                shutil.copy2(extra, dest)
        if not (site / 'trusts' / 'zero' / 'urls.py').is_file():
            raise SystemExit('installed site missing trusts.zero.urls')
        if not (site / 'trusts' / 'zero' / 'templates' / 'trusts_zero' / 'team_form.html').is_file():
            raise SystemExit('installed site missing Zero team templates')
        env = os.environ.copy()
        env.pop('DJANGO_SETTINGS_MODULE', None)
        env.pop('PYTHONPATH', None)
        out = subprocess.check_output(
            [sys.executable, '-c', PROBE % (str(site), str(work))],
            env=env,
            cwd=str(work),
            text=True,
        )
        if 'zero-installed-ui-ok' not in out:
            raise SystemExit('installed UI probe failed: %r' % out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('installed ui ok')
    return 0


if __name__ == '__main__':
    os.chdir(ROOT)
    raise SystemExit(main())
