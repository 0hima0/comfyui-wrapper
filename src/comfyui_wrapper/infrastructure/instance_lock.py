"""OS-owned server lock, automatically released when the process exits."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, root):
        self.path = Path(root).resolve() / '.server.lock'
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if self.path.stat().st_size == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise RuntimeError('同じ保存先を使用するWebUIが起動済みです。既存サービスを停止してから起動してください。') from error
        self.file = stream
        return self

    def __exit__(self, *args):
        stream, self.file = self.file, None
        if stream is not None:
            try:
                if os.name == 'nt':
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()
        # Keep the inode: unlinking a lock file can permit two independent locks.
