-- Share of requests that took longer than the SLA, per agency and creation month.
-- A closed request breaches if it took longer than the SLA; a request that is still open
-- breaches if it has been open that long as of the newest request in the data (not "now",
-- so the table is reproducible). The SLA comes from the `sla_hours` session variable.
WITH as_of AS (
    SELECT max(created_at) AS ts FROM silver
),
flagged AS (
    SELECT
        s.agency,
        CAST(date_trunc('month', s.created_at) AS DATE) AS month,
        CASE
            WHEN s.closed_at IS NOT NULL THEN s.response_hours > getvariable('sla_hours')
            ELSE date_diff('second', s.created_at, a.ts) / 3600.0 > getvariable('sla_hours')
        END AS breached
    FROM silver AS s
    CROSS JOIN as_of AS a
)
SELECT
    agency,
    month,
    count(*)                                              AS tickets,
    count(*) FILTER (WHERE breached)                      AS breached_tickets,
    round(count(*) FILTER (WHERE breached) * 1.0 / count(*), 4) AS breach_rate,
    getvariable('sla_hours')::INTEGER                     AS sla_hours
FROM flagged
GROUP BY 1, 2
ORDER BY 1, 2;
