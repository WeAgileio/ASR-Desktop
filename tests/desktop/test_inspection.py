from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from asr_desktop.intake import inspect, probe
from asr_desktop.workspace import Workspace
from asr_desktop.database import StateError
from asr_desktop.exports import output_availability


class InspectionTests(unittest.TestCase):
    def test_discovery_and_individual_failures_without_hashing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'a.wav').write_bytes(b'a')
            (root / 'bad.wav').write_bytes(b'b')
            (root / 'link.wav').symlink_to(root / 'a.wav')
            (root / 'nested').mkdir(); (root / 'nested' / 'child.mp4').write_bytes(b'c')
            def media(path, executable):
                if path.name == 'bad.wav': raise subprocess.TimeoutExpired('probe', 30)
                return 1200
            with patch('asr_desktop.intake.probe', side_effect=media), patch('asr_desktop.intake.fingerprint', side_effect=AssertionError('no hashing')):
                page = inspect([str(root), str(root / 'a.wav')], 'probe')
                deep = inspect([str(root)], 'probe', True)
            self.assertEqual(sum(e['status'] == 'valid' for e in page['entries']), 1)
            self.assertEqual(sum(e['status'] == 'valid' for e in deep['entries']), 2)
            self.assertIn('duplicate', [e['status'] for e in page['entries']])
            self.assertIn('symlink_excluded', [e['status'] for e in page['entries']])
            self.assertIn('error', next(e for e in page['entries'] if e['status'] == 'invalid'))

    def test_probe_validation_and_background_controls(self):
        import json
        for value in ({'streams': []}, {'streams': [{'codec_type': 'audio'}], 'format': {'duration': 'nan'}},
                      {'streams': [{'codec_type': 'audio'}], 'format': {'duration': '-1'}}):
            with patch('asr_desktop.intake.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(value))):
                with self.assertRaises(StateError): probe(Path('file'), 'probe')
        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(Path(folder), 'probe')
            gate = threading.Event()
            def slow(*args): gate.wait(3); return {'entries': []}
            try:
                with patch('asr_desktop.inspection.inspect', side_effect=slow):
                    start = time.monotonic()
                    first = workspace.dispatch({'operation': 'intake.inspect', 'arguments': {'paths': ['/a.wav']}})
                    workspace.dispatch({'operation': 'intake.inspect', 'arguments': {'paths': ['/b.wav']}})
                    with self.assertRaises(StateError):
                        workspace.dispatch({'operation': 'intake.inspect', 'arguments': {'paths': ['/c.wav']}})
                    result = workspace.dispatch({'operation': 'queue.pause', 'id': 'pause'})
                    self.assertTrue(result['paused'])
                    self.assertLess(time.monotonic() - start, 1)
                    self.assertEqual(workspace.database.batches()['total'], 0)
                    gate.set()
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        page = workspace.dispatch({'operation': 'intake.inspect', 'arguments': {'id': first['id']}})
                        if page['state'] == 'complete': break
                        time.sleep(.01)
                    self.assertEqual(page['state'], 'complete')
            finally:
                gate.set(); workspace.inspections.close(); workspace.database.close()

    def test_real_audio_and_video(self):
        ffmpeg = Path('/opt/homebrew/bin/ffmpeg')
        if not ffmpeg.is_file(): self.skipTest('Fixture generation requires development FFmpeg')
        ffprobe = Path('build/desktop/media/ffprobe').resolve()
        self.assertTrue(ffmpeg.is_file())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            import wave
            with wave.open(str(root / 'audio.wav'), 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                stream.writeframes(b'\0\0' * 20000)
            subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'color=s=32x32:r=10', '-i', str(root / 'audio.wav'), '-t', '1.25', '-c:v', 'mpeg4', '-c:a', 'aac', str(root / 'video.mp4')], check=True)
            entries = inspect([str(root)], ffprobe)['entries']
            self.assertEqual(len(entries), 2)
            self.assertTrue(all(e['status'] == 'valid' and 1000 <= e['duration_ms'] <= 1500 for e in entries))


class OutputSummaryTests(unittest.TestCase):
    def test_committed_partial_missing_and_legacy(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'jobs' / 'job').mkdir(parents=True)
            outputs = {fmt: str(root / ('file.' + fmt)) for fmt in ('txt', 'srt', 'json')}
            Path(outputs['txt']).write_text('成果')
            Path(outputs['json']).write_text('{}')
            job = {'id': 'job', 'state': 'failed', 'outputs': outputs}
            ledger = root / 'jobs' / 'job' / 'outputs.json'
            ledger.write_text(json.dumps({'job_id': 'job', 'files': {'txt': {'path': outputs['txt'], 'state': 'committed'}, 'srt': {'path': outputs['srt'], 'state': 'committed'}, 'json': {'path': outputs['json'], 'state': 'prepared'}}}))
            result = output_availability(job, root)
            self.assertEqual(result['delivered_outputs'], {'txt': outputs['txt']})
            self.assertEqual(result['missing_outputs'], ['srt'])
            self.assertEqual(result['undelivered_outputs'], ['json'])
            ledger.unlink()
            self.assertFalse(output_availability(job, root)['delivered_outputs'])
            job['state'] = 'completed'
            self.assertEqual(set(output_availability(job, root)['delivered_outputs']), {'txt', 'json'})
            ledger.write_text('broken')
            self.assertFalse(output_availability(job, root)['delivered_outputs'])

    def test_list_does_not_load_delivery_ledger(self):
        from asr_desktop.database import encode
        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(Path(folder), 'probe')
            try:
                db = workspace.database
                db.connection.execute("INSERT INTO batches VALUES('b',1,'{}')")
                db.connection.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', ('j', 'b', 1, 'completed', 's', None, encode({'source': '/source.wav'})))
                with patch('asr_desktop.exports.output_availability', side_effect=AssertionError('list must not scan ledger')):
                    self.assertEqual(workspace.dispatch({'operation': 'jobs.list', 'arguments': {'query': 'source'}})['total'], 1)
            finally:
                workspace.database.close()
