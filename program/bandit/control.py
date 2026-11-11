"""Cooperative stopping: finish the current durable operation on the first signal."""

import signal
import threading


class StopRequested(Exception):
    pass


class StopController:
    def __init__(self, event=None, install_signals=True):
        self.event = event if event is not None else threading.Event()
        self.install_signals = install_signals
        self.handlers = {}

    def is_set(self):
        return self.event.is_set()

    def wait(self, seconds):
        return self.event.wait(seconds)

    def check(self):
        if self.is_set():
            raise StopRequested()

    def _signal(self, signum, frame):
        if self.is_set():
            raise KeyboardInterrupt()
        self.event.set()

    def __enter__(self):
        if self.install_signals and threading.current_thread() is threading.main_thread():
            for name in ('SIGINT', 'SIGTERM'):
                sig = getattr(signal, name, None)
                if sig is not None:
                    self.handlers[sig] = signal.getsignal(sig)
                    signal.signal(sig, self._signal)
        return self

    def __exit__(self, *args):
        for sig, handler in self.handlers.items():
            signal.signal(sig, handler)
