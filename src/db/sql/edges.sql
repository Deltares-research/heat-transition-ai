CREATE TABLE IF NOT EXISTS buurt_wijk_edges (
    buurt_code TEXT PRIMARY KEY REFERENCES buurt_nodes(code) ON DELETE CASCADE,
    wijk_code  TEXT NOT NULL REFERENCES wijk_nodes(code)  ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS buurt_wijk_edges_wijk_code_idx
    ON buurt_wijk_edges (wijk_code);

CREATE UNIQUE INDEX IF NOT EXISTS buurt_wijk_edges_buurt_code_unique_idx
    ON buurt_wijk_edges (buurt_code);

CREATE TABLE IF NOT EXISTS wijk_gemeente_edges (
    wijk_code     TEXT PRIMARY KEY REFERENCES wijk_nodes(code)     ON DELETE CASCADE,
    gemeente_code TEXT NOT NULL REFERENCES gemeente_nodes(code) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS wijk_gemeente_edges_gemeente_code_idx
    ON wijk_gemeente_edges (gemeente_code);

CREATE UNIQUE INDEX IF NOT EXISTS wijk_gemeente_edges_wijk_code_unique_idx
    ON wijk_gemeente_edges (wijk_code);

CREATE TABLE IF NOT EXISTS report_gemeente_edges (
    doc_id         TEXT NOT NULL REFERENCES report_nodes(doc_id) ON DELETE CASCADE,
    gemeente_code  TEXT NOT NULL REFERENCES gemeente_nodes(code) ON DELETE CASCADE,
    PRIMARY KEY (doc_id, gemeente_code)
);

CREATE INDEX IF NOT EXISTS report_gemeente_edges_gemeente_code_idx
    ON report_gemeente_edges (gemeente_code);

CREATE TABLE IF NOT EXISTS chunk_report_edges (
    chunk_id TEXT PRIMARY KEY REFERENCES chunk_nodes(id) ON DELETE CASCADE,
    doc_id   TEXT NOT NULL REFERENCES report_nodes(doc_id) ON DELETE CASCADE,
    UNIQUE (doc_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS chunk_report_edges_doc_id_idx
    ON chunk_report_edges (doc_id);

CREATE TABLE IF NOT EXISTS chunk_gemeente_edges (
    chunk_id       TEXT NOT NULL REFERENCES chunk_nodes(id) ON DELETE CASCADE,
    gemeente_code TEXT NOT NULL REFERENCES gemeente_nodes(code) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, gemeente_code)
);

CREATE INDEX IF NOT EXISTS chunk_gemeente_edges_gemeente_code_idx
    ON chunk_gemeente_edges (gemeente_code);

CREATE TABLE IF NOT EXISTS answer_chunk_edges (
    answer_id TEXT PRIMARY KEY REFERENCES chunk_answer_nodes(id) ON DELETE CASCADE,
    chunk_id  TEXT NOT NULL REFERENCES chunk_nodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS answer_chunk_edges_chunk_id_idx
    ON answer_chunk_edges (chunk_id);

CREATE TABLE IF NOT EXISTS chunk_area_edges (
    chunk_id TEXT NOT NULL REFERENCES chunk_nodes(id) ON DELETE CASCADE,
    area_id  TEXT NOT NULL REFERENCES area_nodes(id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, area_id)
);

CREATE INDEX IF NOT EXISTS chunk_area_edges_area_id_idx
    ON chunk_area_edges (area_id);

CREATE OR REPLACE FUNCTION refresh_cbs_aggregates()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    WITH aggregates AS (
        SELECT
            edge.wijk_code AS code,
            MIN(buurt.province) AS province,
            SUM(buurt.population) AS population,
            SUM(buurt.households) AS households,
            SUM(buurt.dwellings) AS dwellings,
            SUM(buurt.non_residential) AS non_residential,
            SUM(buurt.land_area) AS land_area,
            SUM(buurt.total_area) AS total_area,
            SUM(buurt.avg_household_size * buurt.households)
                / NULLIF(SUM(buurt.households) FILTER (WHERE buurt.avg_household_size IS NOT NULL), 0)
                AS avg_household_size,
            SUM(buurt.owned_pct * buurt.dwellings)
                / NULLIF(SUM(buurt.dwellings) FILTER (WHERE buurt.owned_pct IS NOT NULL), 0)
                AS owned_pct,
            SUM(buurt.rented_pct * buurt.dwellings)
                / NULLIF(SUM(buurt.dwellings) FILTER (WHERE buurt.rented_pct IS NOT NULL), 0)
                AS rented_pct,
            SUM(buurt.social_pct * buurt.dwellings)
                / NULLIF(SUM(buurt.dwellings) FILTER (WHERE buurt.social_pct IS NOT NULL), 0)
                AS social_pct,
            SUM(buurt.multi_family_pct * buurt.dwellings)
                / NULLIF(SUM(buurt.dwellings) FILTER (WHERE buurt.multi_family_pct IS NOT NULL), 0)
                AS multi_family_pct,
            SUM(buurt.woz_valuation * buurt.dwellings)
                / NULLIF(SUM(buurt.dwellings) FILTER (WHERE buurt.woz_valuation IS NOT NULL), 0)
                AS woz_valuation,
            SUM(buurt.population) * 100.0
                / NULLIF(SUM(buurt.land_area), 0) AS pop_density,
            SUM(buurt.address_density * buurt.land_area)
                / NULLIF(SUM(buurt.land_area) FILTER (WHERE buurt.address_density IS NOT NULL), 0)
                AS address_density,
            MAX(buurt.peiljaar) AS peiljaar
        FROM buurt_nodes buurt
        JOIN buurt_wijk_edges edge ON edge.buurt_code = buurt.code
        GROUP BY edge.wijk_code
    )
    UPDATE wijk_nodes wijk
    SET province = aggregate.province,
        population = aggregate.population,
        households = aggregate.households,
        avg_household_size = aggregate.avg_household_size,
        dwellings = aggregate.dwellings,
        owned_pct = aggregate.owned_pct,
        rented_pct = aggregate.rented_pct,
        social_pct = aggregate.social_pct,
        multi_family_pct = aggregate.multi_family_pct,
        non_residential = aggregate.non_residential,
        woz_valuation = aggregate.woz_valuation,
        land_area = aggregate.land_area,
        total_area = aggregate.total_area,
        pop_density = aggregate.pop_density,
        address_density = aggregate.address_density,
        urbanity = CASE
            WHEN aggregate.address_density >= 2500 THEN 1
            WHEN aggregate.address_density >= 1500 THEN 2
            WHEN aggregate.address_density >= 1000 THEN 3
            WHEN aggregate.address_density >= 500 THEN 4
            WHEN aggregate.address_density IS NOT NULL THEN 5
        END,
        peiljaar = aggregate.peiljaar
    FROM aggregates aggregate
    WHERE wijk.code = aggregate.code;

    WITH aggregates AS (
        SELECT
            edge.gemeente_code AS code,
            MIN(wijk.province) AS province,
            SUM(wijk.population) AS population,
            SUM(wijk.households) AS households,
            SUM(wijk.dwellings) AS dwellings,
            SUM(wijk.non_residential) AS non_residential,
            SUM(wijk.land_area) AS land_area,
            SUM(wijk.total_area) AS total_area,
            SUM(wijk.avg_household_size * wijk.households)
                / NULLIF(SUM(wijk.households) FILTER (WHERE wijk.avg_household_size IS NOT NULL), 0)
                AS avg_household_size,
            SUM(wijk.owned_pct * wijk.dwellings)
                / NULLIF(SUM(wijk.dwellings) FILTER (WHERE wijk.owned_pct IS NOT NULL), 0)
                AS owned_pct,
            SUM(wijk.rented_pct * wijk.dwellings)
                / NULLIF(SUM(wijk.dwellings) FILTER (WHERE wijk.rented_pct IS NOT NULL), 0)
                AS rented_pct,
            SUM(wijk.social_pct * wijk.dwellings)
                / NULLIF(SUM(wijk.dwellings) FILTER (WHERE wijk.social_pct IS NOT NULL), 0)
                AS social_pct,
            SUM(wijk.multi_family_pct * wijk.dwellings)
                / NULLIF(SUM(wijk.dwellings) FILTER (WHERE wijk.multi_family_pct IS NOT NULL), 0)
                AS multi_family_pct,
            SUM(wijk.woz_valuation * wijk.dwellings)
                / NULLIF(SUM(wijk.dwellings) FILTER (WHERE wijk.woz_valuation IS NOT NULL), 0)
                AS woz_valuation,
            SUM(wijk.population) * 100.0
                / NULLIF(SUM(wijk.land_area), 0) AS pop_density,
            SUM(wijk.address_density * wijk.land_area)
                / NULLIF(SUM(wijk.land_area) FILTER (WHERE wijk.address_density IS NOT NULL), 0)
                AS address_density,
            MAX(wijk.peiljaar) AS peiljaar
        FROM wijk_nodes wijk
        JOIN wijk_gemeente_edges edge ON edge.wijk_code = wijk.code
        GROUP BY edge.gemeente_code
    )
    UPDATE gemeente_nodes gemeente
    SET province = COALESCE(aggregate.province, gemeente.province),
        population = aggregate.population,
        households = aggregate.households,
        avg_household_size = aggregate.avg_household_size,
        dwellings = aggregate.dwellings,
        owned_pct = aggregate.owned_pct,
        rented_pct = aggregate.rented_pct,
        social_pct = aggregate.social_pct,
        multi_family_pct = aggregate.multi_family_pct,
        non_residential = aggregate.non_residential,
        woz_valuation = aggregate.woz_valuation,
        land_area = aggregate.land_area,
        total_area = aggregate.total_area,
        pop_density = aggregate.pop_density,
        address_density = aggregate.address_density,
        urbanity = CASE
            WHEN aggregate.address_density >= 2500 THEN 1
            WHEN aggregate.address_density >= 1500 THEN 2
            WHEN aggregate.address_density >= 1000 THEN 3
            WHEN aggregate.address_density >= 500 THEN 4
            WHEN aggregate.address_density IS NOT NULL THEN 5
        END,
        peiljaar = COALESCE(aggregate.peiljaar, gemeente.peiljaar)
    FROM aggregates aggregate
    WHERE gemeente.code = aggregate.code;
END;
$$;


