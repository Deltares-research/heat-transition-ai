CREATE TABLE IF NOT EXISTS gemeente_nodes (
    code                 TEXT PRIMARY KEY CHECK (code ~ '^GM[0-9]{4}$'),
    name                 TEXT NOT NULL,
    province             TEXT,
    dimension_group_id   TEXT,
    population           BIGINT,
    households           BIGINT,
    avg_household_size   DOUBLE PRECISION,
    dwellings            BIGINT,
    owned_pct            DOUBLE PRECISION,
    rented_pct           DOUBLE PRECISION,
    social_pct           DOUBLE PRECISION,
    multi_family_pct     DOUBLE PRECISION,
    non_residential      BIGINT,
    woz_valuation        DOUBLE PRECISION,
    land_area            BIGINT,
    total_area           BIGINT,
    pop_density          DOUBLE PRECISION,
    address_density      DOUBLE PRECISION,
    urbanity             SMALLINT,
    peiljaar              INTEGER
);

ALTER TABLE gemeente_nodes
    ADD COLUMN IF NOT EXISTS dimension_group_id TEXT;

CREATE TABLE IF NOT EXISTS wijk_nodes (
    code                 TEXT PRIMARY KEY CHECK (code ~ '^WK[0-9]{4}[0-9A-Z]{2}$'),
    name                 TEXT NOT NULL,
    province             TEXT,
    population           BIGINT,
    households           BIGINT,
    avg_household_size   DOUBLE PRECISION,
    dwellings            BIGINT,
    owned_pct            DOUBLE PRECISION,
    rented_pct           DOUBLE PRECISION,
    social_pct           DOUBLE PRECISION,
    multi_family_pct     DOUBLE PRECISION,
    non_residential      BIGINT,
    woz_valuation        DOUBLE PRECISION,
    land_area            BIGINT,
    total_area           BIGINT,
    pop_density          DOUBLE PRECISION,
    address_density      DOUBLE PRECISION,
    urbanity             SMALLINT,
    peiljaar              INTEGER
);

ALTER TABLE wijk_nodes
    DROP CONSTRAINT IF EXISTS wijk_nodes_code_check;

ALTER TABLE wijk_nodes
    ADD CONSTRAINT wijk_nodes_code_check
    CHECK (code ~ '^WK[0-9]{4}[0-9A-Z]{2}$');

CREATE TABLE IF NOT EXISTS buurt_nodes (
    code                 TEXT PRIMARY KEY CHECK (code ~ '^BU[0-9]{4}[0-9A-Z]{2}[0-9]{2}$'),
    name                 TEXT NOT NULL,
    province             TEXT,
    population           BIGINT,
    households           BIGINT,
    avg_household_size   DOUBLE PRECISION,
    dwellings            BIGINT,
    owned_pct            DOUBLE PRECISION,
    rented_pct           DOUBLE PRECISION,
    social_pct           DOUBLE PRECISION,
    multi_family_pct     DOUBLE PRECISION,
    non_residential      BIGINT,
    woz_valuation        DOUBLE PRECISION,
    land_area            BIGINT,
    total_area           BIGINT,
    pop_density          DOUBLE PRECISION,
    address_density      DOUBLE PRECISION,
    urbanity             SMALLINT,
    peiljaar              INTEGER
);

ALTER TABLE buurt_nodes
    ADD COLUMN IF NOT EXISTS urbanity SMALLINT;

ALTER TABLE buurt_nodes
    ADD COLUMN IF NOT EXISTS peiljaar INTEGER;

ALTER TABLE buurt_nodes
    DROP CONSTRAINT IF EXISTS buurt_nodes_code_check;

ALTER TABLE buurt_nodes
    ADD CONSTRAINT buurt_nodes_code_check
    CHECK (code ~ '^BU[0-9]{4}[0-9A-Z]{2}[0-9]{2}$');

CREATE TABLE IF NOT EXISTS question (
    id      TEXT PRIMARY KEY,
    section TEXT,
    type    TEXT NOT NULL CHECK (type IN ('split', 'count', 'bool', 'enum', 'status', 'text')),
    allowed TEXT[],
    nl      TEXT NOT NULL,
    en      TEXT NOT NULL,
    ord     INTEGER NOT NULL,
    active  BOOLEAN NOT NULL DEFAULT TRUE,
    origin  TEXT
);

CREATE TABLE IF NOT EXISTS report_nodes (
    doc_id   TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    language TEXT
);

CREATE TABLE IF NOT EXISTS chunk_nodes (
    id                   TEXT PRIMARY KEY,
    chunk_index          INTEGER NOT NULL CHECK (chunk_index >= 0),
    heading_path         TEXT,
    text                 TEXT NOT NULL,
    char_start           INTEGER CHECK (char_start IS NULL OR char_start >= 0),
    char_end             INTEGER CHECK (char_end IS NULL OR char_end >= 0),
    n_chars              INTEGER NOT NULL CHECK (n_chars >= 0),
    embedding            DOUBLE PRECISION[],
    embedding_dimensions INTEGER,
    CHECK (char_start IS NULL OR char_end IS NULL OR char_end >= char_start),
    CHECK (embedding_dimensions IS NULL OR embedding_dimensions > 0),
    CHECK (
        embedding IS NULL
        OR embedding_dimensions = cardinality(embedding)
    )
);

CREATE TABLE IF NOT EXISTS chunk_answer_nodes (
    id         TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    section    TEXT
);

CREATE TABLE IF NOT EXISTS area_nodes (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('buurt', 'wijk', 'gebied'))
);

