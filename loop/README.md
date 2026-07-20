# `loop/` — the self-feedback improvement loop

You have arrived cold. This directory is a **machine for changing `core/`**, not part of
the product. Nothing in here is imported by the extractor, the API or the UI. You can
delete the whole directory and every number the repository reports stays the same.

The design it implements is `../../extraction-loop-design.md` (outside the repo). This
file is the operator's manual; that document is the reasoning.

---

## What the loop is for, in one paragraph

The extractor abstains on fields it cannot read from a printed license. Some of those
abstentions are reachable and some are not, and the difference is not obvious from a
total. The loop takes one abstention at a time, makes an expensive model propose a rule
that rests on something the page *prints*, kills the proposal against all 77 corpus
documents **before any code is written**, implements it behind a feature flag, measures,
and accepts or reverts on a table of seven gates that no agent is allowed to argue with.
It is expected to be a **short** loop: roughly 5–8 iterations, most of which will end in
`NO_SAFE_RULE` records. Closing an item as unreachable is progress, and the terminal
report is expected to read "+6 or so fields, everything else classified", not a climb.

---

## The files

| path | what it is | who writes it |
|---|---|---|
| `baseline.json` | the current accepted state: per-corpus totals, pytest, and **`field_state`** — every expected field of all 77 documents, classified | `tools/build_field_state.py`, on ACCEPT only |
| `backlog.json` | the target inventory, seeded from design §7 in priority order | seeded day 0; P6 updates status/attempts |
| `tools/corpus_manifest.json` | the 77 documents: absolute path, corpus, and where its truth lives | `tools/build_corpus_manifest.py` |
| `proposals/it-NNN.md` | the eight mandatory sections, ≤150 lines | P2 (expensive model) |
| `falsify/it-NNN.py` | the proposal's firing predicate, runnable and read-only | P2 |
| `falsification/it-NNN.json` | the predicate's sweep over all 77 | P3 |
| `measurements/it-NNN.json` | the full gate result and the four measurement payloads | `tools/gate.py` |
| `reports/it-NNN.md` | the §E template, ≤80 lines, written for a reader who distrusts the loop | P6 |
| `ledger.jsonl` | one appended line per attempt, ACCEPT or not. Read by humans, never by agents | P6 |
| `STOP.md` | written once, at termination | P6 |
| `worktmp/` | scratch: word dumps, the G5 worktree, dump runners. **gitignored** | tools |

`field_state` is the load-bearing one. Totals hide a swap in which a change gains one
field and quietly eats a neighbour's; a field-level map does not. Gates G3 and G7 exist
because of it.

---

## Running it

```bash
# what the six phases are, what each reads and writes, and which model runs it
python loop/tools/run_phase.py

# which backlog item is up, and why
python loop/tools/run_phase.py next

# P3: sweep a proposal's predicate over all 77 documents
python loop/tools/run_phase.py p3 --iteration 17 --run

# P5/P6: the gate
python loop/tools/gate.py --iteration 17 --target T1 \
    --flag REALDOOR_GLYPHBOX \
    --allow core/extract.py --allow core/test_extract_reading.py \
    --predict confirm::ca_dlse_paystub_hourly.pdf::person_name

# the baseline self-check: no iteration in flight, nothing may have moved
python loop/tools/gate.py --iteration 0
```

`gate.py` exits non-zero when any gate fails and always writes its measurements file.

### Rebuilding the baseline (ACCEPT only)

```bash
python loop/tools/build_corpus_manifest.py     # fails loudly if the total is not 77
python loop/tools/build_field_state.py         # ~4 min: re-measures every corpus + pytest
```

---

## The gate, G1–G7

| gate | condition |
|---|---|
| G1 | `wrong == 0` on pack **and** external **and** confirm |
| G2 | pack: correct 159, abstained 0, IoU>0.5 count 159, IoU mean ≥ baseline − 0.0005 |
| G3 | no field anywhere flips `correct` → anything else (field-level, against `baseline.field_state`) |
| G4 | pytest failures 0 **and** passed ≥ baseline passed (tests may be added, never removed) |
| G5 | with this iteration's flag `=0`, extraction output for all 77 is byte-identical to the accepted commit's, cache cleared first |
| G6 | the diff ⊆ the proposal's allowlist ∪ `loop/`, and touches none of the protected instruments |
| G7 | observed flips ⊆ predicted flips, **and** observed ∩ target fields ≠ ∅ |

G1–G6 failing ⇒ `REJECTED_GATE`, automatic revert, ledger names the gate. **G7 failing is
different**: an unpredicted flip — *even a gain* — is an anomaly and buys one expensive
REVIEW call. A rule that helps where its author did not expect is a rule whose firing
condition nobody understands, which is one document away from a wrong value.

`gate.py` has two modes. With `--target` it is the table above. Without `--target` it is
the **baseline self-check**, where G7 instead requires the observed flip set to be
*empty*: on an unchanged tree nothing may move. Both were exercised on day 0 — the gate
passes on the known-good tree and fires, naming the field, on a deliberately broken one.

### What the gate cannot check, said plainly

Constraint 2 — "a rule rests only on what the page prints" — **is not machine-checkable**.
The gate makes *wrongness* automatic to catch. *Licensing* is enforced socially: by P2
being the expensive model with a five-license taxonomy as a hard template, by the
mandatory hazard section, by the falsification sweep making proximity rules die on
contact with 77 documents, and by a human reading the reports. A determined bad proposal
can pass every gate and still be a fitted rule if the corpus happens never to contradict
it. Every three accepts, a human should read the accepted proposals' license sections.
Ten minutes each.

---

## Things that will otherwise eat an afternoon

1. **`.cache/extractions` must be cleared before every measurement pass.** Its key
   (`api/store._cache_key`) is the PDF bytes + a content hash of four engine sources + the
   label-model state + the OCR cap — and **not** the feature flags. A `REALDOOR_X=0` run
   served from a warm cache reads back bytes produced with the flag **on**, so G5 would
   pass while proving nothing. Every tool here clears it; do not add one that doesn't.
2. **pdfplumber writes `Could not get FontBBox…` to stderr mid-run.** Parse stdout JSON
   only. Every subprocess in `tools/` does.
3. **The measure scripts exit non-zero when `wrong > 0`.** A driver reading exit codes
   cannot tell "found a wrong value" from "crashed". Parse the JSON; the tools here
   report a crash distinctly from a failed gate.
4. **`eval/test_no_decision.py` walks `loop/` too.** It bans the tokens `eligible,
   approved, denied, score, rank, priority, qualified, recommendation` (and inflections)
   as keys in any `.json` or as quoted key literals in any `.py`, repo-wide. A key named
   `documents_scored` in an artefact fails the suite, and therefore G4. It also adds one
   parametrized test per file, so each file added here raises the pytest count — which is
   why G4 says *passed ≥ baseline*, never *equal*.
5. **`git restore` on REJECT must exclude `loop/`.** The artefacts of a rejected iteration
   are the record that it was rejected.
6. **The working tree carries unrelated in-progress work** (a modified README, UI scan
   artefacts, untracked recorder scripts, the confirm PDFs). `baseline.preexisting_dirty`
   records it by name so G6 charges an iteration only for what it actually changed. The
   forbidden-path half of G6 is **not** exempted: a protected file that is dirty fails,
   whoever made it dirty.

---

## What the corpus is worth

77 documents: pack 24 (ours, authored), uploads 26 (ours), wording hold-out 7 (real label
strings, our geometry), external 6 (real published PDFs), confirm 14 (real published
PDFs, truth transcribed before any code was seen).

external-6 and confirm-14 are **dev sets now**. Every gain measured on them after day 0 is
weak evidence by this project's own standard, and the ledger's `corpus_inspection_status`
never upgrades. Nothing measured on confirm-14 after today is called generalisation
anywhere. The one mechanism that mints new evidence is the **confirm-2 protocol** (design
§F): a collector with web access and *no repo access* gathers K ≥ 8 new published pay
documents, transcribes truth from rendered page images before any code runs, records
sha256s; the batch is scored **once**, at loop end, as acceptance — never per iteration.
`wrong == 0` on it is the acceptance claim. Gains and abstentions on confirm-2 never
become targets: the moment it is used to *choose* a rule it is spent.

If that standard cannot be met, skip confirm-2 and let `STOP.md` say "no untouched corpus
exists; all gains are dev-set gains." That sentence is worth more than a batch collected
sloppily, which mints false evidence with a hold-out's authority.
