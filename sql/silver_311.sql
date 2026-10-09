-- Bronze (raw strings) -> typed, standardised, de-duplicated requests.
-- Reads the `bronze` view; one row per unique_key, latest version wins.
-- Rows whose key is null/unparseable are kept (they cannot be de-duplicated) so the quality
-- gate can quarantine them instead of silently losing them.
WITH typed AS (
    SELECT
        TRY_CAST(unique_key AS BIGINT)                        AS unique_key,
        TRY_CAST(created_date AS TIMESTAMP)                   AS created_at,
        TRY_CAST(closed_date AS TIMESTAMP)                    AS closed_at,
        TRY_CAST(resolution_action_updated_date AS TIMESTAMP) AS updated_at,
        upper(trim(agency))                                   AS agency,
        trim(complaint_type)                                  AS complaint_type,
        trim(descriptor)                                      AS descriptor,
        trim(status)                                          AS status,
        CASE
            WHEN regexp_matches(trim(incident_zip), '^[0-9]{5}')
                THEN substr(trim(incident_zip), 1, 5)
        END                                                   AS incident_zip,
        CASE upper(trim(borough))
            WHEN ''          THEN NULL
            WHEN 'STATEN IS' THEN 'STATEN ISLAND'
            ELSE upper(trim(borough))
        END                                                   AS borough,
        TRY_CAST(latitude AS DOUBLE)                          AS latitude,
        TRY_CAST(longitude AS DOUBLE)                         AS longitude,
        ingest_date,
        _ingested_at,
        _batch_id
    FROM bronze
),
ranked AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY unique_key
            ORDER BY updated_at DESC NULLS LAST, _ingested_at DESC, _batch_id DESC
        ) AS version_rank
    FROM typed
)
SELECT
    unique_key,
    created_at,
    closed_at,
    updated_at,
    agency,
    complaint_type,
    descriptor,
    status,
    incident_zip,
    borough,
    latitude,
    longitude,
    CASE
        WHEN closed_at IS NOT NULL AND created_at IS NOT NULL
            THEN round(date_diff('second', created_at, closed_at) / 3600.0, 4)
    END                                                       AS response_hours,
    ingest_date
FROM ranked
WHERE version_rank = 1 OR unique_key IS NULL
ORDER BY unique_key NULLS LAST, created_at, complaint_type, descriptor;
