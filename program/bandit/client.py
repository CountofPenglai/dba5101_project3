"""Pacing for every HTTP call made through the supplied cloud helper."""

import math
import threading
import time

import server_pull

from .common import server_address

_HELPER_LOCK = threading.Lock()


def validate_settings(interval, timeout):
    for value, name, minimum, maximum in ((interval, "interval", 0.25, None),
                                          (timeout, "timeout", 0, 60)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < minimum
                or (name == "timeout" and value == 0)
                or (maximum is not None and value > maximum)):
            raise ValueError("Invalid {}".format(name))


class PacedClient:
    def __init__(self, username, password, server_url, *, interval=0.25, timeout=10.0):
        validate_settings(interval, timeout)
        if not isinstance(username, str) or not username.strip():
            raise ValueError("A group username is required for online mode")
        if not isinstance(password, str) or not password:
            raise ValueError("A group password is required for online mode")
        self.username, self.password = username, password
        self.server_url = server_address(server_url)
        self.interval, self.timeout = interval, timeout
        # Also pace the first call after reopening a driver.
        self._not_before = time.monotonic() + interval

    def __enter__(self):
        if not _HELPER_LOCK.acquire(blocking=False):
            raise RuntimeError("Another online driver is already using the cloud helper")
        try:
            # Reconfiguration would discard state or reject a same-session pending request.
            if server_pull.BASE_URL != self.server_url:
                server_pull.configure(self.server_url)
        except BaseException:
            _HELPER_LOCK.release()
            raise
        return self

    def __exit__(self, *args):
        self.password = None
        _HELPER_LOCK.release()

    def _call(self, function, *args, before_send=None, **kwargs):
        delay = self._not_before - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        try:
            if before_send is not None:
                before_send()
            return function(self.username, self.password, *args, timeout=self.timeout, **kwargs)
        finally:
            self._not_before = time.monotonic() + self.interval

    def status(self):
        return self._call(server_pull.status)

    def pull(self, request, *, before_send=None):
        return self._call(server_pull.pull, request["arm"],
                          request_id=request["request_id"], expected_pull=request["expected_pull"],
                          before_send=before_send)

    def wait_before_retry(self):
        self._not_before = max(self._not_before, time.monotonic() + 1.0)
