from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

BASE = "https://datasets.cbs.nl/odata/v1/CBS"
TIMEOUT = 120

# Kerncijfers wijken en buurten
KWB = "86165NED"
DIMENSION = "WijkenEnBuurten"

WANTED = {
    # size
    "inwoners":              ("aantal inwoners", "inwoners > totaal"),
    "huishoudens":           ("huishoudens totaal", "particuliere huishoudens"),
    "huishoudensgrootte":    ("gemiddelde huishoudensgrootte",),
    "bevolkingsdichtheid":   ("bevolkingsdichtheid",),

    # area
    "oppervlakte_totaal":    ("oppervlakte > totaal", "oppervlakte totaal"),
    "oppervlakte_land":      ("oppervlakte > land", "oppervlakte land"),

    # buildings — the core of it
    "woningvoorraad":        ("woningvoorraad",),
    "woningen_bouwjaar_voor2000": ("bouwjaar voor 2000",),
    "woningen_bouwjaar_vanaf2000": ("bouwjaar vanaf 2000",),
    "koopwoningen_pct":      ("koopwoningen",),
    "huurwoningen_pct":      ("huurwoningen totaal", "huurwoningen"),
    "corporatiewoningen_pct": ("in bezit woningcorporatie", "corporatie"),
    "woz_waarde":            ("gemiddelde woningwaarde", "woz"),
    "meergezins_pct":        ("meergezinswoning",),
    "leegstand_pct":         ("leegstand",),

    # non-residential
    "niet_woningen":         ("niet-woningen", "aantal niet-woningen"),

    # energy — present in some KWB years
    "gas_gemiddeld":         ("gemiddeld aardgasverbruik", "aardgasverbruik totaal"),
    "elek_gemiddeld":        ("gemiddeld elektriciteitsverbruik", "elektriciteitsverbruik totaal"),
    "stadsverwarming_pct":   ("stadsverwarming", "blokverwarming"),

    # context
    "stedelijkheid":         ("mate van stedelijkheid",),
    "omgevingsadressen":     ("omgevingsadressendichtheid",),
}


PROVINCE_BY_GROUP = {
    "GMPV20": "Groningen",     "GMPV21": "Fryslân",
    "GMPV22": "Drenthe",       "GMPV23": "Overijssel",
    "GMPV24": "Flevoland",     "GMPV25": "Gelderland",
    "GMPV26": "Utrecht",       "GMPV27": "Noord-Holland",
    "GMPV28": "Zuid-Holland",  "GMPV29": "Zeeland",
    "GMPV30": "Noord-Brabant", "GMPV31": "Limburg",
}


def odata_pages(url: str, params: dict | None = None) -> Iterator[dict]:
    session = requests.Session()
    n = 0
    while url:
        r = session.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("value", [])
        n += len(rows)
        yield from rows
        url = payload.get("@odata.nextLink")
        params = None
        if url:
            print(f"    ...{n:,} rows", end="\r", file=sys.stderr)
    if n:
        print(f"    {n:,} rows          ", file=sys.stderr)


def odata_frame(table: str, resource: str, **params) -> pd.DataFrame:
    return pd.DataFrame(odata_pages(f"{BASE}/{table}/{resource}", params or None))


def discover(term: str) -> pd.DataFrame:
    df = pd.DataFrame(
        odata_pages(f"{BASE}/Datasets", {"$filter": f"contains(Title,'{term}')"})
    )
    cols = [c for c in ("Identifier", "Title", "Period", "Modified") if c in df]
    return df[cols].sort_values("Title") if cols else df


def measure_paths(table: str) -> pd.DataFrame:
    """Catalog with a `Path` column: 'Group > Subgroup > Title'."""
    cat = odata_frame(table, "MeasureCodes")
    if cat.empty:
        raise SystemExit(f"{table}: MeasureCodes returned nothing. Wrong table code?")

    groups = odata_frame(table, "MeasureGroups")
    if groups.empty or "MeasureGroupId" not in cat:
        cat["Path"] = cat["Title"].fillna("")
        return cat

    title_of = dict(zip(groups["Id"], groups["Title"]))
    parent_of = dict(zip(groups["Id"], groups.get("ParentId", pd.Series(dtype=object))))

    def ancestry(gid) -> str:
        parts, seen = [], set()
        while gid is not None and gid in title_of and gid not in seen:
            seen.add(gid)
            parts.append(str(title_of[gid]))
            gid = parent_of.get(gid)
        return " > ".join(reversed(parts))

    cat["Path"] = [
        f"{ancestry(g)} > {t}".strip(" >")
        for g, t in zip(cat["MeasureGroupId"], cat["Title"].fillna(""))
    ]
    return cat


def resolve_measures(table: str) -> dict[str, str]:
    cat = measure_paths(table)
    paths = cat["Path"].fillna("").str.lower()

    resolved: dict[str, str] = {}
    unmatched: list[str] = []

    for col, patterns in WANTED.items():
        hit = None
        for pat in patterns:
            mask = paths.str.contains(re.escape(pat.lower()), regex=True)
            if mask.any():
                hit = cat.loc[mask, "Identifier"].iloc[0].strip()
                break
        if hit and hit not in resolved:
            resolved[hit] = col
        elif not hit:
            unmatched.append(col)

    print(f"resolved {len(resolved)}/{len(WANTED)} measures", file=sys.stderr)
    if unmatched:
        print(f"  not matched: {unmatched}", file=sys.stderr)
        for col in unmatched:
            words = [w for p in WANTED[col] for w in p.split() if len(w) > 4]
            if not words:
                continue
            mask = paths.str.contains("|".join(re.escape(w.lower()) for w in words))
            for _, row in cat.loc[mask, ["Identifier", "Path"]].head(5).iterrows():
                print(f"    ? {col:26} {row.Identifier:<30} {row.Path}", file=sys.stderr)

    if not resolved:
        raise SystemExit(f"No wanted measures found in {table}.")
    return resolved


def fetch_buurten(table: str, measures: dict[str, str],
                  gemeente: str | None = None) -> pd.DataFrame:
    """Wide frame, one row per buurt."""
    measure_filter = " or ".join(f"Measure eq '{m}'" for m in measures)

    prefix = f"BU{gemeente.replace('GM', '')}" if gemeente else "BU"
    print(f"  fetching {prefix}...", file=sys.stderr)

    obs = odata_frame(
        table, "Observations",
        **{"$filter": f"startswith({DIMENSION},'{prefix}') and ({measure_filter})",
           "$select": f"Measure,{DIMENSION},Value"},
    )
    if obs.empty:
        raise SystemExit("no buurt observations returned")

    obs["Measure"] = obs["Measure"].str.strip()
    obs = obs[obs["Value"].notna()]

    wide = (
        obs.pivot_table(index=DIMENSION, columns="Measure", values="Value",
                        aggfunc="first")
        .rename(columns=measures)
    )
    wide.index = wide.index.str.strip()
    wide.index.name = "code"
    return wide.reset_index()


def fetch_labels(table: str) -> dict[str, str]:
    """code -> name, for every level. Buurt rows need the wijk and gemeente names."""
    codes = odata_frame(table, f"{DIMENSION}Codes")
    codes["Identifier"] = codes["Identifier"].str.strip()
    return dict(zip(codes["Identifier"], codes["Title"]))


def load_provinces(path: Path) -> dict[str, str]:
    """
    gemeentecode -> province, from gemeente_data.jsonl.

    Uses the `province` column when present, otherwise derives it from the
    CBS region group code (GMPV23 -> Overijssel), which fetch_gemeenten.py
    carries as DimensionGroupId. The KWB table's own hierarchy does not
    reliably expose provinces.
    """
    if not path.exists():
        print(f"note: {path} not found — province will be null", file=sys.stderr)
        return {}

    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        code = r.get("gemeentecode")
        prov = r.get("province") or PROVINCE_BY_GROUP.get(r.get("DimensionGroupId"))
        if code and prov:
            out[code] = prov

    print(f"provinces loaded for {len(out)} municipalities", file=sys.stderr)
    if not out:
        print(f"  {path.name} has neither a 'province' key nor a recognised "
              f"DimensionGroupId", file=sys.stderr)
    return out


def build(table: str, gemeente_path: Path, gemeente: str | None = None) -> pd.DataFrame:
    measures = resolve_measures(table)
    out = fetch_buurten(table, measures, gemeente)

    name_of = fetch_labels(table)
    province_of = load_provinces(gemeente_path)

    # Codes nest: BU01930101 -> WK019301 -> GM0193
    out["naam"] = out["code"].map(name_of)
    out["wijkcode"] = "WK" + out["code"].str[2:8]
    out["wijk_naam"] = out["wijkcode"].map(name_of)
    out["gemeentecode"] = "GM" + out["code"].str[2:6]
    out["gemeente_naam"] = out["gemeentecode"].map(name_of)
    out["province"] = out["gemeentecode"].map(province_of)

    front = ["code", "naam", "wijkcode", "wijk_naam",
             "gemeentecode", "gemeente_naam", "province"]
    out = out[front + [c for c in out.columns if c not in front]]
    out = out.sort_values(["province", "gemeente_naam", "code"]).reset_index(drop=True)

    print(f"\n{len(out):,} buurten in {out['gemeentecode'].nunique()} municipalities",
          file=sys.stderr)

    for col in ("naam", "wijk_naam", "gemeente_naam", "province"):
        n = out[col].isna().sum()
        if n:
            print(f"WARNING: {col} null for {n:,} rows", file=sys.stderr)

    empty = [c for c in out.columns if out[c].isna().all()]
    if empty:
        print(f"WARNING: columns entirely null: {empty}", file=sys.stderr)

    filled = out.notna().mean().sort_values()
    thin = filled[filled < 0.5]
    if len(thin):
        print(f"note: sparse (CBS suppresses small areas): "
              f"{ {k: f'{v:.0%}' for k, v in thin.items()} }", file=sys.stderr)

    return out


def write_jsonl(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.astype(object).where(pd.notnull(df), None)
    with path.open("w", encoding="utf-8") as fh:
        for record in out.to_dict(orient="records"):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {len(out):,} records to {path}", file=sys.stderr)


if __name__ == "__main__":

    data_path = Path(__file__).parents[1] / "data/cbs"
    data_path.mkdir(parents=True, exist_ok=True)

    df = build(KWB, gemeente_path=data_path / "gemeente_data.jsonl")

    write_jsonl(df, data_path / "buurt_data.jsonl")

