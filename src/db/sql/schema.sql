CREATE OR REPLACE TABLE gemeente (
    gemeente      TEXT PRIMARY KEY,
    gemeentecode  TEXT,
    province      TEXT,
    region        TEXT,
    number_users  INTEGER,
    url           TEXT,
    chars         INTEGER
);


CREATE OR REPLACE TABLE question (
    id       TEXT PRIMARY KEY,
    section  TEXT,
    type     TEXT NOT NULL CHECK (type IN ('split','count','bool','enum','status','text')),
    values   TEXT[],
    nl       TEXT NOT NULL,
    en       TEXT NOT NULL,
    ord      INTEGER NOT NULL
);


CREATE OR REPLACE TABLE response (
    gemeentecode  TEXT NOT NULL,
    question_id   TEXT NOT NULL,
    doc_id        TEXT NOT NULL,
    response      TEXT,
    modality      TEXT CHECK (modality IN (
                      'vastgesteld','voornemen','verkenning',
                      'expliciet_geen','onduidelijk','niet_vermeld')),
    ref           TEXT,
    page          INTEGER,
    note          TEXT,
    lang          TEXT,
    PRIMARY KEY (gemeentecode, question_id)
);