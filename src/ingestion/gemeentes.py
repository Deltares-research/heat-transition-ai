from pathlib import Path
import json
from src.db.db_client import DBClient
import math
from tqdm import tqdm


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

    try:
        for row in tqdm(gemeentes, desc="Ingesting gemeente references"):
            values = (
                row["gemeente"], row["gemeentecode"],
                row.get("DimensionGroupId"), row.get("peiljaar"),
            )
            client.insert(client.inserts["insert_gemeente_reference"]["query"], values)

        for row in tqdm(buurts, desc="Ingesting nodes"):
            row.setdefault("peiljaar", peiljaar_by_code.get(row["gemeentecode"]))
            values = tuple(clean(row.get(src), col) for col, src in COLUMNS.items())
            client.insert(client.inserts["insert_buurt_node"]["query"], values)
            client.insert(
                client.inserts["insert_wijk_node"]["query"],
                (row["wijk_naam"], row["wijkcode"]),
            )
            client.insert(
                client.inserts["insert_gemeente_node"]["query"],
                (row["gemeente_naam"], row["gemeentecode"], row.get("province")),
            )

        for row in tqdm(buurts, desc="Ingesting edges"):
            client.insert(
                client.inserts["insert_buurt_wijk_edge"]["query"],
                (row["code"], row["wijkcode"]),
            )
            client.insert(
                client.inserts["insert_wijk_gemeente_edge"]["query"],
                (row["wijkcode"], row["gemeentecode"]),
            )

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
        client.conn.commit()
    except Exception:
        client.conn.rollback()
        raise


if __name__ == "__main__":

    pass

