"""Extract one small series for the fuel card from the local research library (no network).

Source: library source SRC-037, Statistics Canada table 18-10-0001-01 (monthly average retail prices),
artifact 98676b20…3108 (zip_csv). Series: GEO "Canada", "Regular unleaded gasoline at self service filling
stations", cents per litre. Rows with a STATUS flag or an empty VALUE are dropped and counted, never filled.

Usage: python3 frontend/build-fuel-series.py   (writes frontend/fuel-series.json)
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACT = "98676b20b35b960d0c75bac41a5b7dfd4e66a7cf4bf0a4c78b436a3003893108"
GEO = "Canada"
FUEL = "Regular unleaded gasoline at self service filling stations"


def main():
    catalog = json.loads((HERE / "library-catalog.json").read_text())
    art = next(a for a in catalog["artifacts"] if (a.get("sha256") or a.get("id")) == ARTIFACT) \
        if isinstance(catalog["artifacts"], list) else catalog["artifacts"][ARTIFACT]
    path = HERE / art["payload"]["path"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != art["payload"]["sha256"]:
        raise SystemExit(f"{path} does not match the catalog hash; refusing to extract.")
    table = json.loads(raw)["data"]["members"][0]["data"]
    rows, dropped = [], 0
    for r in table["records"]:
        if r["GEO"] != GEO or r["Type of fuel"] != FUEL:
            continue
        if r["STATUS"] or not r["VALUE"]:
            dropped += 1
            continue
        rows.append((r["REF_DATE"], float(r["VALUE"])))
    rows.sort()
    vectors = {r["VECTOR"] for r in table["records"] if r["GEO"] == GEO and r["Type of fuel"] == FUEL}
    out = {
        "source": {"library_id": "SRC-037", "table": "Statistics Canada 18-10-0001-01", "artifact_sha256": ARTIFACT,
                   "payload_sha256": art["payload"]["sha256"], "vector": sorted(vectors), "geo": GEO, "fuel": FUEL,
                   "unit": "cents per litre", "dropped_flagged_or_empty": dropped},
        "months": [m for m, _ in rows],
        "values": [v for _, v in rows],
    }
    (HERE / "fuel-series.json").write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"{len(rows)} months {rows[0][0]}..{rows[-1][0]}, dropped {dropped}")


if __name__ == "__main__":
    main()
