# HANDOFF: DocMatch Reliability Lab (round 2)

Status: BUILT_UNVERIFIED

- Branch: cc/webhook-rescue-lab. Round 1 commits: 3cedf49 (set B frozen), b875dd5 (code), e582bb1 (handoff). Round 2 changes are uncommitted in the working tree; the orchestrator commits them.
- Goal: proof lab for reliable invoice-to-PO matching, synthetic data, standard library only.
- Round 2: responds to two independent model reviews (Fable 17 findings, Codex 20). One row per finding in `REVIEW_ROUND2.md`: 31 accepted, 4 partial, 2 rejected.

## What exists
`src/docmatch/` (extract, match, validate, queue, pipeline, naive, util), 203 unittest tests (18 contracts against fixed and naive), `data/set_a.json` (tuned), `data/set_b.json` (byte-identical to its freeze commit), `data/set_c.json` (round 2: 39 single + 10 batch cases), `scripts/evaluate.py`, `scripts/mutate.py` (96 mutants + no-op control), README, `.github/workflows/test.yml` at the lab root, `evidence/`.

## Executed results (local, run by me)
- `python3 -B -m unittest discover -s tests`: 203 tests OK on Python 3.14.6; same on 3.12.13 and 3.9.6 (`evidence/`).
- `python3 -B scripts/mutate.py`: control ok; 96 killed, 0 survived, 0 crash (groups: orig 32, fable18 15, round2 49). Hand-picked mutants only.
- `python3 -B scripts/evaluate.py`: set C DocMatch 0/39 false auto, traps 25/25, correct 14/14, batch 0/20 false auto and 0 POs matched twice; set B (regression only) 0/36, 16/16, 19/20 (B-N07 now deliberately flagged); set A 0/20, 8/8, 12/12. Output identical on Python 3.9.
- `scripts/check-confidential.sh` re-run on the lab folder: see the orchestrator log.

## Known weaknesses
- The same author model wrote the rules, the code and all labels. Set C was written knowing the fixes (expected 100%, no discovery power). Set B is no longer clean because the code changed after it was measured. Set A is tuned.
- Mutants are hand-picked after the code and tests.
- In-memory state, single instance; no supplier IDs; partial billing against one PO always goes to a human; tiny-PO floor still allows a large relative over-bill.
- The CI workflow has never run (needs the lab as its own repository or a copy at the monorepo root with a working-directory).
- Text-only, regex, fixed layout family; no OCR.
- `scripts/check-confidential.sh` at the repository root still names the employer vocabulary in plain text (outside this folder, not changed).

## Next action
1. Have a human or a different model family label a set D from the README rules only, without seeing the code or sets A to C; report it separately as the first clean set.
2. Publish the lab as its own repository (or copy the workflow to the root) and link a real CI run for 3.9 to 3.13.
3. Add supplier IDs and an alias list, persisted state, and partial billing against a PO.
