CREATE TABLE IF NOT EXISTS buurt (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    province TEXT,
    population INTEGER,
    households INTEGER,
    avg_household_size FLOAT,
    dwellings INTEGER,
    dwellings_pre2000 INTEGER,
    dwellings_post2000 INTEGER,
    owned_pct FLOAT,
    rented_pct FLOAT,
    social_pct FLOAT,
    multi_family_pct FLOAT,
    non_residential INTEGER,
    woz_valuation FLOAT,
    land_area INTEGER,
    total_area INTEGER,
    pop_density FLOAT,
    address_density FLOAT,
    urbanity INTEGER,
    peiljaar INTEGER
);

CREATE TABLE IF NOT EXISTS wijk (LIKE buurt INCLUDING ALL);

CREATE TABLE IF NOT EXISTS gemeente (LIKE buurt INCLUDING ALL);

CREATE TABLE IF NOT EXISTS question (
    id          TEXT PRIMARY KEY,
    section     TEXT,
    type        TEXT NOT NULL CHECK (type IN ('split','count','bool','enum','status','text')),
    allowed     TEXT[],                 -- enum/status vocabulary, else NULL
    nl          TEXT NOT NULL,
    en          TEXT NOT NULL,
    ord         INTEGER NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    origin TEXT
);

