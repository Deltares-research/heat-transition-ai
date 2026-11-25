-- name: coverage_overview
-- description: How many municipalities have at least one linked programme document.
-- use when: Any aggregate is about to be reported. This is the denominator for every other number.
SELECT
    (SELECT count(*) FROM gemeente_nodes)                          AS gemeenten_totaal,
    (SELECT count(DISTINCT gemeente_code) FROM report_gemeente_edges) AS met_programma,
    round(
        100.0 * (SELECT count(DISTINCT gemeente_code) FROM report_gemeente_edges)
              / NULLIF((SELECT count(*) FROM gemeente_nodes), 0), 1
    )                                                               AS dekking_pct;


-- name: province_overview
-- description: Per-province breakdown of how many municipalities have a linked programme document.
-- use when: Asked about regional coverage, or to qualify a national number with its spread.
SELECT
    g.province,
    count(*)                                AS gemeenten_totaal,
    count(DISTINCT e.gemeente_code)         AS met_programma
FROM gemeente_nodes g
LEFT JOIN report_gemeente_edges e ON e.gemeente_code = g.code
GROUP BY g.province
ORDER BY g.province;


-- name: missing_programmes
-- description: Municipalities with no programme document linked at all.
-- use when: Asked which municipalities are missing, or before treating an absence as a negative answer rather than a gap in the corpus.
SELECT g.code, g.name, g.province, g.population
FROM gemeente_nodes g
WHERE NOT EXISTS (
    SELECT 1 FROM report_gemeente_edges e WHERE e.gemeente_code = g.code
)
ORDER BY g.province, g.name;


-- name: find_questions
-- description: Search the question registry by keyword across ids, English and Dutch text. Returns id, section, type and the allowed values for enum/status questions.
-- use when: You need a question_id and do not know it. Always call this (or list_questions) before guessing an id.
SELECT id, section, type, allowed, en, nl
FROM question
WHERE id ILIKE '%' || $term || '%'
   OR en ILIKE '%' || $term || '%'
   OR nl ILIKE '%' || $term || '%'
ORDER BY ord;


-- name: municipality_profile
-- description: CBS demographic profile for one municipality, plus how many programme documents reference it.
-- use when: Asked to describe or summarise a single municipality.
SELECT
    g.*,
    (SELECT count(*) FROM report_gemeente_edges e WHERE e.gemeente_code = g.code) AS n_documenten
FROM gemeente_nodes g
WHERE g.name ILIKE $gemeente;


-- name: reports_for_municipality
-- description: Programme documents linked to one municipality.
-- use when: Resolving which document(s) back a municipality's answers, or before citing a doc_id.
SELECT r.doc_id, r.title, r.language
FROM report_nodes r
JOIN report_gemeente_edges e ON e.doc_id = r.doc_id
JOIN gemeente_nodes g ON g.code = e.gemeente_code
WHERE g.name ILIKE $gemeente
ORDER BY r.title;


-- name: answers_for_question
-- description: Extracted answers to one question (by concept_id), across municipalities whose name matches a pattern.
-- use when: Asked what municipalities say about a specific topic. Pass '%' for gemeente to cover all municipalities.
SELECT
    g.name AS gemeente, g.province, ca.answer, ca.section,
    r.doc_id, r.title AS doc_title, c.heading_path
FROM chunk_answer_nodes ca
JOIN answer_chunk_edges ace ON ace.answer_id = ca.id
JOIN chunk_nodes c          ON c.id = ace.chunk_id
JOIN chunk_gemeente_edges cge ON cge.chunk_id = c.id
JOIN gemeente_nodes g        ON g.code = cge.gemeente_code
JOIN chunk_report_edges cre  ON cre.chunk_id = c.id
JOIN report_nodes r          ON r.doc_id = cre.doc_id
WHERE ca.concept_id = $question_id
  AND g.name ILIKE $gemeente
ORDER BY g.name;


-- name: search_quotes
-- description: Full-text search across programme chunk text.
-- use when: Asked about a term that has no question_id of its own. Returns matching passages, not a survey of every programme — say so when reporting the result. Pass '%' for gemeente to cover all municipalities.
SELECT
    g.name AS gemeente, r.doc_id, r.title AS doc_title, c.heading_path,
    left(c.text, 500) AS snippet
FROM chunk_nodes c
JOIN chunk_gemeente_edges cge ON cge.chunk_id = c.id
JOIN gemeente_nodes g         ON g.code = cge.gemeente_code
JOIN chunk_report_edges cre   ON cre.chunk_id = c.id
JOIN report_nodes r           ON r.doc_id = cre.doc_id
WHERE c.text ILIKE '%' || $term || '%'
  AND g.name ILIKE $gemeente
ORDER BY g.name
LIMIT 200;


-- name: shared_documents
-- description: Programme documents that cover more than one municipality.
-- use when: Before reporting any count across several municipalities. Municipalities sharing a document are not independent observations.
SELECT
    r.doc_id, r.title,
    count(*)                               AS n_gemeenten,
    array_agg(g.name ORDER BY g.name)      AS gemeenten
FROM report_gemeente_edges e
JOIN report_nodes r    ON r.doc_id = e.doc_id
JOIN gemeente_nodes g  ON g.code = e.gemeente_code
GROUP BY r.doc_id, r.title
HAVING count(*) > 1
ORDER BY n_gemeenten DESC;
