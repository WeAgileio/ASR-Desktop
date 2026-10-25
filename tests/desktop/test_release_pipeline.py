"""Release repairs preserve published bytes and fail closed on conflicts."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release_pipeline', Path(__file__).resolve().parents[2] / 'desktop/scripts/release_pipeline.py')
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)
TAG = 'v0.2.0-beta.2'
PLAN = {'tag': TAG, 'tag_object': 'annotation', 'commit': 'commit', 'mode': 'repair-release'}


class FakeGitHub:
    def __init__(self, existing=None, draft=False):
        self.identity_value = {'tag_object': 'annotation', 'commit': 'commit'}
        self.value = None if existing is None else {'tag_name': TAG, 'prerelease': True, 'draft': draft, 'body': 'keep notes', 'html_url': 'https://example.test/release'}
        self.files = dict(existing or {})
        self.creates = 0
        self.uploads = []
        self.fail_hash = False
        self.race = False
        self.corrupt = False

    def identity(self, tag): return self.identity_value.copy()
    def release(self, tag):
        if self.value is None: return None
        return {**self.value, 'assets': [{'id': name, 'name': name, 'size': len(data), 'state': 'uploaded'} for name, data in self.files.items()]}
    def download(self, asset, path): path.write_bytes(self.files[asset['id']] + (b'corrupt' if self.corrupt else b''))
    def create(self, tag, notes):
        self.creates += 1
        self.value = {'tag_name': tag, 'prerelease': True, 'draft': False, 'body': notes, 'html_url': 'https://example.test/release'}
    def upload(self, tag, path):
        if self.fail_hash and path.name.endswith('.sha256'): raise RuntimeError('upload failed')
        self.uploads.append(path.name)
        self.files[path.name] = path.read_bytes()
        if self.race: raise RuntimeError('already uploaded by competitor')


class ReleasePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.dmg, self.sha = rp.names(TAG)
        (self.directory / self.dmg).write_bytes(b'verified image fixture')
        digest = rp.verify_files(self.directory, TAG, verify=lambda *_: None)
        (self.directory / 'verified.json').write_text(json.dumps({'tag': TAG, 'commit': 'commit', 'sha256': digest}))
        (self.directory / 'release-notes.md').write_text('new notes')
        self.files = {name: (self.directory / name).read_bytes() for name in (self.dmg, self.sha)}

    def test_tag_input_and_annotation(self):
        self.assertEqual(rp.version_for(TAG), '0.2.0b2')
        for value in ['', 'main', 'v1.0.0', 'v01.0.0-beta.1', 'v1.0.0-beta.1\n', '../x']:
            with self.assertRaises(ValueError): rp.version_for(value)
        github = rp.GitHub('owner/repo')
        with patch.object(github, 'api', return_value={'object': {'type': 'commit', 'sha': 'x'}}):
            with self.assertRaisesRegex(ValueError, 'annotated'): github.identity(TAG)

    def test_build_only_cannot_publish(self):
        source = self.directory / 'source'
        source.mkdir()
        (source / 'pyproject.toml').write_text('[project]\nversion = "0.2.0b2"\n')
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_SHA': 'current'}), \
             patch.object(rp.GitHub, 'api', side_effect=AssertionError('build-only must not call GitHub')):
            with patch('sys.argv', ['release_pipeline', 'plan', '--directory', str(self.directory), '--source', str(source)]):
                rp.main()
            plan = json.loads((self.directory / 'plan.json').read_text())
            self.assertEqual(plan['mode'], 'build-only')
            self.assertEqual(plan['commit'], 'current')
            with patch('sys.argv', ['release_pipeline', 'publish', '--directory', str(self.directory)]):
                with self.assertRaisesRegex(ValueError, 'cannot publish'): rp.main()

    def test_source_version_notes_and_old_tools(self):
        source = self.directory / 'source'
        (source / 'desktop/scripts').mkdir(parents=True)
        (source / 'pyproject.toml').write_text('[project]\nversion = "0.2.0b2"\n')
        (source / 'README.md').write_text('### v0.2.0-beta.2\nActual notes\n### other\nnot these\n')
        with self.assertRaisesRegex(ValueError, 'lacks packaging'): rp.source_notes(source, TAG)
        for name in ['build_app.py', 'package_release.py', 'verify_runtime.py', 'build_media.py']:
            (source / 'desktop/scripts' / name).touch()
        self.assertEqual(rp.source_notes(source, TAG), 'Actual notes\n')
        (source / 'README.md').write_text('### other\nnotes')
        with self.assertRaisesRegex(ValueError, 'notes missing'): rp.source_notes(source, TAG)
        (source / 'pyproject.toml').write_text('[project]\nversion = "0.2.0b3"\n')
        with self.assertRaisesRegex(ValueError, 'version'): rp.source_notes(source, TAG)

    def test_prepare_all_asset_states(self):
        for existing, build in [(None, True), ({}, True), ({self.dmg: self.files[self.dmg]}, False),
                                ({self.sha: self.files[self.sha]}, True), (self.files, False)]:
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as temp:
                github = FakeGitHub(existing)
                self.assertEqual(rp.prepare(github, PLAN, Path(temp)), build)
                for name, data in (existing or {}).items(): self.assertEqual((Path(temp) / name).read_bytes(), data)

    def test_publish_missing_and_preserve_metadata(self):
        for existing in [None, {}, {self.dmg: self.files[self.dmg]}, {self.sha: self.files[self.sha]}, self.files]:
            with self.subTest(existing=existing):
                github = FakeGitHub(existing, draft=True)
                github.files['unrelated.zip'] = b'keep'
                result = rp.publish(github, PLAN, self.directory)
                self.assertEqual(github.creates, int(existing is None))
                self.assertEqual(set(github.uploads), set(self.files) - set(existing or {}))
                self.assertEqual(github.files['unrelated.zip'], b'keep')
                if existing is not None:
                    self.assertTrue(result['draft'])
                    self.assertEqual(github.value['body'], 'keep notes')
                rp.publish(github, PLAN, self.directory)
                self.assertEqual(github.creates, int(existing is None))

    def test_conflicts_and_changed_identity(self):
        (self.directory / self.sha).write_text('0' * 64 + '  ' + self.dmg + '\n')
        with self.assertRaisesRegex(ValueError, 'conflicts'): rp.verify_files(self.directory, TAG, verify=lambda *_: None)
        (self.directory / self.sha).write_bytes(self.files[self.sha])
        github = FakeGitHub(self.files)
        github.identity_value['commit'] = 'moved'
        with self.assertRaisesRegex(ValueError, 'changed'): rp.publish(github, PLAN, self.directory)
        self.assertEqual(github.uploads, [])
        github = FakeGitHub(self.files)
        github.value['prerelease'] = False
        with self.assertRaisesRegex(ValueError, 'channel conflict'): rp.prepare(github, PLAN, self.directory)
        with self.assertRaisesRegex(ValueError, 'broken image'):
            rp.verify_files(self.directory, TAG, verify=lambda *_: (_ for _ in ()).throw(ValueError('broken image')))

    def test_partial_retry_race_and_remote_mismatch(self):
        github = FakeGitHub()
        github.fail_hash = True
        with self.assertRaises(RuntimeError): rp.publish(github, PLAN, self.directory)
        self.assertIn(self.dmg, github.files)
        self.assertNotIn(self.sha, github.files)
        github.fail_hash = False
        rp.publish(github, PLAN, self.directory)
        self.assertEqual(github.uploads.count(self.dmg), 1)
        self.assertEqual(github.creates, 1)
        github = FakeGitHub({})
        github.race = True
        rp.publish(github, PLAN, self.directory)
        github.corrupt = True
        with self.assertRaisesRegex(ValueError, 'conflicts'): rp.publish(github, PLAN, self.directory)

    def test_duplicate_zero_and_unfinished_assets(self):
        release = FakeGitHub(self.files).release(TAG)
        for mutate in [lambda r: r['assets'].append(copy.deepcopy(r['assets'][0])),
                       lambda r: r['assets'][0].update(size=0), lambda r: r['assets'][0].update(state='starter')]:
            bad = copy.deepcopy(release); mutate(bad)
            with self.assertRaisesRegex(ValueError, 'incomplete'): rp.assets_for(bad, TAG)
