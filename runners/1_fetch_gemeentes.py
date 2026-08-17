from __future__ import annotations
import json
import re
import sys
from typing import Iterator
import pandas as pd
import requests
from pathlib import Path

BASE = "https://datasets.cbs.nl/odata/v1/CBS"
TIMEOUT = 60

# Regionale kerncijfers Nederland — population, area, density, housing stock.
# Stable table, cited in the Enqualia report as the enrichment source.
KERNCIJFERS = "70072ned"

# Measures wanted from KERNCIJFERS, resolved at runtime by matching Title.
# CBS measure identifiers carry numeric suffixes (Bevolkingsdichtheid_57) that
# change between table revisions, so nothing here is hardcoded.
# Each value is a tuple of title fragments; first match wins.
WANTED = {
    # 70072ned has both a 1-January count and a period average; the average
    # yields half-people (161143.5), so match the 1-January measure first.
    "inwoners":              ("op 1 januari", "aantal inwoners", "totale bevolking"),
    "bevolkingsdichtheid":   ("bevolkingsdichtheid",),
    # Reported in km2 despite the group label; see build() for the check.
    "oppervlakte_land_km2":  ("oppervlakte > land", "oppervlakte land", "land"),
    "woningvoorraad":        ("woningvoorraad", "voorraad woningen"),
    "woz_waarde_k":          ("gemiddelde woningwaarde", "woz"),
    "huurwoningen_pct":      ("huurwoningen",),
    "koopwoningen_pct":      ("koopwoningen",),
    # Must be the 1-5 class code, not an address count within a class.
    "stedelijkheid":         ("mate van stedelijkheid",),
    "omgevingsadressen":     ("omgevingsadressendichtheid",),
}


def odata_pages(url: str, params: dict | None = None) -> Iterator[dict]:
    """Yield rows from an OData v4 endpoint, following @odata.nextLink."""
    session = requests.Session()
    while url:
        r = session.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        yield from payload.get("value", [])
        url = payload.get("@odata.nextLink")
        params = None  # nextLink already carries the query


def odata_frame(table: str, resource: str, **params) -> pd.DataFrame:
    url = f"{BASE}/{table}/{resource}"
    return pd.DataFrame(odata_pages(url, params or None))


# ──────────────────────────────────────────────────────────────
# Discovery helpers — CBS renames and re-codes tables every year
# ──────────────────────────────────────────────────────────────

def discover(term: str) -> pd.DataFrame:
    """Find CBS tables whose title contains `term`."""
    df = pd.DataFrame(
        odata_pages(f"{BASE}/Datasets", {"$filter": f"contains(Title,'{term}')"})
    )
    cols = [c for c in ("Identifier", "Title", "Period", "Modified") if c in df]
    return df[cols].sort_values("Title") if cols else df


def list_measures(table: str) -> pd.DataFrame:
    df = odata_frame(table, "MeasureCodes")
    if df.empty:
        raise SystemExit(f"{table}: MeasureCodes returned nothing. Wrong table code?")
    return df[[c for c in ("Identifier", "Title", "Unit") if c in df]]


def list_periods(table: str) -> pd.DataFrame:
    df = odata_frame(table, "PeriodenCodes")
    if df.empty:
        raise SystemExit(f"{table}: PeriodenCodes returned nothing.")
    return df[[c for c in ("Identifier", "Title") if c in df]]


def list_dimensions(table: str) -> list[str]:
    props = odata_frame(table, "Properties")
    return props["Identifier"].tolist() if "Identifier" in props else []


def measure_paths(table: str) -> pd.DataFrame:
    """
    MeasureCodes carries leaf titles only ("Totaal"), with the meaning held in
    the MeasureGroups hierarchy. Return the catalog with a `Path` column
    holding the full "Group > Subgroup > Title" string, which is what the
    WANTED patterns are matched against.
    """
    cat = list_measures(table).copy()
    raw = odata_frame(table, "MeasureCodes")
    if "MeasureGroupId" in raw:
        cat["MeasureGroupId"] = raw["MeasureGroupId"]

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
    """Map CBS measure identifier -> our column name, matching on full path."""
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
        if hit:
            resolved[hit] = col
        else:
            unmatched.append(col)

    if unmatched:
        print(f"note: no measure matched for {unmatched}", file=sys.stderr)
        for col in unmatched:
            words = [w for p in WANTED[col] for w in p.split() if len(w) > 4]
            if not words:
                continue
            mask = paths.str.contains("|".join(re.escape(w.lower()) for w in words))
            cand = cat.loc[mask, ["Identifier", "Path"]].head(8)
            if not cand.empty:
                print(f"  candidates for '{col}':", file=sys.stderr)
                for _, row in cand.iterrows():
                    print(f"    {row.Identifier:<32} {row.Path}", file=sys.stderr)

    if not resolved:
        raise SystemExit(f"None of the wanted measures exist in {table}.")

    print(f"resolved {len(resolved)} measures", file=sys.stderr)
    lookup = cat.set_index("Identifier")
    for ident, col in resolved.items():
        row = lookup.loc[ident] if ident in lookup.index else None
        unit = row.get("Unit", "") if row is not None else ""
        path = row.get("Path", "") if row is not None else ""
        print(f"  {col:<22} {ident:<28} [{unit}] {path}", file=sys.stderr)
    return resolved


def _period_has_data(table: str, period: str, probe_measure: str) -> bool:
    """A period can exist in the catalog with no observations yet."""
    obs = odata_frame(
        table,
        "Observations",
        **{
            "$filter": f"startswith(RegioS,'GM') and Perioden eq '{period}' "
                       f"and Measure eq '{probe_measure}'",
            "$select": "Value",
            "$top": "50",
        },
    )
    return not obs.empty and obs["Value"].notna().any()


def resolve_period(table: str, year: int | None, probe_measure: str) -> str:
    """
    Validate the requested year, or walk back from the newest annual period
    until one actually carries data. CBS publishes the period code before the
    figures, so the newest listed year is often empty.
    """
    cat = list_periods(table)
    annual = sorted(i.strip() for i in cat["Identifier"] if i.strip().endswith("JJ00"))
    if not annual:
        raise SystemExit(f"{table}: no annual (JJ00) periods found.")

    if year is not None:
        want = f"{year}JJ00"
        if want not in annual:
            raise SystemExit(
                f"Period {want} not available in {table}.\n"
                f"Available range: {annual[0]} .. {annual[-1]}"
            )
        if not _period_has_data(table, want, probe_measure):
            print(f"WARNING: {want} exists but has no data for the probe measure.",
                  file=sys.stderr)
        return want

    for period in reversed(annual[-6:]):
        if _period_has_data(table, period, probe_measure):
            print(f"using most recent populated period: {period}", file=sys.stderr)
            return period

    raise SystemExit(
        f"None of the last 6 annual periods in {table} carry data "
        f"for probe measure {probe_measure}."
    )


def fetch_kerncijfers(period: str, measures: dict[str, str]) -> pd.DataFrame:
    """Wide frame of key figures, municipalities only."""
    measure_filter = " or ".join(f"Measure eq '{m}'" for m in measures)

    obs = odata_frame(
        KERNCIJFERS,
        "Observations",
        **{
            "$filter": f"startswith(RegioS,'GM') and Perioden eq '{period}' "
                       f"and ({measure_filter})",
            "$select": "Measure,RegioS,Value",
        },
    )
    if obs.empty:
        raise SystemExit(
            f"Empty result for period {period} with {len(measures)} measures.\n"
            f"Both were validated against the catalog, so this is likely a "
            f"filter-syntax issue. Try one measure at a time to isolate it."
        )

    obs["Measure"] = obs["Measure"].str.strip()

    # Null observations exist for periods CBS has opened but not populated,
    # and for municipalities that no longer exist. Dropping them here both
    # keeps pivot_table from silently discarding all-null columns and leaves
    # only municipalities that are actually current in this period.
    before = len(obs)
    obs = obs[obs["Value"].notna()]
    if obs.empty:
        raise SystemExit(
            f"All {before} observations for {period} are null — CBS has opened "
            f"the period but not published figures. Pass an earlier year."
        )

    wide = obs.pivot_table(
        index="RegioS", columns="Measure", values="Value", aggfunc="first"
    ).rename(columns=measures)
    wide.index = wide.index.str.strip()
    wide.index.name = "gemeentecode"
    return wide.reset_index()


def fetch_regio_labels() -> pd.DataFrame:
    """Municipality names and their parent regions (province, COROP)."""
    codes = odata_frame(KERNCIJFERS, "RegioSCodes")
    gm = codes[codes["Identifier"].str.strip().str.startswith("GM")].copy()
    gm["Identifier"] = gm["Identifier"].str.strip()
    keep = [c for c in ("Identifier", "Title", "DimensionGroupId") if c in gm]
    return gm[keep].rename(
        columns={"Identifier": "gemeentecode", "Title": "gemeente"}
    )


def fetch_gebieden(table: str) -> pd.DataFrame:
    """
    Stedelijkheid, omgevingsadressendichtheid and the province mapping from
    the annual 'Gebieden in Nederland' table. The table code changes each year —
    pass it explicitly, find it with --discover "Gebieden in Nederland".
    """
    obs = odata_frame(
        table,
        "Observations",
        **{"$filter": "startswith(RegioS,'GM')", "$select": "Measure,RegioS,Value"},
    )
    if obs.empty:
        print(f"note: {table} returned no municipal observations", file=sys.stderr)
        return pd.DataFrame()
    obs["Measure"] = obs["Measure"].str.strip()
    wide = obs.pivot_table(
        index="RegioS", columns="Measure", values="Value", aggfunc="first"
    )
    wide.index = wide.index.str.strip()
    wide.index.name = "gemeentecode"
    return wide.reset_index()


# ──────────────────────────────────────────────────────────────
# Assemble
# ──────────────────────────────────────────────────────────────

def build(year: int | None = None, gebieden_table: str | None = None) -> pd.DataFrame:
    measures = resolve_measures(KERNCIJFERS)
    period = resolve_period(KERNCIJFERS, year, probe_measure=next(iter(measures)))

    # Inner join: RegioSCodes lists every municipality the table has ever
    # covered (700+ including ones merged away decades ago). Only those with
    # observations in this period are current.
    df = fetch_regio_labels().merge(
        fetch_kerncijfers(period, measures), on="gemeentecode", how="inner"
    )

    if gebieden_table:
        gb = fetch_gebieden(gebieden_table)
        if not gb.empty:
            df = df.merge(gb, on="gemeentecode", how="left")

    dropped = set(measures.values()) - set(df.columns)
    if dropped:
        print(
            f"note: resolved but empty for {period}: {sorted(dropped)} — "
            f"CBS has no values for these in this year.",
            file=sys.stderr,
        )

    df["peiljaar"] = int(period[:4])

    # Derived features for peer-matching
    if {"inwoners", "oppervlakte_land_km2"} <= set(df.columns):
        df["dichtheid_inw_km2"] = (
            df["inwoners"] / df["oppervlakte_land_km2"]
        ).round(1)

        # Cross-check: our computed density should track CBS's own figure.
        # A large gap means the area measure is in different units than assumed.
        if "bevolkingsdichtheid" in df:
            both = df[["dichtheid_inw_km2", "bevolkingsdichtheid"]].dropna()
            if not both.empty:
                ratio = (both["dichtheid_inw_km2"] / both["bevolkingsdichtheid"]).median()
                if not 0.9 < ratio < 1.1:
                    print(
                        f"WARNING: computed density is {ratio:.1f}x CBS's own figure. "
                        f"The area measure is probably not km2 — check its Unit.",
                        file=sys.stderr,
                    )

    if "stedelijkheid" in df:
        vals = df["stedelijkheid"].dropna().unique()
        if len(vals) and not set(vals) <= {1, 2, 3, 4, 5, 1.0, 2.0, 3.0, 4.0, 5.0}:
            print(
                f"WARNING: stedelijkheid should be a 1-5 class, got values like "
                f"{sorted(vals)[:3]}. Wrong measure matched.",
                file=sys.stderr,
            )

    if "inwoners" in df:
        if (df["inwoners"].dropna() % 1 != 0).any():
            print(
                "WARNING: inwoners has fractional values — this is the period "
                "average, not the 1-January count.",
                file=sys.stderr,
            )

        df["grootteklasse"] = pd.cut(
            df["inwoners"],
            bins=[0, 20_000, 50_000, 100_000, 250_000, float("inf")],
            labels=["<20k", "20-50k", "50-100k", "100-250k", ">250k"],
        )

    df = df.sort_values("gemeente").reset_index(drop=True)

    n = len(df)
    print(f"{n} municipalities, peiljaar {df['peiljaar'].iloc[0]}", file=sys.stderr)
    if n != 342:
        print(
            f"WARNING: expected 342 for the 2023-2026 indeling, got {n}. "
            "Check the reference year — herindelingen take effect on 1 January.",
            file=sys.stderr,
        )

    empty = [c for c in df.columns if df[c].isna().all()]
    if empty:
        print(f"WARNING: columns entirely null: {empty}", file=sys.stderr)

    return df


def write_jsonl(df: pd.DataFrame, path: str | Path) -> None:
    """One JSON object per line. NaN -> null, Categorical -> str."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    out = df.copy()
    for col in out.select_dtypes(include="category").columns:
        out[col] = out[col].astype("string")
    out = out.astype(object).where(pd.notnull(out), None)

    with open(path, "w", encoding="utf-8") as fh:
        for record in out.to_dict(orient="records"):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"wrote {len(out)} records to {path}", file=sys.stderr)
    for record in out.head(3).to_dict(orient="records"):
        print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":

    data_path = Path(__file__).parents[1] / "data"

    df = build(year=None, gebieden_table=None)
    write_jsonl(df, path=data_path / "gementee_data.jsonl")