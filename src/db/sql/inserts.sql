-- name: insert_buurt_node
INSERT INTO buurt_nodes(
    name, code, province, population, households, avg_household_size,
    owned_pct, rented_pct, social_pct, multi_family_pct, non_residential,
    woz_valuation, land_area, total_area, pop_density, address_density
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (code) DO UPDATE SET
    name               = EXCLUDED.name,
    province           = EXCLUDED.province,
    population         = EXCLUDED.population,
    households         = EXCLUDED.households,
    avg_household_size = EXCLUDED.avg_household_size,
    owned_pct          = EXCLUDED.owned_pct,
    rented_pct         = EXCLUDED.rented_pct,
    social_pct         = EXCLUDED.social_pct,
    multi_family_pct   = EXCLUDED.multi_family_pct,
    non_residential    = EXCLUDED.non_residential,
    woz_valuation      = EXCLUDED.woz_valuation,
    land_area          = EXCLUDED.land_area,
    total_area         = EXCLUDED.total_area,
    pop_density        = EXCLUDED.pop_density,
    address_density    = EXCLUDED.address_density;

-- name: insert_wijk_node
INSERT INTO wijk_nodes(name, code) VALUES (%s, %s)
ON CONFLICT (code) DO NOTHING;

-- name: insert_gemeente_node
INSERT INTO gemeente_nodes(name, code) VALUES (%s, %s)
ON CONFLICT (code) DO NOTHING;

-- name: insert_buurt_wijk_edge
INSERT INTO buurt_wijk_edges (buurt_code, wijk_code)
VALUES (%s, %s)
ON CONFLICT DO NOTHING;

-- name: insert_wijk_gemeente_edge
INSERT INTO wijk_gemeente_edges (wijk_code, gemeente_code)
VALUES (%s, %s)
ON CONFLICT DO NOTHING;

-- name: insert_question
INSERT INTO question (id, section, type, allowed, nl, en, ord, origin)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING;

