-- How long closed requests took, per borough and creation month.
SELECT
    CAST(date_trunc('month', created_at) AS DATE)       AS month,
    borough,
    count(*)                                            AS closed_tickets,
    round(quantile_cont(response_hours, 0.5), 2)        AS median_response_hours,
    round(quantile_cont(response_hours, 0.9), 2)        AS p90_response_hours,
    round(avg(response_hours), 2)                       AS mean_response_hours
FROM silver
WHERE closed_at IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
