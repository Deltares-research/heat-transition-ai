-- =====================================================================
-- queries.sql — warmteprogramma analysis library
--
-- Each query is a candidate MCP tool. Parameters are $named.
--
-- Rule that governs the whole file: a count is only meaningful with its
-- denominator. Every aggregate below reports how many municipalities it
-- looked at, and separates "the document says no" (expliciet_geen) from
-- "the document is silent" (niet_vermeld) from "we have no programme".
-- =====================================================================


-- name: coverage_overview
-- description: How many of the municipalities in the reference list have a programme in the corpus, and how many were analysed.
-- use when: Any aggregate is about to be reported. This is the denominator for every other number.
SELECT
    count(*)                                        AS gemeenten_totaal,
    count(*) FILTER (WHERE url IS NOT NULL)         AS met_programma,
    count(*) FILTER (WHERE url IS NULL)             AS zonder_programma,
    round(100.0 * count(*) FILTER (WHERE url IS NOT NULL) / count(*), 1) AS dekking_pct
FROM gemeente;


-- name: missing_programmes
-- description: Municipalities in the reference list with no programme in the corpus.
-- use when: Asked which municipalities are missing, or before claiming a national picture. Also the first place to look when a count seems too low.
SELECT gemeente, gemeentecode, province, number_users
FROM gemeente
WHERE url IS NULL
ORDER BY number_users DESC NULLS LAST;


-- name: answer_lookup
-- description: The answer to one question for one municipality, with the supporting quote and page.
-- use when: Asked what a specific municipality says about a specific topic. The most common single lookup.
SELECT g.gemeente, q.en AS question, r.response, r.modality,
       r.ref AS quote, r.page, r.note
FROM response r
JOIN gemeente g USING (gemeentecode)
JOIN question q ON q.id = r.question_id
WHERE g.gemeente ILIKE $gemeente
  AND r.question_id = $question_id;


-- name: municipality_profile
-- description: Everything extracted for one municipality, in questionnaire order.
-- use when: Asked to summarise or describe a single municipality's programme.
SELECT q.section, q.en AS question, r.response, r.modality, r.page
FROM response r
JOIN gemeente g USING (gemeentecode)
JOIN question q ON q.id = r.question_id
WHERE g.gemeente ILIKE $gemeente
ORDER BY q.ord;


-- name: answer_distribution
-- description: Distribution of answers to one question across all municipalities, with the silence categories kept separate.
-- use when: Asked "how many municipalities do X". Returns the shape of the whole corpus for that question, not just the positive cases.
SELECT
    coalesce(r.response, '(geen waarde)') AS answer,
    r.modality,
    count(*)                              AS n,
    string_agg(g.gemeente, ', ' ORDER BY g.gemeente) AS gemeenten
FROM response r
JOIN gemeente g USING (gemeentecode)
WHERE r.question_id = $question_id
GROUP BY 1, 2
ORDER BY n DESC;


-- name: who_answered
-- description: Municipalities whose answer to a question matches a pattern, with the quote.
-- use when: Asked which municipalities do a particular thing, and the evidence for it. Feed the result straight to a user — every row carries its source.
SELECT g.gemeente, g.province, g.number_users,
       r.response, r.modality, r.ref AS quote, r.page
FROM response r
JOIN gemeente g USING (gemeentecode)
WHERE r.question_id = $question_id
  AND r.response ILIKE $pattern
  AND r.modality NOT IN ('niet_vermeld', 'expliciet_geen')
ORDER BY g.number_users DESC NULLS LAST;


-- name: explicitly_excluded
-- description: Municipalities whose programme demonstrably rules something out, as opposed to not mentioning it.
-- use when: Asked who rejected a technique or instrument. Do not use who_answered for this — silence is not rejection.
SELECT g.gemeente, g.province, r.ref AS quote, r.page, r.note
FROM response r
JOIN gemeente g USING (gemeentecode)
WHERE r.question_id = $question_id
  AND r.modality = 'expliciet_geen'
ORDER BY g.gemeente;


-- name: not_stated
-- description: Municipalities whose programme is silent on a question.
-- use when: Asked where information is absent, or to show that a national aggregate cannot be built from a given parameter.
SELECT g.gemeente, g.province, g.number_users, r.note
FROM response r
JOIN gemeente g USING (gemeentecode)
WHERE r.question_id = $question_id
  AND r.modality = 'niet_vermeld'
ORDER BY g.number_users DESC NULLS LAST;


-- name: answerability_by_question
-- description: Per question, how often it was answered, explicitly denied, or left unaddressed.
-- use when: Asked which parts of the questionnaire the documents actually support. This is the evidence for saying a national total cannot be computed.
SELECT
    q.section,
    q.id,
    q.en AS question,
    count(r.gemeentecode)                                          AS beoordeeld,
    count(*) FILTER (WHERE r.modality NOT IN ('niet_vermeld','onduidelijk')
                       AND r.response IS NOT NULL)                 AS beantwoord,
    count(*) FILTER (WHERE r.modality = 'expliciet_geen')          AS expliciet_geen,
    count(*) FILTER (WHERE r.modality = 'niet_vermeld')            AS niet_vermeld,
    count(*) FILTER (WHERE r.modality = 'onduidelijk')             AS onduidelijk
FROM question q
LEFT JOIN response r ON r.question_id = q.id
GROUP BY q.section, q.id, q.en, q.ord
ORDER BY q.ord;


-- name: peer_finder
-- description: Municipalities structurally comparable to a given one (population band, province optional), with their answer to a chosen question.
-- use when: A municipality asks who is like them and what those places decided. Match on structure, not on text similarity.
WITH me AS (
    SELECT gemeentecode, number_users, province
    FROM gemeente WHERE gemeente ILIKE $gemeente
)
SELECT g.gemeente, g.province, g.number_users,
       r.response, r.modality, r.ref AS quote, r.page
FROM gemeente g
CROSS JOIN me
LEFT JOIN response r
       ON r.gemeentecode = g.gemeentecode AND r.question_id = $question_id
WHERE g.gemeentecode <> me.gemeentecode
  AND g.url IS NOT NULL
  AND g.number_users BETWEEN me.number_users * 0.6 AND me.number_users * 1.4
ORDER BY abs(g.number_users - me.number_users);


-- name: province_overview
-- description: All municipalities in a province with their answer to one question.
-- use when: A province or energy region asks what its municipalities are planning.
SELECT g.gemeente, g.number_users, g.url IS NOT NULL AS heeft_programma,
       r.response, r.modality, r.page
FROM gemeente g
LEFT JOIN response r
       ON r.gemeentecode = g.gemeentecode AND r.question_id = $question_id
WHERE g.province ILIKE $province
ORDER BY g.number_users DESC NULLS LAST;


-- name: cross_tab
-- description: Cross-tabulation of two questions: how answers to one relate to answers to the other.
-- use when: Asked whether two things co-occur — e.g. whether municipalities that rule out heat networks also lack a public heat utility.
SELECT a.response AS antwoord_a, b.response AS antwoord_b,
       count(*) AS n,
       string_agg(g.gemeente, ', ' ORDER BY g.gemeente) AS gemeenten
FROM response a
JOIN response b ON b.gemeentecode = a.gemeentecode
JOIN gemeente g ON g.gemeentecode = a.gemeentecode
WHERE a.question_id = $question_a
  AND b.question_id = $question_b
GROUP BY 1, 2
ORDER BY n DESC;


-- name: size_breakdown
-- description: Answers to one question grouped by municipality size band.
-- use when: Asked whether small and large municipalities differ — the usual first cut on any policy pattern.
SELECT
    CASE WHEN g.number_users <  20000 THEN '<20k'
         WHEN g.number_users <  50000 THEN '20-50k'
         WHEN g.number_users < 100000 THEN '50-100k'
         WHEN g.number_users < 250000 THEN '100-250k'
         ELSE '>250k' END                          AS grootteklasse,
    r.modality,
    count(*)                                       AS n
FROM gemeente g
JOIN response r ON r.gemeentecode = g.gemeentecode
WHERE r.question_id = $question_id
GROUP BY 1, 2
ORDER BY 1, n DESC;


-- name: region_members
-- description: Municipalities sharing a regional partnership, with their answers to one question.
-- use when: Checking whether a group's programmes align — and whether apparently independent answers actually come from one shared template.
SELECT g.region, g.gemeente, r.response, r.modality, r.doc_id
FROM gemeente g
JOIN response r ON r.gemeentecode = g.gemeentecode
WHERE g.region IS NOT NULL
  AND r.question_id = $question_id
ORDER BY g.region, g.gemeente;


-- name: shared_documents
-- description: Documents covering more than one municipality.
-- use when: Before reporting any count. Municipalities sharing a document are not independent observations, and the count should say so.
SELECT r.doc_id,
       count(DISTINCT r.gemeentecode)                    AS n_gemeenten,
       string_agg(DISTINCT g.gemeente, ', ')             AS gemeenten
FROM response r
JOIN gemeente g USING (gemeentecode)
GROUP BY r.doc_id
HAVING count(DISTINCT r.gemeentecode) > 1
ORDER BY n_gemeenten DESC;


-- name: search_quotes
-- description: Full-text search across the extracted source quotes.
-- use when: Asked about a term that has no question of its own. Returns evidence passages, not a survey — say so when reporting the result.
SELECT g.gemeente, r.question_id, r.ref AS quote, r.page
FROM response r
JOIN gemeente g USING (gemeentecode)
WHERE r.ref ILIKE '%' || $term || '%'
ORDER BY g.gemeente
LIMIT 50;


-- name: evidence_quality
-- description: Share of substantive answers that carry a supporting quote, per question.
-- use when: Judging whether a question's answers can be cited. A low quote rate means the answers are not defensible even where they look complete.
SELECT q.id, q.en AS question,
       count(*) FILTER (WHERE r.modality <> 'niet_vermeld')                        AS substantieel,
       count(*) FILTER (WHERE r.modality <> 'niet_vermeld' AND r.ref IS NOT NULL)  AS met_citaat,
       round(100.0 * count(*) FILTER (WHERE r.modality <> 'niet_vermeld' AND r.ref IS NOT NULL)
             / nullif(count(*) FILTER (WHERE r.modality <> 'niet_vermeld'), 0), 1) AS citaat_pct
FROM question q
JOIN response r ON r.question_id = q.id
GROUP BY q.id, q.en, q.ord
ORDER BY citaat_pct NULLS FIRST;


-- name: extraction_gaps
-- description: Municipality-question pairs with no response row at all.
-- use when: Diagnosing the pipeline. Distinguishes an extraction that never ran from one that ran and found nothing.
SELECT g.gemeente, q.id AS question_id
FROM gemeente g
CROSS JOIN question q
LEFT JOIN response r
       ON r.gemeentecode = g.gemeentecode AND r.question_id = q.id
WHERE g.url IS NOT NULL
  AND r.question_id IS NULL
ORDER BY g.gemeente, q.id;