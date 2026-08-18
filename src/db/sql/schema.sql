CREATE TABLE IF NOT EXISTS gemeente (
    gemeente      TEXT PRIMARY KEY,
    gemeentecode  TEXT,
    province      TEXT,
    region        TEXT,
    number_users  INTEGER,
    url           TEXT,
    chars         INTEGER
);


CREATE TABLE IF NOT EXISTS question (
    id       TEXT PRIMARY KEY,
    section  TEXT,
    type     TEXT NOT NULL CHECK (type IN ('split','count','bool','enum','status','text')),
    values   TEXT[],
    nl       TEXT NOT NULL,
    en       TEXT NOT NULL,
    ord      INTEGER NOT NULL
);


CREATE TABLE IF NOT EXISTS response (
    gemeentecode  TEXT NOT NULL,
    question_id   TEXT NOT NULL,
    doc_id        TEXT NOT NULL,
    response        TEXT,
    value_num       DOUBLE,
    value_bool      BOOLEAN,
    value_qualifier TEXT,
    value_woningen  DOUBLE,
    value_utiliteit DOUBLE,
    modality      TEXT CHECK (modality IN (
                      'vastgesteld','voornemen','verkenning',
                      'expliciet_geen','onduidelijk','niet_vermeld')),
    ref           TEXT,
    page          INTEGER,
    note          TEXT,
    lang          TEXT,
    PRIMARY KEY (gemeentecode, question_id)
);


CREATE OR REPLACE VIEW answer AS
SELECT r.*, q.type AS question_type, q.section, q.en AS question_en, q.ord,
       g.gemeente, g.province, g.number_users
FROM response r
JOIN question q ON q.id = r.question_id
JOIN gemeente g USING (gemeentecode);

