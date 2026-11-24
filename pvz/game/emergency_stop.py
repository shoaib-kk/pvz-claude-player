"""Observe Ctrl+C globally without taking keyboard focus or swallowing the keys."""
import _thread
import threading


class StopHotkey:
    def __init__(self, cancel=None, key_state=None, interrupt=None):
        if key_state is None:
            from win32api import GetAsyncKeyState
            key_state = GetAsyncKeyState
        self.key_state = key_state
        self.cancel = cancel
        self.interrupt = interrupt or _thread.interrupt_main
        self.requested = threading.Event()
        self.closed = threading.Event()
        self.thread = None

    def poll(self):
        if self.requested.is_set():
            return
        if self.key_state(0x11) & 0x8000 and self.key_state(ord("C")) & 0x8000:
            self.requested.set()
            try:
                if self.cancel:
                    self.cancel()
            finally:
                self.interrupt()

    def check(self):
        if self.requested.is_set():
            raise KeyboardInterrupt

    def _watch(self):
        while not self.closed.wait(0.03) and not self.requested.is_set():
            self.poll()

    def start(self):
        self.thread = threading.Thread(target=self._watch, daemon=True, name="pvz-stop-hotkey")
        self.thread.start()

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=0.2)
