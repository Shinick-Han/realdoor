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

The renter flow is **two pages** — the owner's call, after the six-step version proved
too big an obstacle: page 1 is the renter's file, page 2 is readiness and handoff, and
the judges' annex sits behind the header link. Three things to do once it loads, **in
this order**. The page opens holding nothing — upload is the front door, and the
prepared files are a second offer on the same screen:

1. **Press "Open the example file for Mara North"** on page 1, under *"Or open a prepared
   example file"*. That loads `HH-001` in one click. Then **fix a value on its row**:
   on the application summary, press *"This is wrong — fix it"* on `household_size`,
   type `3`, and Save. The before/after summary appears **in place, under that
   document's table**: the frozen threshold moves from $72,000 to $92,580 while the
   income figure stays put — a corrected value changing what it should change and
   nothing else. (Offline, the same two recorded corrections are one-press buttons
   above the table.) Fix `gross_pay` on the newer pay stub to `2500` and watch a
   correction get **recorded and then not used**, because the corrected figure no
   longer agrees with the hours and rate on the same document.
2. **Now change the file to `HH-004 — 4 documents`** with the `Prepared example file`
   select, then press **Continue to page 2**. `HH-001` has every document in order, so
   its checklist has nothing to show you. `HH-004` is missing an employment letter and
   has a gig statement dated to the month with no day — the system says so and abstains
   rather than inventing a date. `HH-005` has an employment letter that fell outside
   the 60-day window. Page 2 reads top to bottom: the calculation, the checklist, then
   the tally and the packet, with jump links under the heading.
3. Open **"How this works, and how we tested it"** in the header. The refusals, the
   prompt-injection probe, the output gate and session deletion all live there. The
   recorded rule questions — the eligibility refusal included — are under the ask box
   pinned to the foot of every page, in the "Recorded questions" list.

All six households carry a bundled report, so the prepared-file select on page 1 renders any of them offline.

**The public URL is the full server; only the offline copy withholds anything.** Earlier
versions of this README described the hosted page as a static build that replayed
recorded pipeline output, could not take an upload, and reported the output gate as
"Not run — there is no server to test". That was true of the old static deployment and
is no longer true of this one: the link above runs the FastAPI process itself
(re-checked 2026-07-20 — `/api/health` answers live and `/api/_gate_selftest` returns
its 500 from the running gate). The withholding behaviour still exists in exactly one
place: opening `ui/dist/index.html` from disk with no server. In that offline mode the
page runs on bundled fixtures; the inline corrections and the ask box replay recordings
made in an `HH-001` session, so on any other household those controls switch off and
say which household they belong to rather than showing `HH-001`'s figures under another
name, and the gate panel reports there is no server to test rather than replaying a
recording and calling it live. To see the gate withhold a response on your own machine,
run the server:

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

*(The root `requirements.txt` pins the runtime dependencies of the deployed server
image; the line above is the wider development set the test suite needs. An earlier
version of this note said there was no root `requirements.txt` — it has since been
added — and promised `880 passed`; the suite has grown well past that and `python -m
pytest` is the authority, with the last measured count under **Measured** below. Three
packages are easy to miss and each was: without `python-multipart` FastAPI raises at
import time — the upload route takes form data — which aborts collection before a
single test runs; the OCR fallback needs `rapidocr-onnxruntime`; and one readability
measurement skips itself without `textstat` rather than failing, which is why it is
listed.)*

---

## The brief's six acceptance steps, and where each one is

Our walkthrough is **two pages** — it used to be six step-screens, and the owner ended
that: six screens were too big an obstacle. The mapping is **not** 1:1 with the brief,
and it never was; every acceptance step remains individually demonstrable.

| Brief's acceptance step | Where it is in our UI |
| --- | --- |
| 1. Upload documents, show extraction evidence | **Page 1** — "Check the values we read from your documents". Upload is the front door, a prepared example is one press, and every value carries the box on the page it came from. The session's uploads together form a file both pages can walk. |
| 2. Edit one field, show downstream values update | **Page 1** — "This is wrong — fix it" opens an editor on the row itself; when the correction commits, the before/after summary (the recomputed figure, the threshold move, or the recorded-but-not-used explanation) appears in place under that document's table. |
| 3. Ask a rule question, show an authoritative citation | **The ask box pinned to every page.** Answers carry rule id, authority, effective date and source; the recorded questions, the eligibility refusal included, are in the "Recorded questions" list under the same box. |
| 4. Deterministic calculation with effective dates | **Page 2, "How your yearly figure was worked out"** — the answer leads, the full working (inputs, formulas, citations) is one fold below, and a figure that could not be computed stays unfolded. |
| 5. Identify missing or expired items, export a packet | **Page 2** — "What is missing or out of date", then "Check what we found, then take your packet", top to bottom on the same page with jump links. |
| 6. Run the refusal, prompt-injection and session-deletion tests | **"How this works" page**, captioned *"Not part of the renter's walkthrough"* — a renter should not have to walk through our safety demos to get their documents ready. |

The API endpoints do map 1:1 to the brief's six steps; the pages do not.

---

## What we did not build

Stated first, because this is the point of the product.

- **Upload needs a running server — and the public URL is one.** Reading a PDF needs the
  extractor, which is Python, so the offline `file://` copy shows the upload panel on
  page 1 switched off rather than hidden, saying what to run. On the hosted server and
  on a local one, the same panel takes one synthetic document, held in that session's
  memory, never written to disk and never joined to the household's file. (An earlier
  version of this bullet said a judge could not bring their own PDF to the public URL;
  that was written when the public URL was a static build, and is no longer true.) The
  24 pack documents are pre-loaded either way.
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
  (3, from re-running `node ui/tools/screen-scan.mjs` on 2026-07-21 against the two-page
  layout; the 2026-07-20 six-screen count was 21, and an earlier draft said 72. Part of
  the latest fall is real rework and part is the fold rule: page 2's working now sits
  behind disclosures, and text inside a collapsed disclosure is not "visible" — the
  method note in `ui/screen-scan.json` states this) rather than hiding it.
- **The adversarial pack is 12 distinct hostile inputs, each present twice.** 24/24 is
  evidence, not proof.

---

## Measured

Every number below is reproduced by the commands in *Reproducing the checks*, and was
last re-measured 2026-07-20. Pack numbers and hold-out numbers are different kinds of
number and are labelled as such — a pack number is measured on inputs this system was
built against; a hold-out number is not.

```
1490 automated tests pass  (python -m pytest -q, 2026-07-21)

— on the pack (inputs we built against) —
Extraction        159/159 exact · 0 wrong · 0 abstained · 0 missed
Bounding boxes    IoU > 0.5 on 159/159 · mean 0.9677  (anchored to the text baseline)
Rule questions    36/36 correct · 0 wrong · 0 abstained  (pack qa_gold — the pack's own
                  phrasing, which the router was developed against: a fit score)
Adversarial       24/24, 0 must_not violations (12 distinct hostile inputs, each twice)
                  controls: 24/24 compliant responses pass; unsafe_responder caught on
                  all 24 runs (12 distinct unsafe responses — the pack reuses inputs);
                  eval/control_set.py probes 42 distinct unsafe responses — 24 blatant
                  all caught, 18 evasive with 5 caught and 13 documented misses
Calculation       90/90 arithmetic cases agree with the organizer's own calculate.py,
                  imported not copied (80 annualization + 10 threshold comparisons)
Schema            6/6 households validate against pack submission.schema.json

— on hold-outs (inputs we did not choose) —
Question phrasing 44 questions: deterministic router alone 6 correct · 38 abstained ·
                  0 wrong; with the intent classifier 36 correct · 7 abstained ·
                  1 wrong (classifier column needs an OpenAI key)
Label wording     own 26 docs 93.1% tables-only and 93.1% with the label model (gain 0);
                  hold-out captions 70.6% tables-only · 79.4% with the model · 0 wrong
                  in every cell, against the correct counts just stated
Real layouts      external six PDFs: 14/44 correct · 30 abstained · 0 wrong (default);
                  18/44 · 26 · 0 with REALDOOR_COLUMNS=1 REALDOOR_ARITHMETIC=1 (the
                  deployed server's flags). Confirm set, 14 docs: 4/126 correct ·
                  122 abstained · 0 wrong (6/120/0 with the flags). Low correct, zero
                  wrong — read together: the guard holds by abstaining on pages the
                  extractor mostly cannot read

— interface —
axe-core          0 violations across 4 origins x 6 screen states — at 1280px only
                  (2 pages + editor/downstream/unfolded states + the judges' page)
Keyboard journey  36/36 on the two-page layout (was 31/31 on the six-step layout)
Reflow            15/15 — 5 widths (320/360/390/412/768 px) x 3 screens (was 35/35 x 7;
                  the same content, absorbed into fewer screens)
Live API check    11/11 against a local server; health, upload and the gate's 500 also
                  re-checked against the public URL on 2026-07-20
Page height       merged pages, default state, HH-001 open: page 1 = 5,129px at 1280px
                  (old step 1: 5,156px) · page 2 = 2,721px (tallest absorbed screen,
                  old step 4: 4,206px; the three absorbed screens summed to 8,659px).
                  At 390px: page 1 = 8,486px (old 8,534) · page 2 = 4,390px (old step 4
                  7,069; sum 14,896). Summary-first: what is settled folds, what is
                  open never does
Citations         6/7 outside-authority citations re-fetched and matched (2026-07-19);
                  1 could not be re-fetched — uscode.house.gov did not answer in 45 s,
                  reported as not checked, never as checked and fine
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

- **No language model is on the judgment path.** Rules and arithmetic are deterministic
  end to end. In extraction, a model may *nominate* a field name for a caption both
  lookup tables miss — both server extraction paths wire that seam in — but the value
  still has to be found by the same geometry and parse as every other field, a
  model-named field is marked and carries low certainty, and with no API key the layer
  stands down to tables-only.
- **An intent classifier sits at the entrance.** It returns exactly one label from a
  closed set of 21 and cannot write a sentence. If the deterministic router does not
  independently confirm the label, it is discarded — a confirmation that is a filter,
  not a proof: on the 44-question phrasing hold-out it let one wrong label through
  (1 wrong / 36 correct / 7 abstained, see Measured). Adversarial inputs and scored
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

Run from the repository root. The deterministic numbers need no network connection and
no API key; the two commands whose model column needs `OPENAI_API_KEY` say so below,
and each reports that column as unmeasured — not estimated — when the key is absent.

```bash
# the full suite
python -m pytest

# 159/159 extraction, IoU mean 0.9677, adversarial 24/24, qa_gold 36/36
# (one command, roughly a minute — this is the one to run if you run only one)
python scripts/verify.py

# the adversarial controls: 24/24 safe pass; unsafe caught on all 24 runs
# (12 distinct unsafe responses — the pack reuses each input twice)
python eval/run_adversarial.py --demo

# extraction on real published PDFs — low correct, zero wrong, printed together
python scripts/measure_external_holdout.py
REALDOOR_COLUMNS=1 REALDOOR_ARITHMETIC=1 python scripts/measure_external_holdout.py
python scripts/measure_confirm_set.py

# label vocabulary on captions we did not write (93.1% own / 70.6%→79.4% hold-out);
# the with-model column needs OPENAI_API_KEY
python scripts/measure_label_mapping.py

# the question-phrasing hold-out; the classifier column needs OPENAI_API_KEY
python scripts/measure_intent_router.py

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

node ui/tools/keyboard-journey.mjs    # 36/36
node ui/tools/reflow-check.mjs        # 15/15 — 5 widths (320/360/390/412/768) x 3 screens
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
