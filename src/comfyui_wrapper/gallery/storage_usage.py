"""Read-only file-size accounting, separate from gallery image loading."""
import copy
import os
import re
import shutil
import stat
import threading
import time
from datetime import datetime, timezone


class StorageUsage:
    def __init__(self, root, history, ttl=60):
        self.root, self.history, self.ttl = root, history, ttl
        self._scan_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._cache = None
        self._version = 0

    def invalidate(self):
        with self._state_lock:
            self._version += 1
            self._cache = None

    def get(self, force=False):
        requested = time.monotonic()
        with self._state_lock:
            observed = self._cache
        with self._scan_lock:
            with self._state_lock:
                cached = self._cache
                if cached and ((not force and requested-cached[0] < self.ttl) or (force and cached is not observed)):
                    return copy.deepcopy(cached[1])
                version = self._version
            result = self.scan()
            with self._state_lock:
                if version == self._version:
                    self._cache = (time.monotonic(), result)
            return copy.deepcopy(result)

    def scan(self):
        # Avoid reading full prompts/settings for every execution.
        with self.history.connect() as db:
            records = {row[0]: 'temporary' if row[1] else 'protected' if row[2] else 'normal'
                for row in db.execute(
                    "SELECT id,COALESCE(json_extract(record,'$.temporary'),0),"
                    "EXISTS(SELECT 1 FROM image_favorites WHERE job_id=executions.id) FROM executions")}
        categories = {key: dict(bytes=0, files=0, executions=0)
                      for key in ('normal', 'temporary', 'protected', 'other')}
        skipped_links = errors = 0
        stack = [(self.root, 'other', True)]
        while stack:
            directory, category, top = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                                # Includes Windows junctions; never follow links outside the output folder.
                                skipped_links += 1
                                continue
                            group = records.get(entry.name, 'other') if top else category
                            if stat.S_ISDIR(info.st_mode):
                                if top and group != 'other' and re.fullmatch('[0-9a-f]{32}', entry.name):
                                    categories[group]['executions'] += 1
                                elif top:
                                    group = 'other'
                                stack.append((entry.path, group, False))
                            elif stat.S_ISREG(info.st_mode):
                                # Root-level database files and all ancillary folders are "other".
                                group = 'other' if top else category
                                categories[group]['bytes'] += info.st_size
                                categories[group]['files'] += 1
                        except OSError:
                            errors += 1
            except OSError:
                errors += 1
        disk = None
        try:
            usage = shutil.disk_usage(self.root)
            disk = dict(total=usage.total, used=usage.used, free=usage.free,
                        used_percent=round(usage.used/usage.total*100, 1) if usage.total else 0)
        except OSError:
            errors += 1
        return dict(categories=categories,
                    total=dict(bytes=sum(row['bytes'] for row in categories.values()),
                               files=sum(row['files'] for row in categories.values())),
                    disk=disk, output_directory=str(self.root),
                    scanned_at=datetime.now(timezone.utc).isoformat(),
                    partial=bool(errors), unreadable_entries=errors, skipped_links=skipped_links,
                    refresh_after_seconds=self.ttl)
