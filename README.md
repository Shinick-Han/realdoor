---
title: RealDoor
emoji: 🚪
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Ready, not eligible — application readiness for renters
---

# RealDoor

RealDoor helps an affordable-housing applicant get their documents into a state a
person can review. It does not decide whether anyone qualifies.

**Ready, not eligible.**

> The AI extracts, explains, retrieves, calculates, and prepares. The renter confirms.
> A qualified human decides.

Hack-Nation #6 — Challenge 3 (RealPage).

---

## Try it

**Live:** https://shinick-realdoor.hf.space

Uploading a document, asking a question in your own words, the output gate returning
its own 500 — all of that needs the server, and that link is the server.

Three things to do once it loads, **in this order**. The page opens holding nothing —
upload is the front door, and the prepared files are a second offer on the same screen:

1. **Press "Open the example file for Mara North"** on step 1, under *"Or open a prepared
   example file"*. That loads `HH-001` in one click. Then **walk steps 1 → 2.** Step 2 offers the two corrections the
   pipeline actually ran as one-press buttons. Press *"Household size is 3, not 1"* and the
   before/after table moves the frozen threshold from $72,000 to $92,580 while the income
   figure stays put — a corrected value changing what it should change and nothing else.
   Press the other one and watch a correction get **recorded and then not used**, because
   the corrected figure no longer agrees with the hours and rate on the same document.
2. **Now change the file to `HH-004 — 4 documents`.** From step 2, press **"Change on
   step 1"** in the line under the heading, use the `Prepared example file` select, then
   go to step 5. `HH-001` has every document in order, so its
   checklist has nothing to show you. `HH-004` is missing an employment letter and has a
   gig statement dated to the month with no day — the system says so and abstains rather
   than inventing a date. `HH-005` has an employment letter that fell outside the 60-day
   window.
3. Open **"How this works, and how we tested it"** in the header. The refusals, the
   prompt-injection probe, the output gate and session deletion all live there.

All six households are available from the prepared-file select on step 1.

### The link above is a running server, so the gate can be tested on it

An earlier revision of this file described the public URL as a static build serving
bundled fixtures, and said the output gate could not be demonstrated on it. That is no
longer true and the paragraph is gone rather than quietly softened. The link runs the
FastAPI process: uploads are read by the extractor, questions are routed live, and the
output gate is in the request path. You can fire the gate at the hosted URL directly:

```bash
curl -i https://shinick-realdoor.hf.space/api/_gate_selftest
# HTTP/1.1 500
```

To run the same thing locally instead:

```bash
python -m uvicorn api.app:app --host 127.0.0.1 --port 8077
```

Then open <http://127.0.0.1:8077/>. FastAPI serves the UI at the same origin, the page
probes `api/health` and switches itself to live mode — the footer will read
`Data source: Live API at this origin`. Any port works; nothing hardcodes 8077.

Requires Python 3.12 and:

```bash
pip install pytest fastapi uvicorn python-multipart pdfplumber pypdfium2 numpy \
            jsonschema httpx pillow rapidocr-onnxruntime textstat
```

*(There is no root `requirements.txt`; this list is derived from the imports. Three of
them are easy to miss and each was: without `python-multipart` FastAPI raises at import
time — the upload route takes form data — which aborts collection before a single test
runs; the OCR fallback needs `rapidocr-onnxruntime`; and one readability measurement
skips itself without `textstat`. In a clean 3.12 venv this exact line reproduces
`1158 passed`. Drop `textstat` and it is `1157 passed, 1 skipped`, which is why it is
listed.)*

---

## The brief's six acceptance steps, and where each one is

Our walkthrough is six screens, but the numbering is **not** 1:1 with the brief. Step 5
of the brief spans two of our screens, and step 6 is deliberately not a renter step.

| Brief's acceptance step | Where it is in our UI |
| --- | --- |
| 1. Upload documents, show extraction evidence | Step 1 — "Check the values we read from your documents". Documents are **pre-loaded, not uploaded**; every value carries the box on the page it came from. |
| 2. Edit one field, show downstream values update | Step 2 — "Correct a value we read wrong" |
| 3. Ask a rule question, show an authoritative citation | Step 3 — "Ask what a housing rule says" |
| 4. Deterministic calculation with effective dates | Step 4 — "See how your yearly income figure was worked out" |
| 5. Identify missing or expired items, export a packet | Steps 5 and 6 — "See what is missing or out of date", then "Check what we found, then take your packet" |
| 6. Run the refusal, prompt-injection and session-deletion tests | **"How this works" page**, captioned *"Not part of the renter's six steps"* — a renter should not have to walk through our safety demos to get their documents ready. |

The API endpoints do map 1:1 to the brief's six steps; the screens do not.

---

## What we did not build

Stated first, because this is the point of the product.

- **Upload takes one document at a time, and it is not persisted.** Reading a PDF needs
  the extractor, which is Python, so upload works wherever the server runs — including the
  public URL, where a judge can bring their own PDF. The document is held in that session's
  memory, never written to disk and never joined to the household's file. (An earlier
  revision of this line said upload was switched off on the public URL. That was true of a
  static build we no longer serve.)
- **One citation in seven could not be re-checked.** Of the 11 rules in the corpus, 7 cite
  an outside authority over https and 4 are the challenge pack's own frozen convention,
  whose source is a file in this repository — re-fetching those would be us reading back
  what we wrote, so they are marked out of scope rather than counted as passes. Of the 7,
  six were re-fetched and the specific figures and sentences we quote were found again at
  the locator we cite; `uscode.house.gov` did not answer and is reported as not checked,
  never as checked and fine. The scorecard prints the time of each check, and the screen
  makes no network request of its own — it reads the artefact left by
  `python eval/citation_recheck.py`, so the demo does not depend on the network and judges
  do not fan requests out to HUD.
- **The stretch goal ("Discover") is not implemented.** No part of it shipped.
- **axe-core ran at one viewport width only** (1280×900). Reflow is checked separately
  at five narrow widths. See the honesty note under Measurements.
- **Identifier redaction is shape-based and incomplete.** We substitute recognisable
  identifier shapes before sending anything outward. We do not claim it is exhaustive,
  and the scorecard publishes the count of machine identifiers still visible on screen
  (72) rather than hiding it.
- **The adversarial pack is 12 distinct hostile inputs, each present twice.** 24/24 is
  evidence, not proof.

---

## Measured

Every number below is reproduced by the commands in *Reproducing the checks*.

```
1158 automated tests pass

Extraction        159/159 exact · 0 wrong · 0 abstained · 0 missed  (the organizer's pack)
Bounding boxes    IoU > 0.5 on 159/159 · mean 0.9677  (anchored to the text baseline)
Adversarial       24/24, 0 must_not violations
                  control set: 24/24 safe responses pass, 24/24 unsafe responses caught
Rule questions    36/36 correct · 0 wrong · 0 abstained  (pack qa_gold)
Calculation       90/90 arithmetic cases agree with the organizer's own calculate.py,
                  imported not copied (80 annualization + 10 threshold comparisons)
Schema            6/6 households validate against pack submission.schema.json
axe-core          0 violations across 4 origins x 8 screens — at 1280px only
Keyboard journey  28/28
Reflow            40/40 at 320 / 360 / 390 / 412 / 768 px
Live API check    11/11
Citations         6/7 outside-authority citations re-fetched and matched; 1 unreachable
                  (4 of the 11 rules are the pack's own convention — out of scope)
```

The test count grows as tests are added; `python -m pytest` is the authority, not this
number.

**On accessibility, precisely:** 0 axe violations at 1280px, and no reflow failure at
five narrow widths. That is not the same as WCAG 2.2 AA conformance and we do not claim
it. Reflow is one success criterion; 1.4.4 and 1.3.4 were not measured. Over `file://`
Chromium blocks axe from reading the stylesheet, so colour contrast comes back
*incomplete* — which means axe declined to judge, not that a check passed.

---

## How it is built

- **No language model is on the judgment path.** Extraction, rules and arithmetic are
  deterministic end to end.
- **An intent classifier sits at the entrance.** It returns exactly one label from a
  closed set of 21 and cannot write a sentence. If the deterministic router does not
  independently confirm the label, it is discarded. Adversarial inputs and scored
  questions never reach the classifier at all — tests hold its call counter at 0.
- **Recognisable identifier shapes are substituted before anything is sent outward.**
  Not exhaustive, and not claimed to be.
- **An output gate inspects every JSON response leaving the server.** If a verdict is
  present, it blocks our own response and returns HTTP 500. We ship an endpoint whose
  only purpose is to demonstrate this against ourselves:

  ```bash
  curl -i http://127.0.0.1:8077/api/_gate_selftest
  # HTTP/1.1 500
  # {"error":"decision_gate_blocked_response",
  #  "detail":"This service must never approve, deny, score, rank or prioritise. ...",
  #  "violations":["banned key `eligible` at $.eligible","banned key `score` at $.score"]}
  ```

  If that endpoint ever succeeds, we have failed.
- **Sessions are held in memory only.** There is no database, so "ephemeral processing"
  is a structural fact rather than a promise. Deleting a session makes follow-up requests
  404.

---

## Repository layout

| Path | Contents |
| --- | --- |
| `core/` | Deterministic PDF text-layer extraction and geometry — boxes come from the PDF, never from a model. |
| `logic/` | Pure, model-free logic: income annualisation, thresholds, checklists, readiness, abstention, rule answering. |
| `api/` | The FastAPI service — routes, the output-gate middleware, in-memory session store, question routing, redaction, scorecard. |
| `ui/` | Zero-build vanilla HTML/CSS/JS front end in `dist/`, real pipeline output in `fixtures/`, and the Playwright/axe measurement tools in `tools/`. |
| `eval/` | Scoring and adversarial harnesses run against the pack, plus the static no-decision guard. |
| `pack/` | The organizer's starter pack, unmodified — synthetic documents, gold data, rule corpus, and the reference calculator. |
| `ocr/` | OCR fallback for the image-only pack documents, emitting the same field objects. |
| `scripts/` | CLI runners: pipeline, fixture export, submission export, and `verify.py`. |
| `contracts/` | Frozen agreements between work streams — response shapes, frozen constants, UI mandate. |

---

## Reproducing the checks

Run from the repository root. None of these need a network connection or an API key.

```bash
# the full suite
python -m pytest

# 159/159 extraction, IoU mean 0.9677, adversarial 24/24, qa_gold 36/36
# (one command, roughly a minute — this is the one to run if you run only one)
python scripts/verify.py

# the adversarial control set: 24/24 safe pass, 24/24 unsafe caught
python eval/run_adversarial.py --demo

# the organizer-agreement file: 140 tests, of which the 90 above are the direct
# arithmetic comparisons against their calculate.py. The other 50 check our output
# against the pack's gold data (thresholds, readiness, review reasons) rather than
# against their calculator, so they are not part of the 90/90.
python -m pytest logic/test_pack_agreement.py

# 6/6 households validate against the pack schema (read-only unless --write)
python scripts/export_submission.py
```

Browser checks need Node and Playwright:

```bash
cd ui/tools && npm install && npx playwright install chromium && cd ../..

node ui/tools/keyboard-journey.mjs    # 28/28
node ui/tools/reflow-check.mjs        # 40/40 at 320/360/390/412/768
node ui/tools/axe-scan.mjs            # 0 violations; rewrites ui/axe-report.json

# 11/11 — needs the server running; pass the URL, it defaults to port 8000
node ui/tools/live-check.mjs http://127.0.0.1:8077
```

`scripts/verify.py` exits non-zero if anything regresses.

---

## Data

Every document, household and identity in `pack/` is **synthetic** and supplied by the
organizer: 24 documents across 6 households. **No real applicants, and no real people.**
The pack's own boundary is in `pack/governance/DATA_USE_AND_SAFETY.md`, including the
line we built the product around: *do not make approval, denial, eligibility,
prioritization, or fair-housing decisions.*

## License

MIT — see [LICENSE](LICENSE).
