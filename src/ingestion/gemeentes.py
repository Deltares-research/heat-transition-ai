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
}


INT_COLS = {"population", "households", "non_residential", "land_area", "total_area"}


def clean(v, col):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return int(round(float(v))) if col in INT_COLS else v


def ingest_gemeentes(client: DBClient, buurt_path: Path | str) -> None:

    if not isinstance(buurt_path, Path):
        buurt_path = Path(buurt_path)

    buurts = []

    with open(buurt_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                line = json.loads(line)
                buurts.append(line)

    for row in tqdm(buurts, desc="Ingesting nodes"):
        values = tuple(clean(row.get(src), col) for col, src in COLUMNS.items())
        client.insert(client.inserts["insert_buurt_node"]["query"], values)
        client.insert(client.inserts["insert_wijk_node"]["query"], (row["wijk_naam"], row["wijkcode"]))
        client.insert(client.inserts["insert_gemeente_node"]["query"], (row["gemeente_naam"], row["gemeentecode"]))

    for row in tqdm(buurts, desc="Ingesting edges"):
        client.insert(client.inserts["insert_buurt_wijk_edge"]["query"], (row["code"], row["wijkcode"]))
        client.insert(client.inserts["insert_wijk_gemeente_edge"]["query"], (row["wijkcode"], row["gemeentecode"]))


if __name__ == "__main__":

    pass

