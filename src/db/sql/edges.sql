CREATE TABLE IF NOT EXISTS buurt_wijk_edges (
    buurt_code TEXT NOT NULL REFERENCES buurt_nodes(code) ON DELETE CASCADE,
    wijk_code  TEXT NOT NULL REFERENCES wijk_nodes(code)  ON DELETE CASCADE,
    PRIMARY KEY (buurt_code, wijk_code)
);

CREATE TABLE IF NOT EXISTS wijk_gemeente_edges (
    wijk_code     TEXT NOT NULL REFERENCES wijk_nodes(code)     ON DELETE CASCADE,
    gemeente_code TEXT NOT NULL REFERENCES gemeente_nodes(code) ON DELETE CASCADE,
    PRIMARY KEY (wijk_code, gemeente_code)
);


