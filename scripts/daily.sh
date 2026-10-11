#!/usr/bin/env bash
# Local daily job: add today's pull, run the checks, write the recap files.
# Example crontab line (06:00 every day):  0 6 * * * /path/to/store-pc-health-check/scripts/daily.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
DAY=$(date +%F)
mkdir -p out
$PY -m pchealth today --date "$DAY"
$PY -m pchealth export --date "$DAY" --format xlsx --out "out/pc-health-recap-$DAY.xlsx"
$PY -m pchealth export --date "$DAY" --format csv --out "out/pc-health-recap-$DAY.csv"
$PY -m pchealth resume --date "$DAY" > "out/pc-health-resume-$DAY.txt"
