import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deployment'))
from mac_service import Manager, private_write
from mac_panel import Panel, make_handler, validate_settings


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = patch('pathlib.Path.home', return_value=self.root)
        self.home.start()
        self.addCleanup(self.home.stop)
        self.manager = Manager(self.root / 'config')
        self.manager.initialize()

    def test_initialize_preserves_credentials_and_private_permissions(self):
        path = self.manager.config / 'compose.env'
        previous = path.read_bytes()
        self.manager.initialize()
        self.assertEqual(previous, path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        settings = self.manager.settings()
        self.assertIn(Path(settings['ASR_WORKER_TOKEN_FILE']).read_text().strip(), path.read_text())

    def test_partial_initialization_refuses_rotation(self):
        self.manager.host.unlink()
        with self.assertRaises(ValueError):
            self.manager.initialize()

    def test_active_job_blocks_stop_after_pause(self):
        with self.manager.locks(('execution.lock',)):
            with patch.object(self.manager, 'pause') as pause, patch.object(self.manager, 'check_agents'), patch('mac_service.run') as run:
                with self.assertRaises(ValueError):
                    self.manager.stop()
                pause.assert_called_once_with(True)
                run.assert_not_called()

    def test_settings_reject_remote_credentials_endpoint(self):
        values = {k: v for k, v in self.manager.settings().items() if k in (
            'ASR_API_URL', 'ASR_REDIS_URL', 'ASR_RETENTION_DAYS', 'ASR_MIN_FREE_BYTES')}
        validate_settings(values)
        for url in ['http://evil.example:8090', 'http://user:pw@localhost:8090', 'http://127.0.0.1:8090/api']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_settings(dict(values, ASR_API_URL=url))

    def test_foreign_agent_is_not_overwritten(self):
        self.manager.agents.mkdir(parents=True)
        import plistlib
        with self.manager.plist('worker').open('wb') as stream:
            plistlib.dump({'Label': 'another'}, stream)
        with self.assertRaises(ValueError):
            self.manager.check_agents()

    def test_panel_requires_auth_and_csrf(self):
        panel = Panel(self.manager)
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(panel))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(panel.pool.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url)
        self.assertEqual(error.exception.code, 401)
        headers = {'Authorization': panel.authorization, 'Content-Type': 'application/json'}
        request = urllib.request.Request(url + '/action', data=b'{"command":"stop"}', headers=headers)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 403)
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as response:
            page = response.read().decode()
        self.assertIn(panel.csrf, page)
        self.assertNotIn('ASR_ADMIN_PASSWORD=', page)
        with patch.object(panel, 'submit') as submit:
            headers['X-CSRF-Token'] = panel.csrf
            with urllib.request.urlopen(urllib.request.Request(url + '/action', data=b'{"command":"pause"}', headers=headers)) as response:
                self.assertEqual(response.status, 202)
            submit.assert_called_once_with('pause', {})

    def test_settings_cannot_change_while_running(self):
        panel = Panel(self.manager)
        self.addCleanup(panel.pool.shutdown)
        before = self.manager.host.read_bytes()
        with patch.object(self.manager, 'loaded', return_value=True):
            panel.execute('settings', {})
        self.assertEqual(before, self.manager.host.read_bytes())
        self.assertIn('停止', panel.result)

    def test_settings_save_keeps_credentials_and_paths(self):
        panel = Panel(self.manager)
        self.addCleanup(panel.pool.shutdown)
        before = self.manager.settings()
        values = {key: before[key] for key in (
            'ASR_API_URL', 'ASR_REDIS_URL', 'ASR_RETENTION_DAYS', 'ASR_MIN_FREE_BYTES')}
        values['ASR_RETENTION_DAYS'] = '14'
        with patch.object(self.manager, 'loaded', return_value=False):
            panel.execute('settings', values)
        after = self.manager.settings()
        self.assertEqual(after['ASR_RETENTION_DAYS'], '14')
        self.assertEqual(after['ASR_WORKER_TOKEN_FILE'], before['ASR_WORKER_TOKEN_FILE'])
        self.assertEqual(after['ASR_WORKSPACE'], before['ASR_WORKSPACE'])
        self.assertEqual(self.manager.host.stat().st_mode & 0o777, 0o600)

    def test_start_preserves_paused_state_and_is_idempotent(self):
        self.manager.agents.mkdir(parents=True)
        for role in ('scanner', 'worker'):
            self.manager.plist(role).touch()
        Path(self.manager.settings()['ASR_GOOGLE_TOKEN_FILE']).touch()
        with patch.object(self.manager, 'check_agents'), patch.object(self.manager, 'api', return_value={'paused': True}) as api, patch.object(self.manager, 'loaded', return_value=True), patch('mac_service.run') as run:
            self.manager.start()
        run.assert_not_called()
        api.assert_called_once_with('/api/overview')

    def test_panel_serializes_operations(self):
        panel = Panel(self.manager)
        self.addCleanup(panel.pool.shutdown)
        panel.busy = True
        with patch.object(panel.pool, 'submit') as submit, self.assertRaises(ValueError):
            panel.submit('install', {})
        submit.assert_not_called()

    def test_existing_oauth_config_is_selected(self):
        target = self.manager.config / 'host.oauth.json'
        self.manager.host.rename(target)
        self.assertEqual(Manager(self.manager.config).host, target)


if __name__ == '__main__':
    unittest.main()
