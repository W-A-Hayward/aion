"""Read-only stand-ins for the S3 client that compute.stats.load_raw expects.

load_raw only calls get_paginator("list_objects_v2").paginate(...) and get_object(...). Both stores
expose exactly those two reads, record the SHA-256 of every object read, and refuse everything else,
so a reproduction run cannot write, delete or publish anything.
"""
import hashlib
import io
from pathlib import Path

REQUIRED_KEYS = (
    "raw/starter/prices_daily.csv",
    "raw/starter/fx_usdcad_daily.csv",
    "raw/starter/macro_rates.csv",
    "raw/prices/snapshot=YYYY-MM-DD/prices_daily_extra.csv",
    "raw/fred/snapshot=YYYY-MM-DD/DCOILBRENTEU.csv",
    "raw/fred/snapshot=YYYY-MM-DD/T10YIE.csv",
)


class ReadOnlyViolation(PermissionError):
    pass


class _ReadOnly:
    _allowed = ("get_paginator", "get_object")

    def __init__(self):
        self.reads = {}  # key -> {"sha256", "bytes"}

    def _record(self, key, body):
        self.reads[key] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}

    def __getattr__(self, name):
        raise ReadOnlyViolation(f"{name} is not allowed: this store is read-only")


class LocalRawStore(_ReadOnly):
    """A local folder laid out like the bucket: <root>/raw/starter/..., <root>/raw/fred/snapshot=.../..."""

    def __init__(self, root):
        super().__init__()
        self.root = Path(root).resolve()
        if not (self.root / "raw").is_dir():
            raise FileNotFoundError(
                f"{self.root}/raw does not exist. Expected a local mirror of s3://<bucket>/raw/ containing:\n  "
                + "\n  ".join(REQUIRED_KEYS))

    def get_object(self, Bucket, Key):
        path = (self.root / Key).resolve()
        if not path.is_relative_to(self.root):
            raise ReadOnlyViolation("key escapes the local root")
        if not path.is_file():
            raise FileNotFoundError(f"Missing input file: {path} (s3 key {Key})")
        body = path.read_bytes()
        self._record(Key, body)
        return {"Body": io.BytesIO(body)}

    def get_paginator(self, name):
        if name != "list_objects_v2":
            raise ReadOnlyViolation(name)
        root = self.root

        class Paginator:
            def paginate(self, Bucket, Prefix, Delimiter="/"):
                folder = root / Prefix
                prefixes = sorted(p.name + "/" for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []
                yield {"CommonPrefixes": [{"Prefix": Prefix + p} for p in prefixes]}

        return Paginator()


class ReadOnlyS3(_ReadOnly):
    """Wraps a real boto3 S3 client (for SageMaker) and only forwards the two reads load_raw needs."""

    def __init__(self, client):
        super().__init__()
        object.__setattr__(self, "_client", client)

    def get_object(self, Bucket, Key):
        body = self._client.get_object(Bucket=Bucket, Key=Key)["Body"].read()
        self._record(Key, body)
        return {"Body": io.BytesIO(body)}

    def get_paginator(self, name):
        if name != "list_objects_v2":
            raise ReadOnlyViolation(name)
        return self._client.get_paginator(name)
