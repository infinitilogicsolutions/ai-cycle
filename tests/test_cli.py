import argparse
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_cycle import cli


class TestAiCycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'my-repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=self.repo, check=True)
        (self.repo / 'README.md').write_text('hello\n')
        subprocess.run(['git', 'add', '.'], cwd=self.repo, check=True)
        subprocess.run(['git', '-c', 'user.name=Unit', '-c', 'user.email=test@example.com',
                        'commit', '-qm', 'init'], cwd=self.repo, check=True)
        patcher = patch.dict(os.environ, {'AI_CYCLE_HOME': str(self.base / 'private')})
        patcher.start()
        self.addCleanup(patcher.stop)

    def setup_project(self):
        cli.setup_repo(self.repo, argparse.Namespace(base='main', build='true', test='true',
            codex_model='gpt-6.1-sol', claude_model='claude-sonnet-5-5',
            codex_reasoning='high', claude_effort='high', max_cycles=3, force=False, profile='balanced'))

    def test_private_config_does_not_touch_repo(self):
        self.setup_project()
        self.assertEqual(cli.git(self.repo, 'status', '--porcelain'), '')
        self.assertTrue(cli.workspace_root(self.repo).is_relative_to(self.base / 'private'))

    def test_prd_approval_required_and_detects_mutation(self):
        self.setup_project()
        prd = self.base / 'my-prd.md'
        prd.write_text('# Approved PRD\nAcceptance criteria: passes test.\n')
        cli.start(self.repo, argparse.Namespace(feature='new-payment', prd=str(prd)))
        with self.assertRaises(cli.CycleError):
            cli.run(self.repo, argparse.Namespace(feature='new-payment'))
        cli.approve(self.repo, argparse.Namespace(feature='new-payment', stage='prd', yes=True, note=None))
        folder, state = cli.get_state(self.repo, 'new-payment')
        cli.ensure_prd_unchanged(folder, state)
        (folder / 'prd.md').write_text('changed')
        with self.assertRaises(cli.CycleError):
            cli.ensure_prd_unchanged(folder, state)

    def test_show_exact_prd_and_missing_review(self):
        self.setup_project()
        from contextlib import redirect_stdout
        from io import StringIO
        prd = self.base / 'scope.md'
        prd.write_text('# Document to approve\nMust preserve API compatibility.\n')
        cli.start(self.repo, argparse.Namespace(feature='test-scope', prd=str(prd)))
        out = StringIO()
        with redirect_stdout(out):
            cli.show(self.repo, 'test-scope', 'prd')
        self.assertIn('Must preserve API compatibility.', out.getvalue())
        self.assertIn('PRIVATE artifact:', out.getvalue())
        with self.assertRaises(cli.CycleError):
            cli.show(self.repo, 'test-scope', 'review')

    def test_show_latest_review_and_private_spec_guard(self):
        self.setup_project()
        folder = cli.feature_root(self.repo, 'x')
        cli.write_state(folder, {'feature': 'x', 'phase': 'prd_approved'})
        report = folder / 'reviews' / 'spec-1.json'
        cli.save_json(report, {'approved': False, 'findings': ['Needs decision']})
        from contextlib import redirect_stdout
        from io import StringIO
        out = StringIO()
        with redirect_stdout(out):
            cli.show(self.repo, 'x', 'review')
        self.assertIn('Needs decision', out.getvalue())
        cli.write_state(folder, {'feature': 'x', 'phase': 'specs_approved',
                                 'spec_paths': ['/tmp/attacker-spec.md'] * 3})
        with self.assertRaises(cli.CycleError):
            cli.show(self.repo, 'x', 'spec')

    def test_guide_file_is_packaged(self):
        from contextlib import redirect_stdout
        from io import StringIO
        page = Path(cli.__file__).resolve().parent / 'web' / 'guide.html'
        self.assertTrue(page.is_file())
        out = StringIO()
        with redirect_stdout(out):
            cli.guide(open_browser=False)
        self.assertIn('file://', out.getvalue())
        self.assertIn('guide.html', out.getvalue())

    def test_guard_private_files_and_secrets(self):
        for item in ['specs/001/spec.md', '.specify/feature.json', '.env.production',
                     'key.pem', 'notes/plan.md', '.ai-cycle/state.json']:
            with self.subTest(item=item):
                with self.assertRaises(cli.CycleError):
                    cli.guard_stage_names([item])
        cli.guard_stage_names(['src/WalletController.cs', 'tests/WalletTests.cs'])

    def test_invalid_feature_slug(self):
        with self.assertRaises(cli.CycleError):
            cli.slug('???')

    def test_missing_build_is_not_pass(self):
        ok, desc = cli.run_project_command(self.repo, None, self.base, 'build', 1)
        self.assertTrue(ok)
        self.assertIn('MANUAL VALIDATION REQUIRED', desc)

    def test_architecture_approval_note_required(self):
        self.setup_project()
        folder = cli.feature_root(self.repo, 'a')
        state = {'feature': 'a', 'phase': 'awaiting_design_approval',
                 'resume_after_design': 'specs_approved'}
        cli.write_state(folder, state)
        with self.assertRaises(cli.CycleError):
            cli.approve(self.repo, argparse.Namespace(feature='a', stage='design', note='', yes=True))
        cli.approve(self.repo, argparse.Namespace(feature='a', stage='design',
                                                 note='Use existing service API.', yes=True))
        self.assertEqual(cli.get_state(self.repo, 'a')[1]['phase'], 'design_approved_pending_spec_review')

    def test_full_flow_with_mocked_agents(self):
        """Real Git branch, PRD approval, private artifacts, checks; fake paid agents."""
        self.setup_project()
        prd = self.base / 'prd.md'
        prd.write_text('# PRD\nAdd a feature with an acceptance test.\n')
        cli.start(self.repo, argparse.Namespace(feature='new-widget', prd=str(prd)))
        cli.approve(self.repo, argparse.Namespace(feature='new-widget', stage='prd', yes=True, note=None))
        folder = cli.feature_root(self.repo, 'new-widget')
        ws = folder / 'spec-kit'

        def fake_init(repo, folder):
            ws.mkdir(parents=True, exist_ok=True)
            return ws

        def fake_codex(repo, cwd, cfg, prompt, log, add_dir=None):
            spec_dir = ws / 'specs' / '001-new-widget'
            spec_dir.mkdir(parents=True, exist_ok=True)
            if cwd == ws:
                if '$speckit-specify' in prompt:
                    (spec_dir / 'spec.md').write_text('Specification. ' * 10)
                elif '$speckit-plan' in prompt:
                    (spec_dir / 'plan.md').write_text('Architecture plan. ' * 10)
                elif '$speckit-tasks' in prompt:
                    (spec_dir / 'tasks.md').write_text('Development tasks. ' * 10)
            else:
                (repo / 'src.py').write_text('def feature():\n    return True\n')

        def fake_claude(repo, cfg, prompt, log):
            return {'approved': True, 'requires_human_decision': False,
                    'findings': [], 'summary': 'Looks good'}

        with patch.object(cli, 'speckit_init', fake_init), \
             patch.object(cli, 'codex', fake_codex), \
             patch.object(cli, 'claude_review', fake_claude):
            cli.run(self.repo, argparse.Namespace(feature='new-widget'))
        _, state = cli.get_state(self.repo, 'new-widget')
        self.assertEqual(state['phase'], 'ready_for_pr')
        self.assertEqual(cli.git(self.repo, 'branch', '--show-current'), 'ai/new-widget')
        self.assertTrue((self.repo / 'src.py').exists())
        self.assertFalse((self.repo / 'specs').exists())
        self.assertTrue((ws / 'specs' / '001-new-widget' / 'spec.md').exists())
        with self.assertRaises(cli.CycleError):
            cli.publish(self.repo, argparse.Namespace(feature='new-widget', yes=False))


if __name__ == '__main__':
    unittest.main()
