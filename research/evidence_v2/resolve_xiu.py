"""Local XIU demonstration. Read existing inputs; optionally create a NEW research JSON."""
import argparse
import json
from pathlib import Path

from constituent_resolver import resolve_constituent_evidence
from research_register import read_register_rows, build_register_catalog
from schema import ValidationError, digest, require
from xiu_holdings import read_holdings

ROOT = Path(__file__).resolve().parent
ACQUISITIONS = ROOT.parent / "source_documents"
DEFAULT_MANIFEST = ACQUISITIONS / "runs/20261115T131702Z_d4fbb4fa/manifest.json"


def resolve_local_inputs(holdings, register, manifest=DEFAULT_MANIFEST):
    snapshot = read_holdings(holdings)
    rows, register_hash = read_register_rows(register)
    raw = Path(manifest).read_bytes()
    catalog, paths, observations = build_register_catalog(
        rows, register_hash, json.loads(raw), digest(raw), ACQUISITIONS)
    require(len(catalog.passages) == 12, "Expected the reviewed twelve-candidate register")
    result = resolve_constituent_evidence(snapshot, catalog, paths, acquisition=observations)
    result["inputs"] = {"holdings_file": str(Path(holdings).resolve()),
                        "register_file": str(Path(register).resolve()), "register_sha256": register_hash,
                        "acquisition_manifest_sha256": digest(raw)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", type=Path, default=Path.home() / "Downloads/xiu_holdings.csv")
    parser.add_argument("--register", type=Path,
                        default=Path.home() / "Downloads/RIPPLE_Official_Research_Register_2026-11-15.xlsx")
    parser.add_argument("--output", type=Path, help="New JSON file within research/evidence_v2; never overwrite")
    args = parser.parse_args()
    try:
        result = resolve_local_inputs(args.holdings, args.register)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            target = args.output.resolve()
            require(target.is_relative_to(ROOT), "Output must remain inside research/evidence_v2")
            # Parent must exist. Exclusive creation prevents overwriting teammate/results files.
            with target.open("x", encoding="utf-8") as out:
                out.write(text)
            print(json.dumps({"output": str(target), **result["scope"]}, ensure_ascii=False, indent=2))
        else:
            print(text, end="")
    except (ValidationError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Local resolution stopped: {exc}\n")


if __name__ == "__main__":
    main()
