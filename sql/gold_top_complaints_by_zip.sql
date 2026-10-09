-- The five most common complaint types in every ZIP code, with their share of that ZIP's volume.
WITH counts AS (
    SELECT incident_zip, complaint_type, count(*) AS tickets
    FROM silver
    WHERE incident_zip IS NOT NULL
    GROUP BY 1, 2
),
ranked AS (
    SELECT
        *,
        row_number() OVER (PARTITION BY incident_zip ORDER BY tickets DESC, complaint_type) AS rank,
        sum(tickets) OVER (PARTITION BY incident_zip)                                       AS zip_tickets
    FROM counts
)
SELECT
    incident_zip,
    rank,
    complaint_type,
    tickets,
    round(tickets * 1.0 / zip_tickets, 4) AS share_of_zip
FROM ranked
WHERE rank <= 5
ORDER BY incident_zip, rank;
