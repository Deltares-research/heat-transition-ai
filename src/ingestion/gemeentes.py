from pathlib import Path
import json
from src.db.db_client import DBClient
import math


COLUMNS = {
    "name":               "naam",
    "code":               "code",
    "province":           "province",
    "population":         "inwoners",
    "households":         "huishoudens",
    "avg_household_size": "huishoudensgrootte",
    "dwellings":          "woningvoorraad",
    "owned_pct":          "koopwoningen_pct",
    "rented_pct":         "huurwoningen_pct",
    "social_pct":         "corporatiewoningen_pct",
    "multi_family_pct":   "meergezins_pct",
    "non_residential":    "niet_woningen",
    "woz_valuation":      "woz_waarde",
    "land_area":          "oppervlakte_land",
    "total_area":         "oppervlakte_totaal",
    "pop_density":        "bevolkingsdichtheid",
    "address_density":    "omgevingsadressen",
    "urbanity":           "stedelijkheid",
    "peiljaar":           "peiljaar",
}


INT_COLS = {
    "population", "households", "dwellings", "non_residential",
    "land_area", "total_area", "urbanity", "peiljaar",
}


def clean(v, col):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return int(round(float(v))) if col in INT_COLS else v


def ingest_gemeentes(
    client: DBClient,
    buurt_path: Path | str,
    gemeente_path: Path | str | None = None,
) -> None:

    if not isinstance(buurt_path, Path):
        buurt_path = Path(buurt_path)
    if gemeente_path is None:
        gemeente_path = buurt_path.with_name("gemeente_data.jsonl")
    elif not isinstance(gemeente_path, Path):
        gemeente_path = Path(gemeente_path)

    buurts = []
    gemeentes = []

    with open(buurt_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                line = json.loads(line)
                buurts.append(line)

    if gemeente_path.exists():
        with open(gemeente_path, encoding="utf-8") as f:
            gemeentes = [json.loads(line) for line in f if line.strip()]

    if not buurts:
        raise ValueError(f"No buurt records found in {buurt_path}")

    buurt_codes = {row["code"] for row in buurts}
    wijk_codes = {row["wijkcode"] for row in buurts}
    gemeente_codes = {row["gemeentecode"] for row in buurts}
    gemeentes = [
        row for row in gemeentes if row["gemeentecode"] in gemeente_codes
    ]

    peiljaar_by_code = {
        row["gemeentecode"]: row.get("peiljaar") for row in gemeentes
    }

    for row in buurts:
        row.setdefault("peiljaar", peiljaar_by_code.get(row["gemeentecode"]))

    # The buurt file repeats each wijk and gemeente once per buurt. Upserting
    # the same key thousands of times is pure round-trip latency, so collapse
    # to one row per code first — last occurrence wins, as it did before.
    wijk_rows = {row["wijkcode"]: (row["wijk_naam"], row["wijkcode"]) for row in buurts}
    gemeente_rows = {
        row["gemeentecode"]: (
            row["gemeente_naam"], row["gemeentecode"], row.get("province"),
        )
        for row in buurts
    }
    wijk_edges = {
        row["wijkcode"]: (row["wijkcode"], row["gemeentecode"]) for row in buurts
    }

    # Nodes before the edges that reference them.
    stages = [
        ("gemeente references", "insert_gemeente_reference", [
            (row["gemeente"], row["gemeentecode"],
             row.get("DimensionGroupId"), row.get("peiljaar"))
            for row in gemeentes
        ]),
        ("buurt nodes", "insert_buurt_node", [
            tuple(clean(row.get(src), col) for col, src in COLUMNS.items())
            for row in buurts
        ]),
        ("wijk nodes", "insert_wijk_node", list(wijk_rows.values())),
        ("gemeente nodes", "insert_gemeente_node", list(gemeente_rows.values())),
        ("buurt-wijk edges", "insert_buurt_wijk_edge", [
            (row["code"], row["wijkcode"]) for row in buurts
        ]),
        ("wijk-gemeente edges", "insert_wijk_gemeente_edge", list(wijk_edges.values())),
    ]

    print("Ingesting CBS data")
    with client.transaction():
        for label, statement, rows in stages:
            print(f"  {label:<22} {len(rows):>8,}", flush=True)
            client.insert_many(client.inserts[statement]["query"], rows)

        print("  pruning stale nodes and refreshing aggregates", flush=True)

        client.insert(
            client.inserts["delete_stale_buurt_nodes"]["query"],
            (sorted(buurt_codes),),
        )
        client.insert(
            client.inserts["delete_stale_wijk_nodes"]["query"],
            (sorted(wijk_codes),),
        )
        client.insert(
            client.inserts["delete_stale_gemeente_nodes"]["query"],
            (sorted(gemeente_codes),),
        )
        client.insert(client.inserts["refresh_cbs_aggregates"]["query"])


if __name__ == "__main__":

    pass

