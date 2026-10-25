#!/usr/bin/env python3
"""Exercise two real development App bundles against disposable state on macOS."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import sqlite3
import subprocess
import tempfile
import time
import wave


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def identity(app):
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    assert info.get('ASRDesktopDevelopmentMode') is True, 'Requires explicit development bundles'
    return {'version': info.get('ASRDesktopReleaseVersion', info['CFBundleShortVersionString']),
            'cli_sha256': digest(app / 'Contents/MacOS/asr-desktop'),
            'runtime_sha256': digest(app / 'Contents/Resources/runtime/asr-desktop-runtime/asr-desktop-runtime')}


def clone(source, target):
    # APFS copy-on-write clones are independent files, never hard links.
    assert not target.exists()
    if source.stat().st_dev == target.parent.stat().st_dev:
        subprocess.run(['/bin/cp', '-cR', str(source), str(target)], check=True)
    else:
        subprocess.run(['/bin/cp', '-R', str(source), str(target)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-app', required=True, type=Path)
    parser.add_argument('--new-app', required=True, type=Path)
    parser.add_argument('--models', required=True, type=Path, help='Read-only source of prepared models')
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    old, new = args.old_app.resolve(), args.new_app.resolve()
    versions = [identity(old), identity(new)]
    assert versions[0]['version'] != versions[1]['version'], 'Use two distinct App versions'
    assert versions[0]['runtime_sha256'] != versions[1]['runtime_sha256'], 'Runtime builds must differ'
    report = {'versions': versions, 'os': platform.platform(), 'phases': [], 'gui_tested': False}
    with tempfile.TemporaryDirectory(prefix='asr-upgrade-', dir='/private/tmp') as temporary:
        root = Path(temporary)
        app = root / 'ASR Desktop.app'
        data = root / 'data'
        data.mkdir(mode=0o700)
        clone(args.models.resolve(), data / 'models')
        # Hash only installed assets; definitions may legitimately grow with a new catalog.
        snapshots = data / 'models/snapshots'
        assets = {str(p.relative_to(snapshots)): digest(p) for p in snapshots.rglob('*') if p.is_file()}
        assert assets, 'At least one prepared snapshot is required'
        environment = {**os.environ, 'PATH': '/usr/bin:/bin',
                       'ASR_DESKTOP_RUN_DIR': str(root / 'run'), 'ASR_DESKTOP_DATA_DIR': str(data),
                       'PYTHONHOME': '/nonexistent-python', 'PYTHONPATH': '/nonexistent-python'}
        socket = root / 'run/control.sock'

        def command(*arguments, check=True):
            result = subprocess.run([str(app / 'Contents/MacOS/asr-desktop'), *arguments, '--json'],
                                    env=environment, capture_output=True, text=True, timeout=180)
            if not check:
                return result
            assert result.returncode == 0, (arguments, result.returncode, result.stderr, result.stdout)
            reply = json.loads(result.stdout)
            assert reply['success'], reply
            return reply['result']

        def stop():
            command('service', 'stop')
            for _ in range(200):
                if not socket.exists():
                    break
                time.sleep(.05)
            assert not socket.exists(), 'Service did not stop before App replacement'

        source = root / 'sample.wav'
        with wave.open(str(source), 'wb') as output:
            output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            output.writeframes(b'\0\0' * 16000)
        output_dir = root / 'output'
        output_dir.mkdir()
        baseline = None
        running = False
        try:
            for label, bundle in [('old', old), ('upgrade', new), ('rollback', old)]:
                if app.exists():
                    shutil.rmtree(app)
                clone(bundle, app)
                status = command('service', 'start')
                running = True
                assert status['execution_ready'] and status['state'] == 'running'
                assert command('service', 'start')['pid'] == status['pid']
                assert command('queue', 'status')['paused'] is True
                if baseline is None:
                    command('settings', 'set', 'device', 'cpu')
                    command('submit', str(source), '--output-dir', str(output_dir), '--model', 'fun-asr-nano')
                    baseline = {'jobs': command('jobs', 'list'), 'settings': command('settings', 'show')}
                    assert baseline['jobs']['total'] == 1
                else:
                    assert command('jobs', 'list') == baseline['jobs'], 'Job state changed across replacement'
                    assert command('settings', 'show') == baseline['settings'], 'Settings changed'
                models = command('models', 'list')
                assert next(m for m in models if m['id'] == 'fun-asr-nano')['ready']
                stop()
                running = False
                with sqlite3.connect(data / 'workspace.sqlite3') as db:
                    schema = db.execute('PRAGMA user_version').fetchone()[0]
                    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                assert all(digest(snapshots / name) == value for name, value in assets.items())
                report['phases'].append({'phase': label, 'pid': status['pid'], 'schema': schema,
                                         'jobs_preserved': True, 'settings_preserved': True,
                                         'model_files_preserved': len(assets), 'reconnect': True})
                if label == 'old':
                    clone(data, root / 'before-update')
            # A genuine old runtime must refuse a synthetic future schema without writing it.
            database = data / 'workspace.sqlite3'
            with sqlite3.connect(database) as db:
                db.execute('PRAGMA user_version=999')
            before = digest(database)
            refused = command('service', 'start', check=False)
            assert refused.returncode == 3 and not socket.exists()
            assert digest(database) == before
            assert 'Use the App version that created this database' in (root / 'run/development-helper.log').read_text()
            report['old_runtime_refuses_future_schema_without_write'] = True
            # Restore a stopped-service, full-directory backup, then reconnect the old App.
            shutil.move(str(data), str(root / 'future-schema-preserved'))
            clone(root / 'before-update', data)
            command('service', 'start')
            running = True
            assert command('jobs', 'list') == baseline['jobs']
            assert command('settings', 'show') == baseline['settings']
            assert all(digest(snapshots / name) == value for name, value in assets.items())
            stop()
            running = False
            report['backup_restore_and_reconnect'] = True
        finally:
            if running:
                stop()
        report['passed'] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(args.report)


if __name__ == '__main__':
    main()
