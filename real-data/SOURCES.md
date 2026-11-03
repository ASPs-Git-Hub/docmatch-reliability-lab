# Sources

All files were fetched on 2026-11-03 from the official host, one request at a time with a 3 second pause, no login. Nothing downloaded was executed. Hashes are in `SHA256.txt`. The big files are not committed: `fetch_data.sh` downloads them again.

| Data | URL | Licence | Size | Used for |
|---|---|---|---|---|
| CORD-v2 receipts, splits `test` and `validation` (200 receipts), as JSON rows | https://datasets-server.huggingface.co/rows?dataset=naver-clova-ix/cord-v2&config=default&split=test (and `validation`), offsets 0 and 50, length 50 | CC BY 4.0. Hugging Face card and API say `cc-by-4.0`; upstream repo https://github.com/clovaai/cord reports CC-BY-4.0 through the GitHub API | 4 files, about 1.3 MB in all | Part A |
| CORD-v2 dataset card (licence check) | https://huggingface.co/api/datasets/naver-clova-ix/cord-v2 | n/a | 1 KB | Licence record |
| Rochdale Borough Council "Council Spending over £500", January to June 2025 | https://data.rochdale.gov.uk/files/2025_JAN_Spend.csv, `2025_FEB_Spend.csv`, `2025_MAR_Spend.csv`, `2025_APR_Spend.csv`, `2025_MAY_Spend.csv`, `2025_JUNE_SPEND.csv` | UK Open Government Licence (data.gov.uk record https://ckan.publishing.service.gov.uk/api/3/action/package_show?id=council-spending-over-500 gives `license_id: uk-ogl`, "UK Open Government Licence (OGL)"). OGL text: https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/ | 2.3 MB to 6.2 MB each, 20.6 MB in all, 154,735 lines | Part B |

Attribution: CORD is by NAVER Corp. (Park et al., "CORD: A Consolidated Receipt Dataset for Post-OCR Parsing", 2019). Rochdale data contains public sector information licensed under the Open Government Licence v3.0.

Licence verification, honestly: for CORD I read the card and the API field, and the GitHub repository field. I did not find a separate licence file. For Rochdale I relied on the data.gov.uk catalogue record, which names the OGL; I did not find the licence wording on the council's own page. Gateshead Council was tried first and skipped: its files are behind a bot challenge (HTTP 403) and I did not bypass it.

Frozen sample committed: `samples/cord_texts_frozen.jsonl` (44 KB, the 193 scored receipts' rebuilt text and labels, CC BY 4.0 with the attribution above) and `samples/handcheck_labels_masked.json` (9 KB, hand-check labels with non-company names masked). No Rochdale lines are committed.

Personal data: Rochdale already replaces payments to individuals with "REDACTED - Personal Data"; 45,324 such lines were left out. Outputs show a supplier name only when it contains a company word, otherwise only the first letter and length.
