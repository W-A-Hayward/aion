"""Portable, explicit inputs for the XIU resolvers. Standard library only.

Inputs are named in a JSON config instead of being assumed in ~/Downloads. Lookup order:
  1. an explicit path (--inputs on the command line, or load_inputs(path));
  2. the CASCADE_RESEARCH_INPUTS environment variable;
  3. research/evidence_v2/local_inputs.json (git-ignored; copy local_inputs.example.json).
Every file is checked against its expected SHA-256. A missing config or file raises MissingInput with the
exact key, path and expected hash. The holdings date is checked when the snapshot is parsed.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path

from schema import ValidationError, digest

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "local_inputs.json"
EXAMPLE_CONFIG = ROOT / "local_inputs.example.json"
ENV = "CASCADE_RESEARCH_INPUTS"
REQUIRED = {
    "xiu_holdings": ("path", "sha256", "as_of", "source"),
    "research_register": ("path", "sha256"),
}


class MissingInput(ValidationError):
    pass


@dataclass(frozen=True)
class InputFile:
    key: str
    path: Path
    sha256: str
    meta: dict


@dataclass(frozen=True)
class ResearchInputs:
    config_path: Path
    holdings: InputFile
    register: InputFile


def _resolve(raw, base):
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    return path if path.is_absolute() else (base / path).resolve()


def load_inputs(config=None, verify=True):
    """Read the config, resolve paths relative to it, and verify each file's SHA-256."""
    chosen = Path(config) if config else Path(os.environ[ENV]) if os.environ.get(ENV) else DEFAULT_CONFIG
    if not chosen.is_file():
        raise MissingInput(
            f"Research input config not found: {chosen}. Copy {EXAMPLE_CONFIG.name} to {DEFAULT_CONFIG.name} "
            f"(git-ignored), or set {ENV}, and fill in the local paths of the XIU holdings snapshot and the "
            f"research register.")
    try:
        data = json.loads(chosen.read_text())
    except ValueError as exc:
        raise ValidationError(f"{chosen} is not valid JSON") from exc
    files = {}
    for key, fields in REQUIRED.items():
        entry = data.get(key)
        if not isinstance(entry, dict) or any(not entry.get(f) for f in fields):
            raise ValidationError(f"{chosen}: '{key}' needs the fields {', '.join(fields)}")
        path = _resolve(entry["path"], chosen.parent)
        if verify:
            if not path.is_file():
                raise MissingInput(f"Missing input '{key}': {path} (expected SHA-256 {entry['sha256']}). "
                                   f"Set its path in {chosen}.")
            actual = digest(path.read_bytes())
            if actual != entry["sha256"]:
                raise ValidationError(f"Input '{key}' at {path} has SHA-256 {actual}, expected {entry['sha256']}. "
                                      f"Wrong file or a different version; refusing to continue.")
        files[key] = InputFile(key, path, entry["sha256"], {k: v for k, v in entry.items() if k not in ("path", "sha256")})
    return ResearchInputs(chosen.resolve(), files["xiu_holdings"], files["research_register"])
