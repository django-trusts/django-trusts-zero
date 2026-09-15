"""#149 R7: companion pin is the exact django-trusts 1.0.0rc1; checkout fails closed."""

import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from tests.runtests import NORMAL_SUITE


ROOT = Path(__file__).resolve().parents[1]
KERNEL_CANDIDATE = 'b85bf44e610c53a99d4fc743b14a079340a256f2'
STALE_KERNEL_R5B = '91e1fb690e14a88626ff3c1c05b137da96c6b254'
STALE_KERNEL_211 = '8bfe6151b5a65af2d0667ab3a71680eecc90a691'


def _load_kernel_checkout():
    path = ROOT / 'scripts' / 'verify-kernel-checkout.py'
    spec = importlib.util.spec_from_file_location('verify_kernel_checkout', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_git_checkout(root):
    env = os.environ.copy()
    env['GIT_AUTHOR_NAME'] = 'R5B'
    env['GIT_AUTHOR_EMAIL'] = 'r5b@example.test'
    env['GIT_COMMITTER_NAME'] = 'R5B'
    env['GIT_COMMITTER_EMAIL'] = 'r5b@example.test'
    subprocess.run(['git', 'init'], cwd=str(root), check=True, capture_output=True)
    subprocess.run(
        ['git', 'config', 'user.email', 'r5b@example.test'],
        cwd=str(root),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ['git', 'config', 'user.name', 'R5B'],
        cwd=str(root),
        check=True,
        capture_output=True,
    )
    (root / 'README').write_text('r5b probe\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'README'], cwd=str(root), check=True, capture_output=True)
    subprocess.run(
        ['git', '-c', 'commit.gpgsign=false', 'commit', '-m', 'r5b probe'],
        cwd=str(root),
        check=True,
        capture_output=True,
        env=env,
    )
    return subprocess.check_output(
        ['git', '-C', str(root), 'rev-parse', 'HEAD'],
        text=True,
    ).strip()


class ExactDjangoTrustsCandidatePinTest(SimpleTestCase):
    def test_suite_lists_this_module(self):
        self.assertIn('tests.test_issue149', NORMAL_SUITE)

    def test_ci_and_verifier_pin_the_exact_django_trusts_candidate(self):
        ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text()
        verifier = (ROOT / 'scripts' / 'verify-kernel-checkout.py').read_text()
        self.assertIn('COMPANION_KERNEL_SHA: %s' % KERNEL_CANDIDATE, ci)
        self.assertIn("KERNEL_HEAD = '%s'" % KERNEL_CANDIDATE, verifier)
        self.assertNotIn(STALE_KERNEL_R5B, ci)
        self.assertNotIn(STALE_KERNEL_R5B, verifier)
        self.assertNotIn(STALE_KERNEL_211, ci)
        self.assertNotIn(STALE_KERNEL_211, verifier)
        self.assertNotIn('#211', ci)
        self.assertNotIn('C-methods', ci)
        self.assertNotIn('django-trusts#211', ci)
        self.assertNotIn('pair with merged core C-methods', ci)
        self.assertIn('pair with exact django-trusts candidate', ci)
        self.assertEqual(ci.count('python scripts/verify-kernel-checkout.py'), 3)
        self.assertIn('assert_kernel_checkout_matches_head(kernel_root, expected)', verifier)
        self.assertNotIn("print('kernel_head', KERNEL_HEAD)", verifier)
        verifier_mod = _load_kernel_checkout()
        self.assertEqual(verifier_mod.KERNEL_HEAD, KERNEL_CANDIDATE)

    def test_verifier_fails_when_checkout_head_does_not_match(self):
        verifier_mod = _load_kernel_checkout()
        tmp = Path(tempfile.mkdtemp(prefix='trusts-r5b-mismatch-'))
        try:
            head = _init_git_checkout(tmp)
            self.assertNotEqual(head, KERNEL_CANDIDATE)
            with self.assertRaises(SystemExit) as ctx:
                verifier_mod.assert_kernel_checkout_matches_head(tmp)
            message = str(ctx.exception)
            self.assertIn(head, message)
            self.assertIn(KERNEL_CANDIDATE, message)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_verifier_fails_when_checkout_is_not_git(self):
        verifier_mod = _load_kernel_checkout()
        tmp = Path(tempfile.mkdtemp(prefix='trusts-r5b-nogit-'))
        try:
            with self.assertRaises(SystemExit) as ctx:
                verifier_mod.assert_kernel_checkout_matches_head(tmp)
            self.assertIn(str(tmp), str(ctx.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_verifier_accepts_checkout_that_resolves_to_expected(self):
        verifier_mod = _load_kernel_checkout()
        tmp = Path(tempfile.mkdtemp(prefix='trusts-r5b-match-'))
        try:
            head = _init_git_checkout(tmp)
            resolved = verifier_mod.assert_kernel_checkout_matches_head(
                tmp,
                expected=head,
            )
            self.assertEqual(resolved, head)
            self.assertEqual(verifier_mod.resolved_kernel_head(tmp), head)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
