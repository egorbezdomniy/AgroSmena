"""OS lock shared by ordinary CRM instances and the updater."""
import os
from pathlib import Path


class AppLock:
    def __init__(self, data_root):
        self.path = Path(data_root) / 'runtime.lock'
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        try:
            if os.fstat(self.stream.fileno()).st_size == 0:
                self.stream.write(b'0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            self.stream = None
            raise RuntimeError('CRM или updater уже запущен. Закройте другой экземпляр.')
        return self

    def __exit__(self, *args):
        if self.stream:
            self.stream.close()
            self.stream = None
