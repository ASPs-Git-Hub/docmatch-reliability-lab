#!/bin/sh
# Downloads the two real-data inputs into DATA_DIR (default: ./_data, not committed). Data files only; nothing is executed.
# Polite: one request at a time, 3 second pause. Official hosts only: datasets-server.huggingface.co, data.rochdale.gov.uk.
set -eu
DATA_DIR="${1:-./_data}"
mkdir -p "$DATA_DIR/cord" "$DATA_DIR/rochdale"
for sp in test validation; do
  for off in 0 50; do
    curl -s "https://datasets-server.huggingface.co/rows?dataset=naver-clova-ix/cord-v2&config=default&split=$sp&offset=$off&length=50" -o "$DATA_DIR/cord/${sp}_$off.json"
    sleep 3
  done
done
curl -s https://huggingface.co/api/datasets/naver-clova-ix/cord-v2 -o "$DATA_DIR/cord/api_card.json"
for f in 2025_JAN_Spend 2025_FEB_Spend 2025_MAR_Spend 2025_APR_Spend 2025_MAY_Spend 2025_JUNE_SPEND; do
  curl -s -o "$DATA_DIR/rochdale/$f.csv" "https://data.rochdale.gov.uk/files/$f.csv"
  sleep 3
done
(cd "$DATA_DIR" && shasum -a 256 cord/*.json rochdale/*.csv)
