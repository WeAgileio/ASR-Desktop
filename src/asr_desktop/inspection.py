"""Bounded read-only media inspection, polled without holding the control loop."""
from concurrent.futures import ThreadPoolExecutor
from .database import StateError, new_id
from .intake import inspect


class Inspections:
    def __init__(self, ffprobe):
        self.ffprobe = ffprobe
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='media-inspect')
        self.jobs = {}

    def dispatch(self, arguments):
        if 'id' in arguments:
            if set(arguments) != {'id'} or not isinstance(arguments['id'], str):
                raise StateError('invalid_arguments', 'Poll inspection with id only')
            future = self.jobs.get(arguments['id'])
            if future is None:
                raise StateError('not_found', 'Inspection expired; inspect sources again')
            if not future.done():
                return {'id': arguments['id'], 'state': 'reading'}
            return {'id': arguments['id'], 'state': 'complete', **future.result()}
        paths, recursive = arguments.get('paths'), arguments.get('recursive', False)
        if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths) or type(recursive) is not bool:
            raise StateError('invalid_arguments', 'Provide source paths and a boolean recursive setting')
        # Bound running and queued operations; retain a small cache for lost poll responses.
        if sum(not future.done() for future in self.jobs.values()) >= 2:
            raise StateError('inspection_busy', 'Media inspection is busy; retry shortly')
        for identifier in list(self.jobs):
            if len(self.jobs) < 16:
                break
            if self.jobs[identifier].done():
                del self.jobs[identifier]
        identifier = new_id('inspect')
        self.jobs[identifier] = self.pool.submit(inspect, list(paths), self.ffprobe, recursive)
        return {'id': identifier, 'state': 'reading'}

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
