import json
from pathlib import Path
import tempfile
import unittest

from asr_desktop.database import Database, StateError, encode


class BatchDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'workspace.sqlite3'
        self.db = Database(self.path)
        for index, name in enumerate((None, '同名', '同名')):
            details = {'entries': [{'source': '/中文/source.wav', 'status': 'valid'}]}
            if name:
                details['name'] = name
            self.db.connection.execute('INSERT INTO batches VALUES(?,?,?)', (f'batch-{index}', index, encode(details)))
        for index, state in enumerate(('failed', 'completed', 'queued')):
            self.db.connection.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',
                                       (f'job-{index}', 'batch-0', index, state, 'snapshot', None, '{}'))

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_old_schema_names_pagination_and_counts(self):
        original = [tuple(r) for r in self.db.connection.execute('SELECT * FROM jobs')]
        self.db.close()
        self.db = Database(self.path)
        self.assertIsNone(self.db.upgrade_backup)
        page = self.db.batches(limit=2)
        self.assertEqual(page['total'], 3)
        self.assertEqual([b['id'] for b in page['batches']], ['batch-2', 'batch-1'])
        self.assertEqual([b['name'] for b in page['batches']], ['同名', '同名'])
        old = self.db.batches(offset=2)['batches'][0]
        self.assertIn('source.wav', old['name'])
        self.assertEqual(old['counts'], {'failed': 1, 'completed': 1, 'queued': 1})
        self.assertEqual(old['total'], 3)
        self.assertEqual(original, [tuple(r) for r in self.db.connection.execute('SELECT * FROM jobs')])
        for args in ({'limit': 0}, {'offset': -1}, {'limit': True}):
            with self.assertRaises(StateError):
                self.db.batches(**args)


class BatchProtocolTests(unittest.TestCase):
    def test_rename_replay_validation_and_persistence(self):
        from asr_desktop.workspace import Workspace, OPERATIONS
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory), 'ffprobe')
            db = workspace.database
            plan = {'entries': [{'source': '/中文/a.wav', 'status': 'valid'}], 'outputs': {'txt': '/out/a.txt'}}
            db.connection.execute('INSERT INTO batches VALUES(?,?,?)', ('batch-old', 1, encode(plan)))
            def call(name, request_id='rename', identifier='batch-old'):
                return workspace.dispatch({'operation': 'batches.rename', 'id': request_id,
                                           'arguments': {'id': identifier, 'name': name}})
            result = call('  十月訪談  ')
            self.assertEqual(result, {'id': 'batch-old', 'name': '十月訪談'})
            self.assertEqual(call('  十月訪談  '), result)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM events WHERE kind='batch.renamed'").fetchone()[0], 1)
            with self.assertRaises(StateError) as caught:
                call('不同內容')
            self.assertEqual(caught.exception.code, 'request_id_conflict')
            for index, name in enumerate(('', '  ', '中' * 101, None, 123, 'e\u0301' * 51)):
                with self.assertRaises(StateError):
                    call(name, f'invalid-{index}')
            call('e\u0301' * 50, 'unicode')
            with self.assertRaises(StateError) as caught:
                call('名稱', 'missing', 'batch-missing')
            self.assertEqual(caught.exception.code, 'not_found')
            saved = json.loads(db.connection.execute('SELECT details FROM batches').fetchone()[0])
            self.assertEqual({k: v for k, v in saved.items() if k != 'name'}, plan)
            db.close()
            workspace = Workspace(Path(directory), 'ffprobe')
            try:
                page = workspace.dispatch({'operation': 'batches.list'})
                self.assertEqual(page['batches'][0]['name'], 'e\u0301' * 50)
                self.assertEqual(set(page['batches'][0]), {'id', 'name', 'created', 'total', 'counts'})
                self.assertIn('batches.list', OPERATIONS)
                self.assertIn('batches.rename', OPERATIONS)
            finally:
                workspace.database.close()


if __name__ == '__main__':
    unittest.main()

class QueryTests(unittest.TestCase):
    def setUp(self):
        from asr_desktop.workspace import Workspace
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Workspace(Path(self.temp.name), 'ffprobe')
        self.db = self.workspace.database
        for batch in ('a', 'b'):
            self.db.connection.execute('INSERT INTO batches VALUES(?,?,?)', (batch, 1, encode({'name': '十月訪談' if batch == 'a' else 'Other'})))
        for index in range(240):
            self.db.connection.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',
                (f'job-{index:03}', 'a' if index < 120 else 'b', index, 'failed' if index % 2 else 'completed', 's', None,
                 encode({'source': f'/unreadable/Record 中文_%\' {index}.wav'})))

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_full_range_literal_search_and_counts(self):
        from unittest.mock import patch
        with patch('asr_desktop.intake.source_matches', side_effect=AssertionError('metadata only')):
            result = self.workspace.dispatch({'operation': 'jobs.list', 'arguments': {'batch_id': 'a', 'query': ' RECORD ', 'states': ['failed']}})
        self.assertEqual(result['total'], 60)
        self.assertEqual(result['counts'], {'completed': 60, 'failed': 60})
        self.assertEqual(result['scope_counts'], result['counts'])
        self.assertEqual(result['matched_counts'], {'failed': 60})
        self.assertEqual(self.db.jobs(query='119')[0]['id'], 'job-119')
        for query, count in (("_%'", 240), ('中文', 240), ('十月訪談', 120), ('%', 240), ('no match', 0), ('   ', 240)):
            self.assertEqual(sum(self.db.job_counts(query=query).values()), count)
        self.assertEqual(len(self.db.jobs(batch_id='a', states=['failed', 'completed'], offset=100)), 20)
        self.assertEqual(self.db.jobs(offset=100)[0]['id'], 'job-100')
        for args in ({'states': ['bad']}, {'states': 'failed'}, {'states': [1]}, {'query': None}, {'batch_id': 2}):
            with self.assertRaises(StateError):
                self.db.jobs(**args)

    def test_selection_is_read_only_and_tokens_track_membership_and_state(self):
        before = self.db.connection.total_changes
        selected, rows = self.db.selection({'batch_id': 'a'})
        self.assertEqual(selected['total'], 120)
        self.assertEqual(len(rows), 120)
        self.assertEqual(selected['retryable_count'], 60)
        self.assertEqual(self.db.connection.total_changes, before)
        token = selected['target_token']
        self.db.update_job('job-119', 'cancelled')
        with self.assertRaises(StateError) as caught:
            self.db.selection({'batch_id': 'a'}, token)
        self.assertEqual(caught.exception.code, 'selection_changed')
        token = self.db.selection({'batch_id': 'a'})[0]['target_token']
        self.db.connection.execute("DELETE FROM jobs WHERE id='job-119'")
        self.assertNotEqual(self.db.selection({'batch_id': 'a'})[0]['target_token'], token)
        token = self.db.selection({'batch_id': 'a'})[0]['target_token']
        self.db.connection.execute("INSERT INTO jobs VALUES('new','a',300,'failed','s',NULL,'{}')")
        self.assertNotEqual(self.db.selection({'batch_id': 'a'})[0]['target_token'], token)
        self.assertEqual(self.db.selection({'query': 'absent'})[0]['total'], 0)
        self.assertEqual(self.db.selection({'ids': []})[0]['total'], 0)
        for selector in ({'ids': ['job-000'], 'query': ''}, {'ids': ['missing']}, {'ids': 'job-000'}, {'extra': 1}, {'batch_id': 'missing'}):
            with self.assertRaises(StateError):
                self.db.selection(selector)
        self.assertEqual(self.db.selection({'ids': ['job-000', 'job-000']})[0]['total'], 1)

    def test_documented_selection_matches_list(self):
        import re
        documentation = Path(__file__).resolve().parents[2] / 'desktop/PROTOCOL.md'
        examples = re.findall(r"```json\n(.*?)\n```", documentation.read_text(), re.S)
        for example in examples:
            request = json.loads(example)
            if request.get('operation') == 'jobs.selection.preview':
                preview = self.workspace.dispatch(request)
                listing = self.workspace.dispatch({'operation': 'jobs.list', 'arguments': request['arguments']['selector']})
                self.assertEqual(preview['total'], listing['total'])
                self.assertEqual(preview['counts'], listing['matched_counts'])

class MutationTests(QueryTests):
    def call(self, operation, arguments, identifier='mutation'):
        return self.workspace.dispatch({'operation': operation, 'arguments': arguments, 'id': identifier})

    def test_retry_scope_atomicity_and_replay(self):
        from unittest.mock import patch
        # Real persisted metadata, with source validation isolated to test transaction boundaries.
        for row in self.db.connection.execute('SELECT id,details FROM jobs').fetchall():
            details = json.loads(row['details']); details['fingerprint'] = {'size': 1, 'sha256': 'original'}
            self.db.connection.execute('UPDATE jobs SET details=? WHERE id=?', (encode(details), row['id']))
        self.db.update_job('job-001', 'cancelled')
        self.db.update_job('job-003', 'interrupted')
        self.db.connection.execute('UPDATE jobs SET snapshot=?', (self.workspace.models.definition('fun-asr-nano')['snapshot_id'],))
        args = {'selector': {'batch_id': 'a'}, 'failed_only': True}
        with patch('asr_desktop.workspace.source_matches', return_value=True):
            result = self.call('jobs.retry', args)
            self.assertEqual(result['retried_count'], 58)
            self.assertEqual(result['skipped_count'], 62)
            self.assertEqual(self.call('jobs.retry', args), result)
        self.assertEqual(self.db.job('job-001')['state'], 'cancelled')
        self.assertEqual(self.db.job('job-003')['state'], 'interrupted')
        original = self.db.job('job-001')
        with patch('asr_desktop.workspace.source_matches', side_effect=[True, False]):
            with self.assertRaises(StateError) as caught:
                self.call('jobs.retry', {'selector': {'ids': ['job-001', 'job-003']}}, 'rollback')
        self.assertEqual(caught.exception.details['job_id'], 'job-003')
        self.assertEqual(self.db.job('job-001'), original)
        with patch('asr_desktop.workspace.source_matches', side_effect=FileNotFoundError('missing')):
            with self.assertRaises(StateError) as caught:
                self.call('jobs.retry', {'selector': {'ids': ['job-001']}}, 'missing')
        self.assertEqual(caught.exception.code, 'source_unavailable')
        token = self.db.selection({'states': ['failed']})[0]['target_token']
        with patch('asr_desktop.workspace.source_matches', return_value=True):
            result = self.call('jobs.retry', {'selector': {'states': ['failed']}, 'target_token': token}, 'all')
        self.assertEqual(result['retried_count'], 60)
        with self.assertRaises(StateError):
            self.call('jobs.retry', {'selector': {}, 'id': 'a'}, 'mixed')

    def test_remove_atomic_replay_and_files_preserved(self):
        source = Path(self.temp.name) / 'source.wav'; source.write_bytes(b'audio')
        output = Path(self.temp.name) / 'result.txt'; output.write_text('成果')
        cache = Path(self.temp.name) / 'cache'; cache.mkdir()
        (cache / 'outputs.json').write_text('{"committed":true}')
        before = {p: p.read_bytes() for p in (source, output, cache / 'outputs.json')}
        self.db.connection.execute("INSERT INTO attempts VALUES('attempt','job-001',1,'running','{}')")
        selector = {'ids': ['job-000', 'job-001']}
        token = self.db.selection(selector)[0]['target_token']
        with self.assertRaises(StateError) as caught:
            self.call('jobs.remove', {'selector': selector, 'target_token': token})
        self.assertEqual(caught.exception.code, 'worker_not_reaped')
        self.assertEqual(len(self.db.selection(selector)[1]), 2)
        self.db.connection.execute("UPDATE attempts SET state='failed'")
        token = self.db.selection(selector)[0]['target_token']
        args = {'selector': selector, 'target_token': token}
        result = self.call('jobs.remove', args)
        self.assertEqual(result['removed_count'], 2)
        self.assertEqual(self.call('jobs.remove', args), result)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with self.assertRaises(StateError): self.db.job('job-000')
        self.assertNotIn('job-000', [j['id'] for j in self.db.snapshot()['jobs']])
        self.assertEqual(self.db.batches()['batches'][0]['name'], '十月訪談')
        summary = self.db.selection({'batch_id': 'a'})[0]
        self.call('jobs.remove', {'selector': {'batch_id': 'a'}, 'target_token': summary['target_token']}, 'rest')
        self.assertEqual([b['id'] for b in self.db.batches()['batches']], ['b'])
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM events WHERE kind='job.removed'").fetchone()[0], 120)
