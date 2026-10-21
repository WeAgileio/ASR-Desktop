#!/usr/bin/env python3
"""Build and verify an ad-hoc beta DMG; Git publication is a separate step."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-runtime', action='store_true',
                        help='Reuse a frozen runtime only if its recorded source fingerprints match')
    args = parser.parse_args()
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    match = re.fullmatch(r'(\d+\.\d+\.\d+)b(\d+)', version)
    if not match:
        parser.error('This ad-hoc distribution workflow requires a beta version such as 0.2.0b1')
    tag = f'v{match[1]}-beta.{match[2]}'
    python = ROOT / 'build/desktop/packaging-env/bin/python'
    if not python.is_file():
        parser.error('Prepare the locked Python packaging environment described in desktop/README.md first')
    def run(script, *arguments, interpreter=sys.executable):
        subprocess.run([str(interpreter), str(ROOT / 'desktop/scripts' / script), *map(str, arguments)],
                       cwd=ROOT, check=True)
    run('build_app.py')
    run('build_runtime.py', *(['--install-only'] if args.reuse_runtime else []), interpreter=python)
    run('collect_notices.py', interpreter=python)
    run('sign_development.py')
    build = ROOT / 'build/desktop'
    app = json.loads((build / 'development-signing.json').read_text())['app']
    image = build / f'ASR-Desktop-{tag}-arm64.dmg'
    run('build_dmg.py', '--app', app, '--output', image)
    run('verify_dmg.py', '--image', image)
    with image.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (build / (image.name + '.sha256')).write_text(f'{digest}  {image.name}\n')
    readme = (ROOT / 'README.md').read_text()
    section = re.search(r'^### '+re.escape(tag)+r'[^\n]*\n(.*?)(?=^### |\Z)', readme, re.M | re.S)
    if not section:
        raise SystemExit('README Release Notes missing for ' + tag)
    (build / 'release-notes.md').write_text(section[1].strip() + '\n')
    print(f'Verified beta: {image}\nTag: {tag}\nGit and GitHub have not been changed.')


if __name__ == '__main__':
    main()
