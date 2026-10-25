#!/usr/bin/env python3
"""Plan, verify and repair beta Release assets without replacing existing assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import quote

TAG = re.compile(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-beta\.(0|[1-9][0-9]*)')


def version_for(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError('Expected an existing annotated vX.Y.Z-beta.N tag')
    return f'{match[1]}.{match[2]}.{match[3]}b{match[4]}'


def names(tag):
    version_for(tag)
    name = f'ASR-Desktop-{tag}-arm64.dmg'
    return name, name + '.sha256'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checksum(text, name):
    match = re.fullmatch(r'([0-9a-fA-F]{64})  ' + re.escape(name) + r'\n?', text)
    if not match:
        raise ValueError('Invalid checksum file')
    return match[1].lower()


class GitHub:
    def __init__(self, repo):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('Invalid repository')
        self.repo = repo

    def api(self, path, payload=None, missing=False):
        command = ['gh', 'api', f'repos/{self.repo}/{path}']
        if payload is not None:
            command += ['--method', 'POST', '--input', '-']
        result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                                text=True, capture_output=True, timeout=60)
        if result.returncode:
            if missing and '(HTTP 404)' in result.stderr:
                return None
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)

    def identity(self, tag):
        version_for(tag)
        ref = self.api('git/ref/tags/' + quote(tag, safe=''))
        obj = ref['object']
        if obj['type'] != 'tag':
            raise ValueError('Tag must be annotated')
        tagged = self.api('git/tags/' + obj['sha'])
        if tagged['object']['type'] != 'commit':
            raise ValueError('Tag must point directly to a commit')
        return {'tag_object': obj['sha'], 'commit': tagged['object']['sha']}

    def release(self, tag):
        value = self.api('releases/tags/' + quote(tag, safe=''), missing=True)
        if value is not None:
            # The embedded assets array may be paginated; fetch all assets explicitly.
            assets = []
            for page in range(1, 101):
                items = self.api(f"releases/{value['id']}/assets?per_page=100&page={page}")
                assets.extend(items)
                if len(items) < 100:
                    break
            else:
                raise ValueError('Incomplete Release asset listing')
            value['assets'] = assets
        return value

    def download(self, asset, target):
        with target.open('wb') as stream:
            subprocess.run(['gh', 'api', f"repos/{self.repo}/releases/assets/{asset['id']}",
                            '-H', 'Accept: application/octet-stream'], stdout=stream, check=True, timeout=1800)
        if target.stat().st_size != asset['size']:
            raise ValueError('Downloaded asset size does not match')

    def create(self, tag, notes):
        return self.api('releases', {'tag_name': tag, 'name': tag, 'body': notes,
                                     'prerelease': True, 'draft': False, 'make_latest': 'false'})

    def upload(self, tag, path):
        # Deliberately no --clobber: a concurrent upload must be reconciled, not overwritten.
        subprocess.run(['gh', 'release', 'upload', tag, str(path), '--repo', self.repo], check=True, timeout=1800)


def assets_for(release, tag):
    if release is None:
        return {}
    if release['tag_name'] != tag or not release['prerelease']:
        raise ValueError('Release tag/channel conflict; existing metadata was not changed')
    result = {}
    for asset in release['assets']:
        if asset['name'] in names(tag):
            if asset['name'] in result or asset['state'] != 'uploaded' or asset['size'] <= 0:
                raise ValueError('Duplicate or incomplete existing asset')
            result[asset['name']] = asset
    return result


def assert_identity(github, plan):
    if github.identity(plan['tag']) != {key: plan[key] for key in ('tag_object', 'commit')}:
        raise ValueError('Target tag changed since planning; refusing publication')


def source_notes(source, tag):
    expected = version_for(tag)
    actual = tomllib.loads((source / 'pyproject.toml').read_text())['project']['version']
    if actual != expected:
        raise ValueError('Source version does not match tag')
    text = (source / 'README.md').read_text()
    section = re.search(r'^### ' + re.escape(tag) + r'(?:[^\S\n][^\n]*)?\n(.*?)(?=^### |\Z)', text, re.M | re.S)
    if not section or not section[1].strip():
        raise ValueError('Version release notes missing')
    for script in ('build_app.py', 'package_release.py', 'verify_runtime.py', 'build_media.py'):
        if not (source / 'desktop/scripts' / script).is_file():
            raise ValueError('Target source lacks packaging script: ' + script)
    return section[1].strip() + '\n'


def verify_image(image, tag, verifier=None):
    verifier = verifier or Path(__file__).with_name('verify_dmg.py')
    subprocess.run([sys.executable, str(verifier), '--image', str(image), '--expected-version', version_for(tag)], check=True)


def prepare(github, plan, directory):
    assert_identity(github, plan)
    found = assets_for(github.release(plan['tag']), plan['tag'])
    for name, asset in found.items():
        github.download(asset, directory / name)
    return names(plan['tag'])[0] not in found


def verify_files(directory, tag, verify=verify_image):
    dmg, sha = names(tag)
    image = directory / dmg
    verify(image, tag)
    actual = digest(image)
    hashfile = directory / sha
    if hashfile.exists() and checksum(hashfile.read_text(), dmg) != actual:
        raise ValueError('Existing checksum conflicts with DMG; no asset was replaced')
    hashfile.write_text(f'{actual}  {dmg}\n')
    return actual


def publish(github, plan, directory):
    tag = plan['tag']; dmg, sha = names(tag)
    verified = json.loads((directory / 'verified.json').read_text())
    if verified['tag'] != tag or verified['commit'] != plan['commit'] or verified['sha256'] != digest(directory / dmg):
        raise ValueError('Verified package identity changed')
    if checksum((directory / sha).read_text(), dmg) != verified['sha256']:
        raise ValueError('Local checksum changed')
    assert_identity(github, plan)
    release = github.release(tag)
    if release is None:
        try:
            github.create(tag, (directory / 'release-notes.md').read_text())
        except (RuntimeError, subprocess.CalledProcessError):
            if github.release(tag) is None:
                raise
    # Re-read before each upload; partial successes remain recoverable on rerun.
    verified_assets = {}
    for name in (dmg, sha):
        assert_identity(github, plan)
        found = assets_for(github.release(tag), tag)
        if name not in found:
            try:
                github.upload(tag, directory / name)
            except (RuntimeError, subprocess.CalledProcessError):
                found = assets_for(github.release(tag), tag)
                if name not in found:
                    raise
        found = assets_for(github.release(tag), tag)
        with tempfile.TemporaryDirectory() as temp:
            downloaded = Path(temp) / name
            github.download(found[name], downloaded)
            if digest(downloaded) != digest(directory / name):
                raise ValueError('Existing or uploaded asset conflicts: ' + name)
        verified_assets[name] = (found[name]['id'], found[name]['size'])
    assert_identity(github, plan)
    result = github.release(tag)
    found = assets_for(result, tag)
    if {name: (asset['id'], asset['size']) for name, asset in found.items()} != verified_assets:
        raise ValueError('Release assets changed during final verification')
    return {**plan, 'url': result['html_url'], 'draft': result['draft'],
            'sha256': verified['sha256'], 'assets': [{k: a[k] for k in ('id', 'name', 'size')} for a in found.values()]}


def output(values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            for key, value in values.items():
                stream.write(f'{key}={value}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['plan', 'prepare', 'source', 'verify', 'publish'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--mode', choices=['build-only', 'repair-release', 'tag-push'], default='build-only')
    parser.add_argument('--tag', default='')
    args = parser.parse_args()
    directory = args.directory.resolve(); directory.mkdir(parents=True, exist_ok=True)
    if args.phase == 'plan':
        github = GitHub(os.environ['GITHUB_REPOSITORY'])
        tag = args.tag
        if args.mode == 'build-only':
            version = tomllib.loads((args.source / 'pyproject.toml').read_text())['project']['version']
            match = re.fullmatch(r'(\d+\.\d+\.\d+)b(\d+)', version)
            if not match: raise ValueError('Only beta packaging is supported')
            tag = f'v{match[1]}-beta.{match[2]}'
            identity = {'commit': os.environ['GITHUB_SHA'], 'tag_object': None}
        else:
            identity = github.identity(tag)
        plan = {'tag': tag, 'mode': args.mode, 'repository': github.repo,
                'control_commit': os.environ['GITHUB_SHA'], **identity}
        (directory / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
        output({'tag': tag, 'commit': identity['commit'], 'publish': str(args.mode != 'build-only').lower()})
    else:
        plan = json.loads((directory / 'plan.json').read_text()); tag = plan['tag']
        if args.phase == 'source':
            (directory / 'release-notes.md').write_text(source_notes(args.source, tag))
        elif args.phase == 'prepare':
            needed = True if plan['mode'] == 'build-only' else prepare(GitHub(plan['repository']), plan, directory)
            output({'build': str(needed).lower()})
        elif args.phase == 'verify':
            # A pre-existing hash in directory is authoritative; never copy over it.
            image = directory / names(tag)[0]
            if not image.exists():
                shutil.copy2(args.source / 'build/desktop' / image.name, image)
            sha = verify_files(directory, tag)
            (directory / 'verified.json').write_text(json.dumps({'tag': tag, 'commit': plan['commit'], 'sha256': sha}, indent=2) + '\n')
        else:
            if plan['mode'] == 'build-only': raise ValueError('Build-only cannot publish')
            try:
                result = publish(GitHub(plan['repository']), plan, directory)
                (directory / 'publication.json').write_text(json.dumps(result, indent=2) + '\n')
                print(json.dumps(result, indent=2))
                if os.environ.get('GITHUB_STEP_SUMMARY'):
                    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
                        stream.write(f"Verified Release: {result['url']}\n\nTag: `{tag}`, source: `{plan['commit']}`, SHA-256: `{result['sha256']}`\n")
            except Exception as error:
                try:
                    remaining = ', '.join(assets_for(GitHub(plan['repository']).release(tag), tag)) or '(none)'
                except Exception:
                    remaining = '(remote state could not be read; inspect Release before retrying)'
                message = f'Publication incomplete for {tag}: {error}\nPresent assets: {remaining}\n'
                print(message, file=sys.stderr)
                (directory / 'publication.json').write_text(json.dumps({'complete': False, 'tag': tag,
                    'error': str(error), 'present_assets': remaining}, indent=2) + '\n')
                if os.environ.get('GITHUB_STEP_SUMMARY'):
                    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
                        stream.write(message)
                raise


if __name__ == '__main__':
    main()
