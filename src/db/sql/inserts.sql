-- name: insert_buurt_node
INSERT INTO buurt_nodes(
    name, code, province, population, households, avg_household_size,
    dwellings, owned_pct, rented_pct, social_pct, multi_family_pct,
    non_residential, woz_valuation, land_area, total_area, pop_density,
    address_density, urbanity, peiljaar
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (code) DO UPDATE SET
    name               = EXCLUDED.name,
    province           = EXCLUDED.province,
    population         = EXCLUDED.population,
    households         = EXCLUDED.households,
    avg_household_size = EXCLUDED.avg_household_size,
    dwellings          = EXCLUDED.dwellings,
    owned_pct          = EXCLUDED.owned_pct,
    rented_pct         = EXCLUDED.rented_pct,
    social_pct         = EXCLUDED.social_pct,
    multi_family_pct   = EXCLUDED.multi_family_pct,
    non_residential    = EXCLUDED.non_residential,
    woz_valuation      = EXCLUDED.woz_valuation,
    land_area          = EXCLUDED.land_area,
    total_area         = EXCLUDED.total_area,
    pop_density        = EXCLUDED.pop_density,
    address_density    = EXCLUDED.address_density,
    urbanity           = EXCLUDED.urbanity,
    peiljaar            = EXCLUDED.peiljaar;

-- name: insert_wijk_node
INSERT INTO wijk_nodes(name, code) VALUES (%s, %s)
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name;

-- name: insert_gemeente_node
INSERT INTO gemeente_nodes(name, code, province) VALUES (%s, %s, %s)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    province = COALESCE(EXCLUDED.province, gemeente_nodes.province);

-- name: insert_gemeente_reference
INSERT INTO gemeente_nodes(name, code, dimension_group_id, peiljaar)
VALUES (%s, %s, %s, %s)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    dimension_group_id = EXCLUDED.dimension_group_id,
    peiljaar = EXCLUDED.peiljaar;

-- name: insert_buurt_wijk_edge
INSERT INTO buurt_wijk_edges (buurt_code, wijk_code)
VALUES (%s, %s)
ON CONFLICT (buurt_code) DO UPDATE SET wijk_code = EXCLUDED.wijk_code;

-- name: insert_wijk_gemeente_edge
INSERT INTO wijk_gemeente_edges (wijk_code, gemeente_code)
VALUES (%s, %s)
ON CONFLICT (wijk_code) DO UPDATE SET gemeente_code = EXCLUDED.gemeente_code;

-- name: delete_stale_buurt_nodes
DELETE FROM buurt_nodes
WHERE NOT (code = ANY(%s));

-- name: delete_stale_wijk_nodes
DELETE FROM wijk_nodes
WHERE NOT (code = ANY(%s));

-- name: delete_stale_gemeente_nodes
DELETE FROM gemeente_nodes
WHERE NOT (code = ANY(%s));

-- name: refresh_cbs_aggregates
SELECT refresh_cbs_aggregates();

-- name: insert_question
INSERT INTO question (id, section, type, allowed, nl, en, ord, origin)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING;

-- name: insert_report_node
INSERT INTO report_nodes (doc_id, title, language)
VALUES (%s, %s, %s)
ON CONFLICT (doc_id) DO UPDATE SET
    title = EXCLUDED.title,
    language = EXCLUDED.language;

-- name: insert_chunk_node
INSERT INTO chunk_nodes (
    id, chunk_index, heading_path, text, char_start, char_end, n_chars,
    embedding, embedding_dimensions
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    chunk_index = EXCLUDED.chunk_index,
    heading_path = EXCLUDED.heading_path,
    text = EXCLUDED.text,
    char_start = EXCLUDED.char_start,
    char_end = EXCLUDED.char_end,
    n_chars = EXCLUDED.n_chars,
    embedding = EXCLUDED.embedding,
    embedding_dimensions = EXCLUDED.embedding_dimensions;

-- name: insert_chunk_answer_node
INSERT INTO chunk_answer_nodes (id, concept_id, question, answer, section)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    concept_id = EXCLUDED.concept_id,
    question = EXCLUDED.question,
    answer = EXCLUDED.answer,
    section = EXCLUDED.section;

-- name: insert_area_node
INSERT INTO area_nodes (id, name, type)
VALUES (%s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    type = EXCLUDED.type;

-- name: insert_report_gemeente_edge
INSERT INTO report_gemeente_edges (doc_id, gemeente_code)
VALUES (%s, %s)
ON CONFLICT (doc_id, gemeente_code) DO NOTHING;

-- name: insert_chunk_report_edge
INSERT INTO chunk_report_edges (chunk_id, doc_id)
VALUES (%s, %s)
ON CONFLICT (chunk_id) DO UPDATE SET doc_id = EXCLUDED.doc_id;

-- name: insert_chunk_gemeente_edge
INSERT INTO chunk_gemeente_edges (chunk_id, gemeente_code)
VALUES (%s, %s)
ON CONFLICT (chunk_id, gemeente_code) DO NOTHING;

-- name: insert_answer_chunk_edge
INSERT INTO answer_chunk_edges (answer_id, chunk_id)
VALUES (%s, %s)
ON CONFLICT (answer_id) DO UPDATE SET chunk_id = EXCLUDED.chunk_id;

-- name: insert_chunk_area_edge
INSERT INTO chunk_area_edges (chunk_id, area_id)
VALUES (%s, %s)
ON CONFLICT (chunk_id, area_id) DO NOTHING;

