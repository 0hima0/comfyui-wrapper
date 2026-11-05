"""Update a Git clone with saved-data backup and startup verification."""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SERVICE = 'comfyui-wrapper.service'
sys.path.insert(0, str(ROOT/'src'))
from comfyui_wrapper.infrastructure.instance_lock import InstanceLock


class GitUpdate:
    """Update a clean, ordinary clone without discarding local files or commits."""

    def __init__(self, root):
        self.root = root.resolve()

    def git(self, *args, check=True):
        # Do not echo remote URLs, credentials, or Git's possibly sensitive stderr.
        result = subprocess.run(
            ['git', '-c', 'core.hooksPath=' + os.devnull, '-C', str(self.root), *args],
            capture_output=True, timeout=120,
            env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
        if check and result.returncode:
            raise RuntimeError('Git ' + args[0] + ' failed. Check repository access and branch state locally.')
        return result

    def value(self, *args):
        return self.git(*args).stdout.decode('utf-8').strip()

    def clean(self):
        if self.value('status', '--porcelain', '--untracked-files=no'):
            raise ValueError('Tracked files have local changes. Commit or move them before updating.')
        flags = self.value('ls-files', '-v').splitlines()
        if any(line and (line[0] == 'S' or line[0].islower()) for line in flags):
            raise ValueError('Sparse checkout and assume-unchanged files are not supported.')

    def tree(self, commit):
        files = set()
        for entry in self.git('ls-tree', '-r', '-z', commit).stdout.split(b'\0'):
            if not entry:
                continue
            meta, raw = entry.split(b'\t', 1)
            name = raw.decode('utf-8')
            path = PurePosixPath(name)
            parts = tuple(part.lower() for part in path.parts)
            if meta.split()[0] not in (b'100644', b'100755'):
                raise ValueError('Git updates do not support symlinks or submodules.')
            if (path.is_absolute() or '\\' in name or ':' in name or
                    any(part in ('..', '.', '.git', '.venv', 'local', 'internal-docs',
                                 'web-results', 'outputs', 'update-backups', '.update-lock') for part in parts) or
                    any(part == 'settings.conf' or part.startswith('config.json') or
                        part == '.env' or (part.startswith('.env.') and part != '.env.example')
                        for part in parts)):
                raise ValueError('Git tree contains a private or runtime path; update refused.')
            files.add(name)
        return files

    def prepare(self, config, output):
        if Path(self.value('rev-parse', '--show-toplevel')).resolve() != self.root:
            raise ValueError('Run the updater in the root of a Git clone.')
        self.branch = self.value('symbolic-ref', '--quiet', 'HEAD')
        upstream = self.value('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
        if not upstream.startswith('origin/'):
            raise ValueError('The current branch must track an origin branch.')
        self.clean()
        self.old = self.value('rev-parse', 'HEAD')
        self.git('fetch', '--no-tags', 'origin', 'refs/heads/' + upstream[len('origin/'):])
        self.target = self.value('rev-parse', 'FETCH_HEAD^{commit}')
        if self.git('merge-base', '--is-ancestor', self.old, self.target, check=False).returncode:
            raise ValueError('Local and upstream history diverged. Automatic update requires fast-forward.')
        self.previous = self.tree(self.old)
        self.files = self.tree(self.target)
        required = {'VERSION', 'requirements.txt', 'tools/user/webui.py',
                    'src/comfyui_wrapper/webui.py', 'scripts/user/start-webui.sh',
                    'scripts/user/update.sh', 'tools/internal/update_app.py'}
        if not required <= self.files:
            raise ValueError('Required application files are missing from the Git target.')
        for name in self.previous | self.files:
            dest = self.root / name
            if dest.is_symlink() or any(p.is_symlink() for p in dest.parents):
                raise ValueError('Git update target contains a symbolic link.')
            if (dest == config or dest in config.parents or dest == output or
                    output in dest.parents or dest in output.parents):
                raise ValueError('Git files overlap the configuration or saved data.')
            if name not in self.previous and dest.exists():
                raise ValueError('A new Git file would overwrite a local file or directory.')
        self.names = self.git('diff', '--name-only', '--no-renames', '-z', self.old, self.target).stdout.decode('utf-8').strip('\0').split('\0')
        self.names = [name for name in self.names if name]
        self.release = self.value('show', self.target + ':VERSION')

    def install(self):
        self.clean()
        if self.value('rev-parse', 'HEAD') != self.old or self.value('symbolic-ref', 'HEAD') != self.branch:
            raise RuntimeError('Git HEAD changed while preparing the update.')
        self.git('merge', '--ff-only', '--no-overwrite-ignore', self.target)

    def rollback(self):
        head = self.value('rev-parse', 'HEAD')
        if head == self.old:
            return
        if head != self.target or self.value('symbolic-ref', 'HEAD') != self.branch:
            raise RuntimeError('Git HEAD changed; automatic rollback stopped. Use the recorded backup.')
        # --keep refuses to discard edits made during the update. Never use --hard/clean.
        self.git('reset', '--keep', self.old)


def request_json(url):
    # Local control requests never use HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        return json.load(response)


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('--url must be a local HTTP address without credentials.')
    return value.rstrip('/')


def server_info(url):
    try:
        return request_json(url + '/api/version')
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            return None
        raise RuntimeError('Cannot confirm local server state; update aborted.') from error


def service_active():
    if os.name != 'nt' and shutil.which('systemctl'):
        active = [name for name in (SERVICE, 'llmpc-image-webui.service')
                  if subprocess.run(['systemctl', 'is-active', '--quiet', name]).returncode == 0]
        if len(active) > 1:
            raise RuntimeError('Both old and new services are running. Stop the duplicate service first.')
        return active[0] if active else None
    return None


def sudo_service(action, service=SERVICE):
    subprocess.run(['sudo', 'systemctl', action, service], check=True)


def migrate_service(service, config):
    if not service:
        return service
    import importlib.util
    spec = importlib.util.spec_from_file_location('service_renderer', ROOT/'tools/internal/render_service.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    user = subprocess.check_output(['systemctl', 'show', service, '-p', 'User', '--value'], text=True).strip() or 'root'
    template = (ROOT/'deploy/systemd/comfyui-wrapper.service').read_text(encoding='utf-8')
    # Preserve the selected configuration file, including non-default paths.
    value = json.dumps(str(config).replace('%', '%%').replace('$', '$$'), ensure_ascii=False)
    template = template.replace('@CONFIG@', value)
    unit = renderer.render(template, ROOT, user)
    with tempfile.TemporaryDirectory(prefix='wrapper-service-') as folder:
        path = Path(folder)/SERVICE
        path.write_text(unit, encoding='utf-8')
        subprocess.run(['systemd-analyze', 'verify', str(path)], check=True)
        subprocess.run(['sudo', 'install', '-m', '644', str(path), '/etc/systemd/system/'+SERVICE], check=True)
    if service != SERVICE:
        sudo_service('disable', service)
    subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True)
    sudo_service('enable')
    return SERVICE

def stop_server(url, info, service):
    if info:
        if Path(info['app_directory']).resolve() != ROOT:
            raise ValueError('The specified URL belongs to another installation.')
        state = request_json(url + '/api/generation-state')
        history = request_json(url + '/api/history')
        if state.get('active_batch') or any(row.get('state') == 'running' for row in history['items']):
            raise RuntimeError('Generation is running. Retry after it finishes.')
        if service:
            pid = subprocess.check_output(['systemctl', 'show', service, '-p', 'MainPID', '--value'], text=True).strip()
            if int(pid) != int(info['pid']):
                raise ValueError('Service PID does not match this server.')
    elif service:
        raise RuntimeError('Service is active but its API cannot be verified.')
    if service:
        sudo_service('stop', service)
    elif info:
        pid = int(info['pid'])
        if pid <= 1 or pid == os.getpid():
            raise ValueError('Invalid server PID.')
        os.kill(pid, signal.SIGTERM)
    for _ in range(60):
        if server_info(url) is None:
            return
        time.sleep(.5)
    raise RuntimeError('Server did not stop.')


def copy_tree(source, destination):
    # Never follow links out of backup roots.
    if source.is_symlink() or any(path.is_symlink() for path in source.rglob('*')):
        raise ValueError('Backup paths must not contain symbolic links: ' + str(source))
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.server.lock'))


def start_server(config, service, log):
    if service:
        sudo_service('start', service)
        return None
    options = dict(cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    return subprocess.Popen([sys.executable, str(ROOT/'tools/user/webui.py'),
                             '--config', str(config)], **options)


def wait_ready(url, release):
    for _ in range(60):
        try:
            info = server_info(url)
            if info and Path(info['app_directory']).resolve() == ROOT and info['release'] == release:
                return
        except (OSError, ValueError, RuntimeError):
            pass
        time.sleep(1)
    raise RuntimeError('Updated server failed its startup check.')


def perform_update(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'config.json')
    parser.add_argument('--url', default='http://127.0.0.1:7860')
    args = parser.parse_args(argv)
    if not (ROOT/'.git').is_dir():
        raise ValueError('Update requires a Git clone. See docs/MAINTENANCE.md#migration for ZIP installations.')
    url = local_url(args.url)
    config = args.config.resolve()
    # Read configuration only at user-invoked runtime; never print its contents.
    if not config.is_file():
        raise ValueError('Create the configuration file before updating.')
    settings = json.loads(config.read_text(encoding='utf-8-sig'))
    if (urlsplit(url).port or 80) != settings.get('port', 7860):
        raise ValueError('--url port must match the saved configuration.')
    output = Path(settings.get('output_dir', 'web-results')).expanduser()
    if not output.is_absolute():
        output = config.parent / output
    output = output.resolve()
    if (output == ROOT or output in ROOT.parents or output in (ROOT/'update-backups').parents
            or output == ROOT/'update-backups' or ROOT/'update-backups' in output.parents):
        raise ValueError('Unsafe output directory for automatic backup.')
    for directory in ('src', 'web', 'scripts', 'tools', 'docs', 'deploy', 'workflows', 'tests', 'docker', '.venv', '.git'):
        managed = ROOT/directory
        if output == managed or managed in output.parents or output in managed.parents:
            raise ValueError('Output directory overlaps program or environment files.')
    update = GitUpdate(ROOT)
    update.prepare(config, output)
    if update.old == update.target:
        print('Already up to date: ' + update.old)
        return 0

    backup_root = ROOT/'update-backups'
    if backup_root.is_symlink():
        raise ValueError('Backup directory must not be a symbolic link.')
    backup_root.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = Path(tempfile.mkdtemp(prefix=stamp+'-', dir=backup_root))
    info = server_info(url)
    service = service_active()
    stopped = False
    installed = False
    process = None
    existed = []
    log = None
    server_lock = None
    try:
        stop_server(url, info, service)
        stopped = True
        server_lock = InstanceLock(output)
        server_lock.__enter__()
        if output.exists():
            copy_tree(output, backup/'data')
        shutil.copy2(config, backup/'config.json')
        for name in update.names:
            source = ROOT/name
            if source.exists():
                if not source.is_file():
                    raise ValueError('Update target is not a file: ' + name)
                destination = backup/'program'/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                existed.append(name)
        (backup/'restore.json').write_text(json.dumps(dict(
            output=str(output), config=str(config), files=update.names, existed=existed,
            release=update.release, git_before=update.old, git_after=update.target),
            indent=2), encoding='utf-8')
        installed = True
        update.install()
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(ROOT/'requirements.txt')], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
        log = (backup/'startup.log').open('ab')
        server_lock.__exit__(None, None, None)
        server_lock = None
        service = migrate_service(service, config)
        process = start_server(config, service, log)
        wait_ready(url, update.release)
        print('Update complete: ' + update.target + '. Backup: ' + str(backup))
    except BaseException:
        if installed:
            if service:
                sudo_service('stop', service)
            elif process and process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
            update.rollback()
            if server_lock is not None:
                server_lock.__exit__(None, None, None)
                server_lock = None
            if (backup/'data').exists():
                if output.exists():
                    shutil.move(str(output), str(backup/'failed-data'))
                shutil.copytree(backup/'data', output)
            # Dependency rollback is best effort; keep the complete log and backup.
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(ROOT/'requirements.txt')])
        if server_lock is not None:
            server_lock.__exit__(None, None, None)
            server_lock = None
        if stopped and info:
            if log is None:
                log = (backup/'startup.log').open('ab')
            start_server(config, service, log)
        print('Update failed. Backup and logs: ' + str(backup), file=sys.stderr)
        raise
    finally:
        if server_lock is not None:
            server_lock.__exit__(None, None, None)
        if log:
            log.close()
    return 0


def main(argv=None):
    lock = ROOT/'.update-lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError('Another update is running or .update-lock remains after an interrupted update.')
    try:
        return perform_update(argv)
    finally:
        lock.rmdir()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print('Update error: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
