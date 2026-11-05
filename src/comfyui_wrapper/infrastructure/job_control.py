"""Per-worker cooperative cancellation, never shared across jobs."""
import threading


class JobCancelled(Exception):
    pass


class JobControl:
    def __init__(self):
        self.event = threading.Event()

    def check(self):
        if self.event.is_set():
            raise JobCancelled('ユーザーの操作で停止しました。')


local = threading.local()


def current():
    return getattr(local, 'control', None)


def check():
    control = current()
    if control is not None:
        control.check()
