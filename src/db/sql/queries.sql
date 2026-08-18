-- =====================================================================
-- queries.sql — warmteprogramma analysis library
--
-- Each query is a candidate MCP tool. Parameters are $named.
--
-- Reads from the `answer` view (response + question + gemeente) unless a
-- query needs municipalities that have no response rows at all.
--
-- Typed columns:
--   response        verbatim answer, the audit trail
--   value_num       parsed number (ranges -> midpoint)
--   value_bool      parsed yes/no
--   value_qualifier what the parse discarded: circa | range | minimaal |
--                   maximaal | percentage | ongesplitst | niet_vermeld
--   value_woningen / value_utiliteit   for `type: split`
--
-- Three rules govern the whole file:
--   1. A count is only meaningful with its denominator.
--   2. `expliciet_geen` (the document says no) is not `niet_vermeld` (the
--      document is silent) is not "no programme at all".
--   3. Aggregates over value_num must never silently include hedged values —
--      hence the exact/estimate split in every numeric query.
--
-- These rules are why the queries exist. Equivalent SQL written ad hoc will
-- return numbers that look right and are not: a count without its
-- denominator, a sum that quietly includes parsed range midpoints, a total
-- that treats six municipalities on one shared programme as six independent
-- observations. If a question cannot be answered from these queries, that is
-- a gap to be filled here — not a reason to query the database directly.
-- =====================================================================


-- name: find_questions
-- description: Search the question registry by keyword across ids, English and Dutch text. Returns id, section, type and the allowed values for enum questions.
-- use when: You need a question_id and do not know it, or several related questions may exist (e.g. a status question and its explanatory counterpart). Always call this before guessing an id.
SELECT id, section, type, values, en, nl
FROM question
WHERE id ILIKE '%' || $term || '%'
   OR en ILIKE '%' || $term || '%'
   OR nl ILIKE '%' || $term || '%'
ORDER BY ord;


-- name: answers_for_questions
-- description: Answers to several questions at once for all municipalities, with values, modality and evidence. Pass a comma-separated list of question ids.
-- use when: A user's question spans more than one parameter — e.g. an instrument and the justification for it. One call instead of several, and the rows line up per municipality.
SELECT gemeente, province, number_users, question_id, question_en AS question,
       response, value_num, value_bool, value_qualifier,
       modality, ref AS quote, page, doc_id
FROM answer
WHERE list_contains(
        list_transform(string_split($question_ids, ','), x -> trim(x)),
        question_id)
ORDER BY gemeente, ord;


-- name: coverage_overview
-- description: How many of the municipalities in the reference list have a programme in the corpus.
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
-- description: The answer to one question for one municipality, with the parsed value, supporting quote and page.
-- use when: Asked what a specific municipality says about a specific topic. The most common single lookup.
SELECT gemeente, question_en AS question, response,
       value_num, value_bool, value_qualifier,
       modality, ref AS quote, page, note
FROM answer
WHERE gemeente ILIKE $gemeente
  AND question_id = $question_id;


-- name: municipality_profile
-- description: Everything extracted for one municipality, in questionnaire order.
-- use when: Asked to summarise or describe a single municipality's programme.
SELECT section, question_en AS question, response, value_num, value_bool,
       modality, page
FROM answer
WHERE gemeente ILIKE $gemeente
ORDER BY ord;


-- name: answer_distribution
-- description: Distribution of answers to one question across all municipalities, with the silence categories kept separate.
-- use when: Asked "how many municipalities do X". Returns the shape of the whole corpus for that question, not just the positive cases.
SELECT
    coalesce(response, '(geen waarde)')            AS answer,
    modality,
    count(*)                                       AS n,
    string_agg(gemeente, ', ' ORDER BY gemeente)   AS gemeenten
FROM answer
WHERE question_id = $question_id
GROUP BY 1, 2
ORDER BY n DESC;


-- name: modality_summary
-- description: One-line breakdown of a question: answered, explicitly ruled out, silent, and how many municipalities were assessed at all.
-- use when: The quickest honest answer to "how many municipalities do X". Report all four numbers, not just the first.
SELECT
    count(*)                                                  AS beoordeeld,
    count(*) FILTER (WHERE modality IN ('vastgesteld','voornemen','verkenning'))
                                                              AS bevestigd,
    count(*) FILTER (WHERE modality = 'expliciet_geen')       AS expliciet_geen,
    count(*) FILTER (WHERE modality = 'niet_vermeld')         AS niet_vermeld,
    count(*) FILTER (WHERE modality = 'onduidelijk')          AS onduidelijk,
    (SELECT count(*) FROM gemeente WHERE url IS NULL)         AS zonder_programma
FROM answer
WHERE question_id = $question_id;


-- name: numeric_summary
-- description: Sum, mean and range of the parsed numeric values for one question, with exact and estimate-inclusive totals reported separately.
-- use when: Asked to total or average a quantitative parameter. Always report `met_getal` against `beoordeeld` — most programmes do not quantify.
SELECT
    count(*)                                                   AS beoordeeld,
    count(value_num)                                           AS met_getal,
    count(value_num) FILTER (WHERE value_qualifier IS NULL)     AS exact,
    count(value_num) FILTER (WHERE value_qualifier IS NOT NULL) AS geschat,
    sum(value_num) FILTER (WHERE value_qualifier IS NULL)       AS som_exact,
    sum(value_num)                                             AS som_totaal,
    round(avg(value_num), 2)                                   AS gemiddelde,
    round(median(value_num), 2)                                AS mediaan,
    min(value_num)                                             AS minimum,
    max(value_num)                                             AS maximum
FROM answer
WHERE question_id = $question_id;


-- name: numeric_values
-- description: Every parsed numeric value for one question, per municipality, with the verbatim answer and qualifier.
-- use when: Backing up a total, or checking a suspicious aggregate. The `response` column shows what the number was parsed from.
SELECT gemeente, province, number_users,
       value_num, value_qualifier, response, modality, ref AS quote, page
FROM answer
WHERE question_id = $question_id
  AND value_num IS NOT NULL
ORDER BY value_num DESC;


-- name: numeric_by_group
-- description: Numeric values for one question, aggregated by province, region or size band.
-- use when: Asked whether a quantity differs across provinces, regions or municipality sizes.
SELECT
    CASE lower($group_by)
        WHEN 'province' THEN province
        WHEN 'region'   THEN coalesce(region, '(geen)')
        ELSE CASE WHEN number_users <  20000 THEN '<20k'
                  WHEN number_users <  50000 THEN '20-50k'
                  WHEN number_users < 100000 THEN '50-100k'
                  WHEN number_users < 250000 THEN '100-250k'
                  ELSE '>250k' END
    END                                                    AS groep,
    count(*)                                               AS beoordeeld,
    count(value_num)                                       AS met_getal,
    round(avg(value_num), 2)                               AS gemiddelde,
    sum(value_num) FILTER (WHERE value_qualifier IS NULL)  AS som_exact
FROM answer
WHERE question_id = $question_id
GROUP BY 1
ORDER BY gemiddelde DESC NULLS LAST;


-- name: who_answered
-- description: Municipalities whose answer to a question matches a pattern, with the quote.
-- use when: Asked which municipalities do a particular thing, and the evidence for it. Every row carries its source.
SELECT gemeente, province, number_users,
       response, value_num, value_bool, modality, ref AS quote, page
FROM answer
WHERE question_id = $question_id
  AND response ILIKE $pattern
  AND modality NOT IN ('niet_vermeld', 'expliciet_geen')
ORDER BY number_users DESC NULLS LAST;


-- name: who_confirmed
-- description: Municipalities that answered yes to a boolean question.
-- use when: The question's type is `bool`. Uses the parsed value rather than string matching, so phrasing does not affect the count.
SELECT gemeente, province, number_users, response, modality, ref AS quote, page
FROM answer
WHERE question_id = $question_id
  AND value_bool
ORDER BY number_users DESC NULLS LAST;


-- name: explicitly_excluded
-- description: Municipalities whose programme demonstrably rules something out, as opposed to not mentioning it.
-- use when: Asked who rejected a technique or instrument. Do not use who_answered for this — silence is not rejection.
SELECT gemeente, province, response, ref AS quote, page, note
FROM answer
WHERE question_id = $question_id
  AND modality = 'expliciet_geen'
ORDER BY gemeente;


-- name: not_stated
-- description: Municipalities whose programme is silent on a question.
-- use when: Asked where information is absent, or to show that a national aggregate cannot be built from a given parameter.
SELECT gemeente, province, number_users, note
FROM answer
WHERE question_id = $question_id
  AND modality = 'niet_vermeld'
ORDER BY number_users DESC NULLS LAST;


-- name: answerability_by_question
-- description: Per question, how often it was answered, explicitly denied, left unaddressed, and how often a usable number was extracted.
-- use when: Asked which parts of the questionnaire the documents actually support. This is the evidence for saying a national total cannot be computed.
SELECT
    q.section,
    q.id,
    q.type,
    q.en                                                           AS question,
    count(r.gemeentecode)                                          AS beoordeeld,
    count(*) FILTER (WHERE r.modality IN ('vastgesteld','voornemen','verkenning'))
                                                                   AS bevestigd,
    count(*) FILTER (WHERE r.modality = 'expliciet_geen')          AS expliciet_geen,
    count(*) FILTER (WHERE r.modality = 'niet_vermeld')            AS niet_vermeld,
    count(r.value_num)                                             AS met_getal
FROM question q
LEFT JOIN response r ON r.question_id = q.id
GROUP BY q.section, q.id, q.type, q.en, q.ord
ORDER BY q.ord;


-- name: peer_finder
-- description: Municipalities structurally comparable to a given one (population band), with their answer to a chosen question.
-- use when: A municipality asks who is like them and what those places decided. Match on structure, not on text similarity.
WITH me AS (
    SELECT gemeentecode, number_users, province
    FROM gemeente WHERE gemeente ILIKE $gemeente
)
SELECT g.gemeente, g.province, g.number_users,
       a.response, a.value_num, a.value_bool, a.modality, a.ref AS quote, a.page
FROM gemeente g
CROSS JOIN me
LEFT JOIN answer a
       ON a.gemeentecode = g.gemeentecode AND a.question_id = $question_id
WHERE g.gemeentecode <> me.gemeentecode
  AND g.url IS NOT NULL
  AND g.number_users BETWEEN me.number_users * 0.6 AND me.number_users * 1.4
ORDER BY abs(g.number_users - me.number_users);


-- name: province_overview
-- description: All municipalities in a province with their answer to one question, including those without a programme.
-- use when: A province or energy region asks what its municipalities are planning.
SELECT g.gemeente, g.number_users, g.url IS NOT NULL AS heeft_programma,
       a.response, a.value_num, a.modality, a.page
FROM gemeente g
LEFT JOIN answer a
       ON a.gemeentecode = g.gemeentecode AND a.question_id = $question_id
WHERE g.province ILIKE $province
ORDER BY g.number_users DESC NULLS LAST;


-- name: cross_tab
-- description: Cross-tabulation of two questions: how answers to one relate to answers to the other, by modality.
-- use when: Asked whether two things co-occur — e.g. whether municipalities that rule out heat networks also lack a public heat utility.
SELECT a.modality AS modality_a, coalesce(a.response, '(geen)') AS antwoord_a,
       b.modality AS modality_b, coalesce(b.response, '(geen)') AS antwoord_b,
       count(*) AS n,
       string_agg(a.gemeente, ', ' ORDER BY a.gemeente) AS gemeenten
FROM answer a
JOIN answer b ON b.gemeentecode = a.gemeentecode
WHERE a.question_id = $question_a
  AND b.question_id = $question_b
GROUP BY 1, 2, 3, 4
ORDER BY n DESC;


-- name: size_breakdown
-- description: Answers to one question grouped by municipality size band, split by modality.
-- use when: Asked whether small and large municipalities differ — the usual first cut on any policy pattern.
SELECT
    CASE WHEN number_users <  20000 THEN '<20k'
         WHEN number_users <  50000 THEN '20-50k'
         WHEN number_users < 100000 THEN '50-100k'
         WHEN number_users < 250000 THEN '100-250k'
         ELSE '>250k' END                          AS grootteklasse,
    modality,
    count(*)                                       AS n,
    round(avg(value_num), 1)                       AS gemiddelde_waarde
FROM answer
WHERE question_id = $question_id
GROUP BY 1, 2
ORDER BY 1, n DESC;


-- name: region_members
-- description: Municipalities sharing a regional partnership, with their answers to one question.
-- use when: Checking whether a group's programmes align — and whether apparently independent answers actually come from one shared template.
SELECT region, gemeente, response, value_num, modality, doc_id
FROM answer
WHERE region IS NOT NULL
  AND question_id = $question_id
ORDER BY region, gemeente;


-- name: shared_documents
-- description: Documents covering more than one municipality.
-- use when: Before reporting any count. Municipalities sharing a document are not independent observations, and the count should say so.
SELECT doc_id,
       count(DISTINCT gemeentecode)                AS n_gemeenten,
       string_agg(DISTINCT gemeente, ', ')         AS gemeenten
FROM answer
GROUP BY doc_id
HAVING count(DISTINCT gemeentecode) > 1
ORDER BY n_gemeenten DESC;


-- name: search_quotes
-- description: Full-text search across the extracted source quotes and answers.
-- use when: Asked about a term that has no question of its own. Returns evidence passages, not a survey — say so when reporting the result.
SELECT gemeente, question_id, question_en AS question, ref AS quote, page
FROM answer
WHERE ref ILIKE '%' || $term || '%'
   OR response ILIKE '%' || $term || '%'
ORDER BY gemeente
LIMIT 50;


-- name: evidence_quality
-- description: Share of substantive answers that carry a supporting quote, per question.
-- use when: Judging whether a question's answers can be cited. A low quote rate means the answers are not defensible even where they look complete.
SELECT question_id, question_en AS question,
       count(*) FILTER (WHERE modality <> 'niet_vermeld')                      AS substantieel,
       count(*) FILTER (WHERE modality <> 'niet_vermeld' AND ref IS NOT NULL)  AS met_citaat,
       round(100.0 * count(*) FILTER (WHERE modality <> 'niet_vermeld' AND ref IS NOT NULL)
             / nullif(count(*) FILTER (WHERE modality <> 'niet_vermeld'), 0), 1) AS citaat_pct
FROM answer
GROUP BY question_id, question_en, ord
ORDER BY citaat_pct NULLS FIRST;


-- name: parse_failures
-- description: Answers that carry text but from which no number could be parsed, for questions expected to be numeric.
-- use when: Diagnosing the parser, or explaining why a total covers fewer municipalities than expected.
SELECT gemeente, question_id, question_type, response, modality
FROM answer
WHERE question_type IN ('count', 'split')
  AND response IS NOT NULL
  AND value_num IS NULL
  AND modality <> 'niet_vermeld'
ORDER BY question_id, gemeente;


-- name: hedged_values
-- description: Numeric answers that were estimates, ranges or unsplit totals rather than exact figures.
-- use when: Qualifying a total. These values are in `som_totaal` but excluded from `som_exact`.
SELECT gemeente, question_id, response, value_num, value_qualifier, ref AS quote, page
FROM answer
WHERE value_qualifier IS NOT NULL
  AND value_qualifier <> 'niet_vermeld'
  AND ($question_id = '' OR question_id = $question_id)
ORDER BY question_id, gemeente;


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