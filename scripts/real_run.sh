#!/usr/bin/env bash
# One polite real-API run: the first 10,000 requests of each of five months (50,000 rows in total),
# so the monthly gold tables span several months without pulling the whole dataset.
set -euo pipefail

DATA_DIR="${1:-data}"

for month in 04 05 06 07 08; do
  next=$(printf '%02d' $((10#$month + 1)))
  echo "== 2026-${month} =="
  conduit run --source api --data-dir "$DATA_DIR" \
    --since "2026-${month}-01" --until "2026-${next}-01" --limit 10000
done
