"""S3-shaped test double, entirely in memory. No bucket, credentials or network."""

from dataclasses import dataclass
from threading import RLock

from schema import digest


class MissingObject(RuntimeError):
    pass


class PreconditionFailed(RuntimeError):
    pass


class SimulatedStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    body: bytes
    etag: str


class MemoryS3:
    """Conditional writes are atomic within this fake only; ETag is a test token.

    There is deliberately no delete method, SDK client, endpoint or AWS adapter.
    fail_next_read / fail_put_key support deterministic failure-injection tests.
    """

    def __init__(self):
        self._objects = {}
        self._lock = RLock()
        self.events = []
        self.fail_next_read = False
        self.fail_put_key = None
        self._sequence = 0

    def get_object(self, *, Key):
        with self._lock:
            self.events.append(("get", Key))
            if self.fail_next_read:
                self.fail_next_read = False
                raise SimulatedStorageError("Injected read failure")
            if Key not in self._objects:
                raise MissingObject("Required catalog object is missing")
            return self._objects[Key]

    def put_object(self, *, Key, Body, if_none_match=False, if_match=None):
        with self._lock:
            if type(Body) is not bytes:
                raise TypeError("Fake object bodies must be bytes")
            if if_none_match == (if_match is not None):
                raise ValueError("Exactly one write precondition is required")
            if self.fail_put_key == Key:
                raise SimulatedStorageError("Injected write failure")
            current = self._objects.get(Key)
            if if_none_match and current is not None:
                raise PreconditionFailed("Object already exists")
            if if_match is not None and (current is None or current.etag != if_match):
                raise PreconditionFailed("Catalog changed; re-read and merge again")
            self._sequence += 1
            token = digest(Body) + ":" + str(self._sequence)
            self._objects[Key] = StoredObject(Body, token)
            self.events.append(("put", Key))
            return token

    def snapshot(self):
        with self._lock:
            return dict(self._objects)
