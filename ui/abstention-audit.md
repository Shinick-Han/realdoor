# Abstention audit — R26

**Rule (R26):** an abstention is a redirect, not a verdict. Saying "we do not know" is
correct and mandated. Ending there is not. Every visible abstention must continue into
(a) a concrete action the user can take, (b) the person or office that can settle it, or
(c) a control by which the user settles it themselves. An abstention carrying none of the
three is a defect. The product's stated output is document readiness and human-review
handoff, so an abstention's next step IS the handoff.

**Method.** Every surface an abstention can reach was enumerated from `ui/dist/app.js`,
`api/plain.py`, `api/situations.py`, `api/ask.py`, `logic/answer_rules.py`,
`logic/abstain.py` and the packet writer in `api/app.py`, then walked live against a
server on port 8099 — all six pack households, five upload fixtures
(up_002 intended-absent field, up_006 image-only, up_011 month-only date, up_017 synonym
drift, up_026 illegible), live corrections producing the recorded-but-not-used case, a
household of 9, an income that cannot be annualized, the generated packet, and the whole
list again under the Korean toggle. Nothing was softened or shrunk: every fix is
louder-with-a-path, and every machine string stays where it was.

**Count: 21 surfaces walked — 14 already COVERED, 7 COLD ENDS, all 7 fixed.**
New copy measures FK grade 0.6–6.6 per string, combined FK 4.0 / SMOG 6.7 (textstat).

| # | Surface | Before (quoted) | Verdict | After (quoted) |
|---|---------|-----------------|---------|----------------|
| 1 | Step 1 · pack value rows | No pack household carries a field-level abstain (verified across all six fixture reports), so the absence row cannot appear on pack documents today. | COVERED (vacuous — no abstention reaches this surface with pack data) | unchanged |
| 2 | Step 1 · document summary, undatable date (HH-004 gig statement) | "Still current? — ? No day in the date · The 60-day window cannot be applied — the date is not precise enough to use without inventing a day." Full stop; the action lived four steps away. | **COLD END** | Same two sentences, then: "If you know the exact date, enter it on step 2. Or ask for a copy that shows the full date. Step 5 lists this as an open item." (a)+(c). ko: "정확한 날짜를 아시면 2단계에서 입력해 주세요. …" |
| 3 | Step 1 · upload, intended-absent field (up_002 application_date) | "An application summary usually shows application date. We did not find one on this document. … If you can, ask whoever gave you the form for a version that shows it — or confirm below that this document really does not show it. [This document does not show this]" | COVERED (a)+(c) | unchanged |
| 4 | Step 1 · upload, read-nothing (up_026 illegible) | "We could not confidently read any field on this document. That is an answer, not a failure. … You can try choosing a different kind of document above, or hand this one to a person to read." | COVERED (a)+(b) | unchanged |
| 5 | Step 1 · upload, document-date abstention (up_011 month-only; up_002; up_026) | "Document date — ✕ Unreadable · no date we could read on this document". Full stop — and for up_011, "Unreadable" while the table below shows all 4 fields read cleanly. | **COLD END** (and names the wrong problem) | Month-only: "? No day in the date · The date shows a month but no day, so we cannot count the 60-day window from it. Ask the app you work for for a copy dated to the day, or tell the person who reviews it the exact date." No date at all: "✕ Unreadable · no date we could read on this document. Ask your employer for a copy that shows the date, or hand this one to a person to read." (a)+(b). Machine `state` untouched. |
| 6 | Step 1 · upload, low-confidence name note (up_006) | "…Check this row first, and fix it here if it is wrong." — but the upload table has no fix control; the promised way out did not exist on this surface. | **COLD END** (next step pointed at a missing control) | "…Check it against the page shown here. If it is wrong, the person who reviews this document goes by the page, not by our reading." (a)+(b). Household table keeps the original tail, where the control is real. |
| 7 | Rail "Things we did not say" — HH-001…HH-006, and after uploads | Every folded item leads with the plain action, e.g. HH-004: "Upload your bank statements, your earnings records from the app you work for, or a 1099 form covering the same dates." Empty/none states explain themselves ("Nothing has been read yet, so there is nothing yet to be unsure about…"). | COVERED (a); reasons also carry "Go to step N" (c) | unchanged |
| 8 | Ask panel · unrouted ("can i keep a dog in the apartment") | "This isn't one this tool can answer — here is where to take it … Where a question like this belongs: your property manager or a housing worker can answer it. … What you can ask here: … Step 3 lists them…" | COVERED (b)+(c) | unchanged |
| 9 | Ask panel · could-not-separate ("are they using the old numbers or the new ones right now") | "We read your question as one about using figures from a different year. If that is not what you meant, ask again in different words, or use a recorded question on step 3. … [Ask again in different words]" | COVERED (c) | unchanged |
| 10 | Ask panel · corpus abstention (frozen_corpus_enforced / size-9 lookup) | "We do not have an income limit for a household of your size … What would resolve it: a reviewer supplies the published 60% limit for household size 9, with its source" | COVERED (a)/(b) in English — see #20 for the Korean half | unchanged (English) |
| 11 | Ask panel · household-bound question, no household open ("What is my yearly income?") | "Abstained — no value given … No answer is given for this question. What would resolve it: supply the documents for the household in question" — the cure named, the control (one step away) not. | **COLD END** (named no control) | Abstention unchanged, plus: "What you can do: no file is open, so there was nothing to answer from. Step 1 reads a document you upload, or opens a prepared example file. Then ask again." (a)+(c). ko: "할 수 있는 일: 열려 있는 파일이 없어서…" |
| 12 | Ask panel · recorded questions (step 3), incl. refusals | Refusals carry resolves in both registers: "ask what the frozen threshold is, what the annualized amount is…", "open that household's own session, with that renter's consent". Offline session-bound withholding names the two ways forward (switch household / start the server). No-household callout explains which buttons still work and points at step 1. | COVERED (a)+(b)+(c) | unchanged |
| 13 | Step 5 · missing / expired / undatable (HH-004, HH-005) | Every open card leads with "What you can do: …" — e.g. "Ask your employer for a signed letter confirming your job, then upload it."; "Ask for a gig earnings statement that shows the full date, or tell us the exact date on the one you already sent."; expired (HH-005): "Ask your employer for a new letter dated 19 May 2026 or later, then upload it." Summary box repeats the same actions. | COVERED (a) | unchanged |
| 14 | Step 5 · unreadable | No pack household raises it today; audited at the message layer: "Send the ‹document› again. A clear photo in good light, or the original file from your employer or your bank, usually works." (`api/plain.py::_r_unreadable`, ko regex present) | COVERED (a) (latent) | unchanged |
| 15 | Step 2 · correction recorded-but-not-used (HH-001 gross_pay→2500) | "Your correction was recorded and was NOT used … What you can do: Tell us which amount is right, or add a stub that shows your usual pay. If the hours or the hourly rate are also wrong, correct those too." — plus the error summary link and the rail. | COVERED (a)+(c) | unchanged |
| 16 | Step 4 · figure could not be worked out (frequency "quarterly") | Wage panel: "Formula: `abstained` · Result: —" and nothing else. Total panel: "Formula: `no documented source` · Result: — · Frozen 60% threshold: $72,000.00 · No frozen threshold applies to this figure, so no comparison is made." The open item lived on step 5; this screen offered no path (and the comparison sentence contradicted the threshold row above it). | **COLD END** | Warn callout per withheld panel: "We could not work out this figure, so no amount is shown." (+ on the total: "The income limit itself is on file — what is missing is a yearly figure to set against it.") "What you can do: Ask your housing worker to convert this pay schedule into a yearly figure. They can enter it and the rest will follow." / "…Work through the other items on your list first. Each one says what to send." — actions read positionally off the report's own plain abstentions. (a)+(b). Machine formula strings untouched. |
| 17 | Step 4 · household of 9, comparison withheld | Total panel: "Frozen 60% threshold: No threshold applies to this line … No frozen threshold applies to this figure, so no comparison is made." No open item on this step (the reason files under step 5). | **COLD END** | Warn callout on the total line: "We could not compare this figure with a limit. We do not hold a limit for a household of this size. What you can do: Ask your housing worker for the published income limit for a household of your size. They can add it and the comparison will run." (b). Component lines with a result and no threshold — the by-design case — get nothing; the keyboard journey's exact comparison phrases are untouched. |
| 18 | Step 4 · region panel, size unknown / above 8 | "We cannot line this household up against another region. … HUD does not publish these limits for households of more than eight people. We will not estimate one." Full stop. | **COLD END** | Refusal unchanged, then: "Ask your housing worker for the published limit for your household size. They hold the tables this page will not guess from." (b). ko added for both sentences. |
| 19 | Packet · cover sheet "Things this tool did not say" + README.txt | Each abstention line carries its cure for the reviewer: "…What would clear it: the renter uploads platform earnings records, bank deposits, or a 1099 covering the same period." README routes the human to the cover sheet ("what the documents show, what a person checked, and what is still open") and shows no abstention of its own. | COVERED (a — tells the reviewer what to have the applicant supply) | unchanged |
| 20 | Packet · cover sheet profile row, value not read | "not read — the machine took no value here (‹machine note›)" — full stop. The sibling branch (renter-confirmed absence) already told the reviewer what the applicant confirmed; this one gave the reviewer nothing to do. Unreachable with today's pack data (every pack field carries a value) — a latent branch, audited because the reviewer is also a user. | **COLD END** (latent) | "not read — the machine took no value here (‹machine note›). If the review needs this value, ask the applicant for a copy of the document that shows it" (a, addressed to the reviewer). Machine note verbatim in place; both packet JSONs byte-identical. |
| 21 | Korean toggle across all of the above | Rail, step 5, step 1, step 2 and the unrouted answer were fully Korean. But on the ask surface the next-step half went dark under 한국어: every situation-layer and answer-rules resolve line stayed English ("a reviewer supplies the published 60% limit for household size 9, with its source", "supply the documents for the household in question", "contact the property's management office…", 20+ more), as did the abstained heading ("Abstained — no value given" — the dictionary only knew the retired wording "no answer given") and the three plain comparison sentences. | **COLD END** (the next step vanished for the very person the toggle serves) | All resolve sentences translated (dictionary entries plus regex rules for the ones carrying numbers and dates); heading "말하지 않았습니다 — 값을 내지 않았습니다"; comparison sentences translated. Verified live: "무엇이 있으면 풀리는지: 검토자가 세대원 9인에 대한 공표된 60% 상한을 출처와 함께 제공하면 됩니다". Every new string from fixes #2–#18 shipped bilingual in the same commit. |

## Gates (measured on the final state)

* `python -m pytest -q` — **1349 passed** (includes `eval/test_no_decision.py` over every new string, and `api/test_packet_summary.py` byte-freezing the packet JSONs)
* axe (WCAG 2.2 AA, 7 screens × file/http × en/ko) — **0 violations**
* reflow — **35/35**
* keyboard journey — **31/31**
* textstat on new copy — per-string FK 0.6–6.6, combined FK 4.0 / SMOG 6.7 (target ≈7)

## NEEDS_OWNER

1. **Situation-layer body paragraphs stay English under 한국어** (e.g. the size-9 body
   "NEEDS_REVIEW, with the abstention slot rather than a number. The frozen table in
   HUD-MTSP-002 covers…"). The plain headline above it and the resolve line below it are
   now Korean, so the abstention and its next step both survive the toggle; the precise
   evidence paragraph between them does not. It carries live-computed evidence and reads
   like the verbatim layer (U10 kept citations and judge-facing rationale English by
   design), so translating it is a policy call, not a mechanical one.
2. **`state=unreadable` for month-only dates at the extraction layer.** The upload view
   reports a month-only date as `unreadable`; the UI now says the true thing on top of it,
   but the state itself is owned by core/ (read-only in this pass, and the enum is frozen —
   `undatable` exists and would fit once the document is dated at month precision).
3. **`REASON_STEP` for `NO_FROZEN_THRESHOLD` / `INCOME_NOT_COMPUTABLE`** files their open
   item under step 5 while the wound shows on step 4. The step-4 callouts now carry the
   action in place, so nothing is cold — but if the owner would rather move the open item
   to step 4, that is a one-line routing change with error-summary implications.


## Owner decisions on the NEEDS_OWNER items (2026-07-21)

1. **Situation evidence paragraphs under 한국어 — stays English, deliberately.** The Korean
   layer is kept (it is part of the product's story: the reviewer's persona names
   non-native speakers, and the English for "Abstentions" was improved by following our own
   Korean), but further Korean investment is frozen. What is translated today — every
   headline, every next step, every renter-facing screen — is the commitment; the evidence
   paragraphs join the existing carve-out alongside verbatim HUD quotes.
2. **`state=unreadable` for month-only upload dates** — queued for a gated loop iteration
   after the OCR iterations finish (core/ is owned by that loop while it runs). The frozen
   enum already holds the right word (`undatable`); the fix is vocabulary consistency, not
   new behaviour.
3. **Open-item step routing** — left as is. The step-4 callouts carry the action in place;
   moving the open item would touch the error summary for no coverage gain.
