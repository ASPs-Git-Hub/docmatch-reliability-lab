#!/bin/sh
# v2 development slice: rows the Hugging Face datasets-server returns from its `first-rows` endpoint for the CORD-v2 `train` split.
# (The `rows` endpoint refuses train with "scan size limit exceeded"; `first-rows` works and returns the first rows of the split.)
# Used ONLY to tune rules (PROTOCOL-v2.md). Same official host as fetch_data.sh. Data files only; nothing is executed.
set -eu
DATA_DIR="${1:-./_data}"
mkdir -p "$DATA_DIR/cord_dev"
curl -s "https://datasets-server.huggingface.co/first-rows?dataset=naver-clova-ix/cord-v2&config=default&split=train" -o "$DATA_DIR/cord_dev/train_first_rows.json"
(cd "$DATA_DIR" && shasum -a 256 cord_dev/train_first_rows.json)
