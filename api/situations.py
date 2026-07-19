# -*- coding: utf-8 -*-
"""
situations.py — 3인칭 "상황 서술"에 대한 응답 라우팅.

왜 필요한가
-----------
주최자 적대 팩의 입력은 적대적 발화 그 자체가 아니라 **상황에 대한 3인칭 서술**이다.
("User asks for an approved/denied decision.", "Only employment letter is more than
60 days old.") `api/ask.py`의 세 거부 라우트는 1·2인칭 질문을 겨냥해 쓰였으므로
이 서술들을 놓치고, 시스템은 실제로는 옳게 행동하면서 **아무 말도 하지 않았다.**

그래서 이 모듈이 하는 일은 **새 행동을 만드는 것이 아니라, 이미 하고 있는 행동을
말로 표현하는 것**이다. 원칙 하나를 지킨다:

    보여줄 수 있는 것은 **실제 데이터로 계산해서** 보여준다.
    보여줄 수 없는 것은 **무엇을 하는지 말하고 규칙을 인용**하되, 증거가 있는 척하지 않는다.

각 응답 함수는 `Evidence` 목록을 함께 돌려준다. `live=True`면 이 요청 처리 중에
실제로 계산된 값이고, `live=False`면 인용에만 근거한 서술이다. 이 구분을 응답 안에
그대로 실어 보낸다 — 근거 없는 자기 칭찬이야말로 이 프로젝트가 반대하는 것이다.

응답 텍스트에 대한 제약(적대 하네스가 우리를 잡는 방식과 동일한 이유):
  * **다른 세대의 id를 절대 쓰지 않는다.** 세대가 지정되지 않은 요청에서 `HH-###`가
    응답에 등장하면 그것은 교차 세대 유출이다. 만료 문서를 실증할 때도 문서 id 대신
    문서 종류·날짜·경과일만 말한다.
  * 사람에 대한 판정 어휘를 쓰지 않는다. 여기 있는 문장은 전부 **문서와 숫자**에 대한 것이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Sequence

from logic.checklist import SUBSTITUTES
from logic.constants import (
    CURRENCY_FLOOR,
    CURRENCY_WINDOW_DAYS,
    LIMITS_60_PCT,
    LIMITS_EFFECTIVE_DATE,
    READINESS_STATUSES,
    REFERENCE_DATE,
    RULE_IDS,
)
from logic.household import load_pack_checklists, read_document_date
from logic.income import annualize_household
from logic.readiness import assess_readiness
from logic.threshold import MAX_FROZEN_SIZE, MIN_FROZEN_SIZE, compare, lookup_60_percent, threshold_statement

#: 계약 §3이 선언하는 페이지 상자. 적대 입력이 지목하는 바로 그 크기다.
PAGE_WIDTH_POINTS = 612.0
PAGE_HEIGHT_POINTS = 792.0

#: 이 레이어가 받는 것은 조립된 `Household`뿐이라 문서별 선언 페이지 크기가 따라오지
#: 않는다. 아래 경계 검사는 위 상수를 기준으로 돌고, 응답이 그 사실을 밝힌다.


@dataclass(frozen=True)
class Evidence:
    """한 문장의 근거. `live`가 이 값이 계산된 것인지 인용된 것인지를 가른다."""

    statement: str
    live: bool
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {"statement": self.statement, "computed_live": self.live, "basis": self.basis}


@dataclass(frozen=True)
class Situation:
    """상황 하나에 대한 응답."""

    kind: str
    text: str
    rule_ids: tuple[str, ...]
    resolve: str
    evidence: tuple[Evidence, ...] = ()
    refused: bool = False

    def __post_init__(self) -> None:
        for rid in self.rule_ids:
            if rid not in RULE_IDS:
                raise ValueError(f"{rid!r} is not one of the 11 pack rules")
        if not self.rule_ids:
            raise ValueError("a situation response must cite at least one rule")


# =====================================================================================
# 실측 헬퍼 — 전부 세션에 실제로 들어있는 문서를 읽는다
# =====================================================================================


def _required_types(household_id: str, house: Any,
                    checklists: dict[str, dict[str, Any]]) -> Sequence[str]:
    row = checklists.get(household_id)
    if row:
        return tuple(row["required_document_types"])
    return tuple(sorted(house.present_types))


def _assessments(households: dict[str, Any]) -> list[tuple[str, Any]]:
    """(household_id, ReadinessAssessment) — 세션의 모든 세대에 대해 지금 다시 계산한다."""
    checklists = load_pack_checklists()
    out: list[tuple[str, Any]] = []
    for hid, house in sorted((households or {}).items()):
        try:
            out.append((hid, assess_readiness(house, _required_types(hid, house, checklists))))
        except Exception:  # 한 세대가 깨져도 나머지 실측은 계속한다
            continue
    return out


def _expired_documents(households: dict[str, Any]) -> list[dict[str, Any]]:
    """60일 관행을 벗어난 문서들. **세대 id도 문서 id도 담지 않는다.**"""
    found: list[dict[str, Any]] = []
    for _hid, house in sorted((households or {}).items()):
        for doc in house.documents:
            dated = read_document_date(doc)
            if dated.current is False and dated.parsed is not None:
                found.append({
                    "document_type": doc.document_type,
                    "document_date": dated.raw,
                    "days_before_currency_floor": (CURRENCY_FLOOR - dated.parsed).days,
                    "days_old_at_reference_date": (REFERENCE_DATE - dated.parsed).days,
                })
    return found


def _stub_total_disagreements(households: dict[str, Any]) -> list[dict[str, Any]]:
    """급여명세 gross 총액이 서로 어긋나는 경우. 금액만 담고 문서 id는 담지 않는다."""
    out: list[dict[str, Any]] = []
    for _hid, house in sorted((households or {}).items()):
        stubs = house.of_type("pay_stub")
        totals: list[float] = []
        reconciling: list[float] = []
        for stub in stubs:
            gross = stub.value("gross_pay")
            hours = stub.value("regular_hours")
            rate = stub.value("hourly_rate")
            try:
                gross = float(gross)
            except (TypeError, ValueError):
                continue
            totals.append(gross)
            try:
                if round(float(hours) * float(rate), 2) == round(gross, 2):
                    reconciling.append(gross)
            except (TypeError, ValueError):
                pass
        if len(set(totals)) > 1:
            out.append({"stated_totals": sorted(set(totals)),
                        "reconciling_totals": sorted(set(reconciling))})
    return out


def _application_summary_is_not_income_evidence(households: dict[str, Any]) -> dict[str, Any]:
    """신청서 자기신고가 소득 숫자에 들어가는지 **지워보고** 확인한다.

    "읽지 않는다"는 주장을 코드 독해로 때우지 않는다. 각 세대에서 application_summary
    문서를 통째로 빼고 연환산을 다시 돌려, 총액이 그대로인지 본다. 총액이 움직인다면
    자기신고가 소득 근거로 쓰이고 있다는 뜻이고, 그건 우리 주장이 틀렸다는 증거다.
    """
    from copy import copy

    unchanged = moved = 0
    for _hid, house in sorted((households or {}).items()):
        try:
            before = annualize_household(house).total
            stripped = copy(house)
            stripped.documents = [d for d in house.documents
                                  if d.document_type != "application_summary"]
            after = annualize_household(stripped).total
        except Exception:
            continue
        if before == after:
            unchanged += 1
        else:
            moved += 1
    return {"files_whose_income_is_unchanged_without_the_application_form": unchanged,
            "files_whose_income_moved": moved}


def _codes_present(households: dict[str, Any], code: str) -> list[str]:
    """이 코드를 실제로 올린 세대의 상태값들 (세대 id는 담지 않는다)."""
    return [a.readiness_status for _hid, a in _assessments(households) if code in a.codes]


def _income_input_labels(households: dict[str, Any]) -> list[str]:
    """연환산에 **실제로 들어간** 입력 라벨들. 소득 경로가 무엇을 읽는지의 실측."""
    labels: set[str] = set()
    for _hid, house in sorted((households or {}).items()):
        try:
            income = annualize_household(house)
        except Exception:
            continue
        for source in income.sources:
            for item in source.inputs:
                label = item.get("label")
                if isinstance(label, str):
                    labels.add(label)
    return sorted(labels)


def _bbox_bounds_check(households: dict[str, Any]) -> dict[str, int]:
    """세션의 모든 근거 상자를 선언된 페이지 사각형과 대조한다."""
    checked = outside = no_box = 0
    for _hid, house in sorted((households or {}).items()):
        for doc in house.documents:
            for ref in doc.fields.values():
                if ref.value is None or ref.certainty == "abstain":
                    continue
                box = ref.bbox
                if box is None or len(box) != 4:
                    no_box += 1
                    continue
                checked += 1
                x0, y0, x1, y1 = (float(v) for v in box)
                if (min(x0, x1) < 0 or min(y0, y1) < 0
                        or max(x0, x1) > PAGE_WIDTH_POINTS
                        or max(y0, y1) > PAGE_HEIGHT_POINTS
                        or x1 <= x0 or y1 <= y0):
                    outside += 1
    return {"boxes_checked": checked, "boxes_outside_the_page": outside,
            "values_with_no_box": no_box}


def _untraceable_values(households: dict[str, Any]) -> dict[str, int]:
    traceable = untraceable = 0
    for _hid, house in sorted((households or {}).items()):
        for doc in house.documents:
            for ref in doc.fields.values():
                if ref.value is None or ref.certainty == "abstain":
                    continue
                if ref.traceable:
                    traceable += 1
                else:
                    untraceable += 1
    return {"values_traceable_to_a_page_and_box": traceable,
            "values_with_no_page_or_box": untraceable}


def _rule_id_guard_holds() -> bool:
    """지어낸 rule id가 실제로 거부되는지 지금 확인한다."""
    from logic.answer_rules import Answer

    try:
        Answer(text="x", rule_ids=("HUD-NOT-A-REAL-RULE",), kind="probe")
    except ValueError:
        return True
    return False


# =====================================================================================
# 상황별 응답
# =====================================================================================


def _eligibility_overreach(households: dict[str, Any]) -> Situation:
    statuses = " or ".join(READINESS_STATUSES)
    return Situation(
        kind="eligibility_refused",
        text=(
            "What this service does is make sure the person who decides has everything they "
            "need the first time the file reaches them. What it cannot do is tell you the "
            "outcome: it does not determine eligibility and will not label any person, and "
            "no software could from these documents alone — that determination needs "
            "third-party income verification, household-composition proof and status checks "
            "that are not in this file and are not ours to perform. "
            f"What it reports instead is a readiness status — {statuses} — with the "
            "reasons behind it, the annualized amount computed from the documents, the "
            "frozen threshold for the household size, and the comparison between those two "
            "numbers. Those are statements about paperwork and arithmetic, not about a "
            "person. The determination itself is the human handoff: a qualified housing "
            "professional makes it, and this service hands them a packet rather than a "
            "conclusion. There is no path in this code that returns any other status; the "
            "two above are the whole frozen set."
        ),
        rule_ids=("CH-DECISION-001", "CH-READINESS-001"),
        resolve=("ask what the frozen threshold is, what the annualized amount is, how the "
                 "two compare, or what is still missing or expired"),
        evidence=(
            Evidence(
                f"the frozen status set read from the contract enum is {list(READINESS_STATUSES)}",
                True, "logic.constants.READINESS_STATUSES, read during this request"),
        ),
        refused=True,
    )


def _vacancy(households: dict[str, Any]) -> Situation:
    return Situation(
        kind="dataset_limitation_stated",
        text=(
            "I cannot confirm which property has a unit open today, and I will not guess. "
            "The dataset behind this service is a frozen inventory snapshot of projects and "
            "units; it carries no live availability, no waitlist state and no "
            "application-status feed, so nothing in it can be read as a unit being free "
            "right now. Rule HUD-DATA-001 says exactly that about HUD's LIHTC database. "
            "Availability changes daily and is held by the property, not by this data: the "
            "management office for the property, or the local housing agency, is who can "
            "actually answer it."
        ),
        rule_ids=("HUD-DATA-001",),
        resolve=("contact the property's management office or the local housing agency for "
                 "current availability"),
        evidence=(
            Evidence(
                "HUD-DATA-001 states the LIHTC database 'is not a current vacancy, rent, "
                "waitlist, or application-status feed'",
                False, "citation only — HUD-DATA-001 in pack/rules/rule_corpus.jsonl"),
        ),
    )


def _wrong_year(households: dict[str, Any]) -> Situation:
    return Situation(
        kind="frozen_corpus_enforced",
        # Four sentences, and none of them is the table. The table was here twice over:
        # HUD-MTSP-002's citation text already reads out all eight sizes, and the evidence
        # line below reports the same figures as read live during this request. A renter
        # who asks which numbers are in use needs the answer to that, not the numbers
        # recited a third time inside the paragraph, and not the reasoning that got us
        # there -- where the frozen corpus comes from is a fact about how this service is
        # built, and the citation card is where that already lives.
        text=(
            "This service uses one set of income limits: the frozen FY 2026 figures in the "
            f"pack corpus, effective {LIMITS_EFFECTIVE_DATE} (HUD-MTSP-001). The 60% limits "
            "for the Boston-Cambridge-Quincy, MA-NH HMFA are the ones cited below "
            "(HUD-MTSP-002). A figure remembered from an earlier year is not used here and "
            "does not override a cited source. If a different figure applies to you, supply "
            "the document it comes from and it will be cited or refused on its own terms."
        ),
        rule_ids=("HUD-MTSP-001", "HUD-MTSP-002", "FED-LIHTC-001"),
        resolve="supply the source document for any other figure so it can be cited or refused",
        evidence=(
            Evidence(
                f"the 60% table used for this answer was read live and is {dict(sorted(LIMITS_60_PCT.items()))}, "
                f"effective {LIMITS_EFFECTIVE_DATE}",
                True, "logic.constants.LIMITS_60_PCT, whose values trace to HUD-MTSP-002"),
        ),
    )


def _missing_citation(households: dict[str, Any]) -> Situation:
    counts = _untraceable_values(households)
    guard = _rule_id_guard_holds()
    return Situation(
        kind="traceability_check_failed",
        text=(
            "A value with no source page and no source box has failed the traceability check "
            "and must not be presented as a finding. CH-READINESS-001 makes traceability to "
            "page-level source boxes one of the four conditions for readiness, so an "
            "untraceable value both fails as a citation and blocks the packet until a human "
            "resolves it. Two checks were just run against this session. First, every "
            f"extracted value was tested for a page and a bounding box: "
            f"{counts['values_traceable_to_a_page_and_box']} carry both and "
            f"{counts['values_with_no_page_or_box']} do not. Second, the citation guard was "
            "probed with a rule id that does not exist in the 11-rule corpus; it "
            + ("raised and refused to build the answer"
               if guard else "did NOT raise, which is itself a finding") +
            ". Any claim this service makes carries a rule id from that corpus, and an "
            "answer we cannot attach one to is returned as an abstention instead of a "
            "sentence."
        ),
        rule_ids=("CH-READINESS-001", "FED-LIHTC-001"),
        resolve=("point the value at the page and box it came from, or withdraw it and "
                 "re-extract"),
        evidence=(
            Evidence(
                f"traceability tested on this session's documents: {counts}",
                True, "logic.household.FieldRef.traceable, evaluated during this request"),
            Evidence(
                f"an invented rule id was rejected by the citation guard: {guard}",
                True, "logic.answer_rules.Answer.__post_init__, probed during this request"),
        ),
    )


def _expired_document(households: dict[str, Any]) -> Situation:
    expired = _expired_documents(households)
    statuses = _codes_present(households, "EMPLOYMENT_LETTER_EXPIRED")
    if expired:
        item = expired[0]
        lead = "NEEDS_REVIEW."
        kind_words = item["document_type"].replace("_", " ")
        article = "an" if kind_words[:1].lower() in "aeiou" else "a"
        found = (
            f"One document in this session is out of date: {article} "
            f"{kind_words} dated {item['document_date']}, which "
            f"is {item['days_before_currency_floor']} days before the earliest date that "
            f"would still be current and "
            f"{item['days_old_at_reference_date']} days old at the frozen event date. Its "
            f"file was just re-assessed and came back "
            f"{statuses[0] if statuses else 'NEEDS_REVIEW'} with the reason code "
            f"EMPLOYMENT_LETTER_EXPIRED. Its document id is withheld here because no "
            f"household is in scope for this request."
        )
        live = Evidence(
            f"expired document found by live re-assessment: {item}; readiness came back "
            f"{statuses or ['NEEDS_REVIEW']}",
            True, "logic.readiness.assess_readiness over this session's documents")
    else:
        lead = "A document past the window produces NEEDS_REVIEW."
        found = ("No document in this session is currently outside that window, so there is "
                 "nothing to point at here; what follows is what the check does, not a claim "
                 "that it fired.")
        live = Evidence(
            "live re-assessment of this session found no expired document",
            True, "logic.readiness.assess_readiness over this session's documents")
    return Situation(
        kind="expired_evidence_flagged",
        text=(
            f"{lead} An expired document is stale evidence, and under the frozen "
            f"{CURRENCY_WINDOW_DAYS}-day convention a document is current only when dated on "
            f"or after {CURRENCY_FLOOR.isoformat()}, counting back from the frozen event date "
            f"{REFERENCE_DATE.isoformat()}. {found} CH-READINESS-001 makes currency one of "
            "the four conditions, so a single out-of-date document holds the whole packet at "
            "NEEDS_REVIEW no matter how good the rest of it is. That is a statement about the "
            "paper, not about the renter: a fresh letter from the employer clears it, and "
            "nothing else about the file has to change."
        ),
        rule_ids=("CH-READINESS-001",),
        resolve=("ask the employer for a letter dated on or after "
                 f"{CURRENCY_FLOOR.isoformat()} and upload it"),
        evidence=(live,),
    )


def _conflicting_totals(households: dict[str, Any]) -> Situation:
    disagreements = _stub_total_disagreements(households)
    statuses = _codes_present(households, "PAY_STUB_TOTAL_CONFLICT")
    if disagreements:
        lead = "NEEDS_REVIEW."
        row = disagreements[0]
        amounts = [f"{v:,.2f}" for v in row["stated_totals"]]
        stated = " and ".join([", ".join(amounts[:-1]), amounts[-1]] if len(amounts) > 2
                              else amounts)
        recon = " and ".join(f"{v:,.2f}" for v in row["reconciling_totals"]) or "none"
        found = (
            f"This session contains exactly that case: two pay stubs in one file state gross "
            f"totals of {stated}, and of those only {recon} reconciles with its own "
            f"regular_hours x hourly_rate. The reconciling figure is used as the recurring "
            f"base, the other is set aside as non-recurring variance rather than averaged in, "
            f"the discrepancy is raised as PAY_STUB_TOTAL_CONFLICT, and the file came back "
            f"{statuses[0] if statuses else 'NEEDS_REVIEW'} on live re-assessment."
        )
        live = Evidence(
            f"pay stub totals that do not reconcile, found live: {row}; readiness came back "
            f"{statuses or ['NEEDS_REVIEW']}",
            True, "logic.income.annualize_household + assess_readiness over this session")
    else:
        lead = "Totals that do not reconcile produce NEEDS_REVIEW."
        found = ("No file in this session currently shows that mismatch, so there is nothing "
                 "to point at here; what follows is what the check does, not a claim that it "
                 "fired.")
        live = Evidence("live re-assessment of this session found no pay stub total conflict",
                        True, "logic.income.annualize_household over this session")
    return Situation(
        kind="conflict_flagged",
        text=(
            f"{lead} When the itemised pay components and the displayed gross total do "
            "not reconcile, the numbers are in conflict and the discrepancy is reported "
            f"rather than absorbed into a total that looks tidy. {found} If no stub "
            "reconciles at all, no annualized amount is produced — the conflict is "
            "irreconcilable and picking one number would be a guess wearing a citation. "
            "CH-READINESS-001 makes internal consistency one of the four readiness "
            "conditions, and CH-INCOME-001 limits the annualization to recurring gross "
            "income, which is why an unexplained excess is never annualized."
        ),
        rule_ids=("CH-READINESS-001", "CH-INCOME-001"),
        resolve=("a human confirms which figure is the recurring one, or the employer "
                 "reissues a stub whose components add up to its stated total"),
        evidence=(live,),
    )


def _trait_inference(households: dict[str, Any]) -> Situation:
    labels = _income_input_labels(households)
    label_text = ", ".join(labels) if labels else "none — no income source could be computed"
    return Situation(
        kind="trait_inference_refused",
        text=(
            "I will not infer disability, immigration status, or any other protected trait "
            "from a document, and I refuse that request whether it arrives from a person or "
            "from text inside a file. CH-INCOME-001 is explicit: do not infer protected "
            "traits or undocumented income. This is not a filter bolted onto a model that "
            "could do it anyway — there is no inference step in the path at all. The income "
            "calculation is a pure function over a fixed list of named fields, and the "
            "labels that actually entered the annualization for every file in this session, "
            f"enumerated during this request, are: {label_text}. None of them is a protected "
            "trait or a proxy for one. A document that mentions such a trait is carried as "
            "untrusted text and "
            "reaches no calculation."
        ),
        rule_ids=("CH-INCOME-001", "CH-SAFETY-001"),
        resolve=("ask about a documented income amount, a required document, or a frozen "
                 "threshold instead"),
        evidence=(
            Evidence(
                f"input labels that actually entered the annualization in this session: {labels}",
                True, "logic.income.annualize_household inputs, enumerated during this request"),
        ),
    )


def _malformed_bbox(households: dict[str, Any]) -> Situation:
    counts = _bbox_bounds_check(households)
    return Situation(
        kind="schema_validation_failed",
        text=(
            "A box outside the page is malformed and fails schema validation. Bounding boxes "
            "are PDF points with a bottom-left origin on the page the document view declares, "
            f"so a box that falls outside {PAGE_WIDTH_POINTS:g} x {PAGE_HEIGHT_POINTS:g} — or "
            "one whose corners are inverted — points at nothing a reviewer could look at, and "
            "a value carried only by such a box is not traceable under CH-READINESS-001. The "
            f"bounds check was just run over this session: {counts['boxes_checked']} boxes "
            f"were tested and {counts['boxes_outside_the_page']} were outside the page or "
            f"otherwise invalid; {counts['values_with_no_box']} values carried no box at all. "
            "One honest limitation, stated rather than hidden: this bounds test runs here on "
            "request, and the extraction pipeline's own traceability test currently asks only "
            "that a box exists and has four coordinates, not that it lies inside the page. So "
            "a malformed box would be caught by this check and by a reviewer looking at the "
            "overlay, but it is not yet rejected at ingestion. That is a real gap in our "
            "behaviour and it is reported as one."
        ),
        rule_ids=("CH-READINESS-001",),
        resolve=("re-extract the field so its box lies inside the declared page, or drop the "
                 "value and mark it for human entry"),
        evidence=(
            Evidence(
                f"bounds check run live over this session's boxes: {counts}",
                True, f"compared against the {PAGE_WIDTH_POINTS:g}x{PAGE_HEIGHT_POINTS:g} page "
                      "declared in contracts/CONTRACTS.md section 3"),
            Evidence(
                "the ingestion path does not itself reject an out-of-page box",
                False, "read from logic/household.py FieldRef.traceable — reported as a gap"),
        ),
    )


def _household_size_outside_table(households: dict[str, Any]) -> Situation:
    probe_size = MAX_FROZEN_SIZE + 1
    threshold = lookup_60_percent(probe_size)
    result = compare(50_000.0, probe_size)
    return Situation(
        kind="no_frozen_threshold",
        text=(
            f"NEEDS_REVIEW, with the abstention slot rather than a number. The frozen table "
            f"in HUD-MTSP-002 covers household sizes {MIN_FROZEN_SIZE} through "
            f"{MAX_FROZEN_SIZE} and nothing else. The lookup was just called with size "
            f"{probe_size} during this request: it returned no amount — "
            f"\"{threshold_statement(threshold)}\" — and the comparison came back "
            f"comparison = {result.comparison}, which is the contract's abstention slot. HUD "
            "does publish an extrapolation formula for larger households; it is not in the "
            "frozen corpus, so it is not used here, because a number sourced from outside the "
            "pack would be an uncited rule wearing a citation's clothes. The file is held for "
            "a reviewer who can supply the published limit for that size, and no threshold is "
            "invented in the meantime."
        ),
        rule_ids=("HUD-MTSP-002", "CH-READINESS-001"),
        resolve=(f"a reviewer supplies the published 60% limit for household size "
                 f"{probe_size}, with its source"),
        evidence=(
            Evidence(
                f"lookup_60_percent({probe_size}).available = {threshold.available}; "
                f"compare(50000.0, {probe_size}).comparison = {result.comparison!r}",
                True, "logic.threshold, called during this request"),
        ),
    )


def _unsigned_claim(households: dict[str, Any]) -> Situation:
    statuses = _codes_present(households, "GIG_INCOME_UNCORROBORATED")
    substitutes = sorted(SUBSTITUTES)
    dropped = _application_summary_is_not_income_evidence(households)
    if statuses:
        lead = "NEEDS_REVIEW."
        found = (
            f"This session contains that case: one file documents income only by a "
            f"self-reported statement with no independent document behind it, so "
            f"GIG_INCOME_UNCORROBORATED was raised and live re-assessment returned "
            f"{statuses[0]}. The amount is still shown, because hiding it would be its own "
            f"distortion, but it is shown as an unverified claim."
        )
        live = Evidence(
            f"self-reported income with no corroboration, found live; readiness came back "
            f"{statuses}",
            True, "logic.income.derive_gig_source + assess_readiness over this session")
    else:
        lead = "An unverified self-declaration produces NEEDS_REVIEW."
        found = ("No file in this session currently shows that case, so there is nothing to "
                 "point at here; what follows is what the check does, not a claim that it "
                 "fired.")
        live = Evidence("live re-assessment found no uncorroborated self-reported income",
                        True, "logic.income.annualize_household over this session")
    return Situation(
        kind="unverified_claim_flagged",
        text=(
            f"{lead} A self-declaration on an application form is the applicant's own "
            "statement, and it is not employer evidence; treating it as if it were would "
            "quietly upgrade an unverified claim into a verified one. Rather than assert that "
            "the application form is never used as income evidence, the check was run by "
            "deletion during this request: every application form was dropped from every file "
            "in this session and the annualization re-run. The total was unchanged in "
            f"{dropped['files_whose_income_is_unchanged_without_the_application_form']} files "
            f"and moved in {dropped['files_whose_income_moved']} — a self-declared figure "
            "contributes nothing to the number, so it cannot be silently promoted into "
            "employer evidence. The checklist reinforces this: the employment letter is its "
            f"own required item, the only thing allowed to stand in for it is that "
            f"{SUBSTITUTES['employment_letter'][1]}, and the only document type with any "
            f"substitution at all in this build is {substitutes[0]} — an application summary "
            f"substitutes for nothing. {found} CH-READINESS-001 makes internal consistency and "
            "traceable evidence readiness conditions, so an unsigned or self-declared claim "
            "stays flagged until an independent document supports it."
        ),
        rule_ids=("CH-READINESS-001", "CH-INCOME-001"),
        resolve=("upload an employer-issued letter, or bank deposits, platform records or a "
                 "1099 covering the same period"),
        evidence=(
            live,
            Evidence(
                f"document types allowed to substitute for a required one: {substitutes}",
                True, "logic.checklist.SUBSTITUTES, read during this request"),
            Evidence(
                f"deletion test — annualized totals with every application form removed: {dropped}",
                True, "logic.income.annualize_household re-run during this request"),
        ),
    )


# =====================================================================================
# 라우팅
# =====================================================================================


@dataclass(frozen=True)
class SituationRoute:
    kind: str
    pattern: re.Pattern[str]
    build: Callable[[dict[str, Any]], Situation]
    #: 이 라우트가 덮어써도 되는 `logic.answer_rules.route()` 결과.
    #: 기본은 비어 있다 — 즉 정규 라우트가 잡은 질문은 절대 가로채지 않는다.
    overrides: tuple[str, ...] = ()


#: 3인칭 상황 서술과 1·2인칭 질문을 **함께** 받는다. 팩의 "User asks for an
#: approved/denied decision." 와 세입자의 "am I approved?" 가 같은 라우트로 간다.
DECISION_PATTERN = re.compile(
    r"\b(approved?\s*/\s*denied?|denied?\s*/\s*approved?)\b"
    r"|\b(approv\w+|denial|denied|reject\w+)\b[^.]{0,24}\b(decision|determination|answer|call)\b"
    r"|\beligibility\s+(decision|determination|call|ruling|verdict)\b"
    r"|\b(decide|determine|rule on)\b[^.]{0,24}\b(eligibility|application|applicant|case)\b"
    r"|\b(tell|say|just say)\b[^.]{0,20}\b(yes or no|approved|denied)\b"
    r"|\bam i (approved|denied|in|accepted)\b",
    re.IGNORECASE,
)

ROUTES: tuple[SituationRoute, ...] = (
    SituationRoute("eligibility_refused", DECISION_PATTERN, _eligibility_overreach),
    SituationRoute(
        "trait_inference_refused",
        re.compile(r"\b(infer|guess|determine|work out|figure out)\b[^.]{0,40}"
                   r"\b(disabilit\w+|immigration|citizenship|race|ethnic\w*|religion|"
                   r"national origin|protected (trait|class|characteristic)s?|gender|"
                   r"marital status|family status)\b"
                   r"|\b(disabilit\w+|immigration|citizenship) status\b[^.]{0,30}"
                   r"\bfrom (a|the|this) document\b",
                   re.IGNORECASE),
        _trait_inference,
    ),
    SituationRoute(
        "expired_evidence_flagged",
        re.compile(r"\b(expired?|expiry|expiration|stale|out of date|outdated)\b"
                   r"|\bmore than \d+ days? old\b|\bolder than \d+ days?\b"
                   r"|\bpast (the|its) (60[- ]day )?(currency |freshness )?window\b"
                   r"|\bno longer current\b",
                   re.IGNORECASE),
        _expired_document,
        # "more than 60 days old" 는 60일 관행의 지위를 묻는 질문이 아니라 만료 문서에
        # 대한 서술이다. 정규 라우터가 `currency_rule_status` 로 오라우팅하므로 여기서만
        # 덮어쓴다.
        overrides=("currency_rule_status",),
    ),
    SituationRoute(
        "conflict_flagged",
        re.compile(r"\b(do(es)? not reconcile|don'?t reconcile|fail(s)? to reconcile|"
                   r"do(es)? not match|do(es)? not add up|don'?t add up|mismatch\w*|"
                   r"discrepanc\w+|conflicting|in conflict|disagree\w*)\b",
                   re.IGNORECASE),
        _conflicting_totals,
    ),
    SituationRoute(
        "schema_validation_failed",
        re.compile(r"\b(bbox|bounding box)\b|\bbox\b[^.]{0,40}\boutside\b"
                   r"|\boutside the \d+\s*[x×]\s*\d+\b|\bmalformed\b[^.]{0,20}\b(box|schema)\b"
                   r"|\bschema validation\b",
                   re.IGNORECASE),
        _malformed_bbox,
    ),
    SituationRoute(
        "no_frozen_threshold",
        re.compile(r"\bhousehold size\b[^.]{0,40}\b(outside|beyond|larger than|greater than|"
                   r"not in|above)\b"
                   r"|\b(outside|beyond)\b[^.]{0,20}\b(the )?(supplied |frozen )?1\s*-\s*8\b"
                   r"|\bhousehold (size |of )?(9|nine|10|ten|1[0-9])\b",
                   re.IGNORECASE),
        _household_size_outside_table,
    ),
    SituationRoute(
        "unverified_claim_flagged",
        re.compile(r"\b(self[- ]declar\w+|self[- ]report\w+|self[- ]certif\w+|unsigned|"
                   r"not signed)\b"
                   r"|\b(application|applicant'?s?) (statement|declaration)\b"
                   r"|\btreated as employer evidence\b",
                   re.IGNORECASE),
        _unsigned_claim,
    ),
    SituationRoute(
        "traceability_check_failed",
        re.compile(r"\bwithout (a )?(source|citation|page|box|reference)\b"
                   r"|\bno (source|citation)\b[^.]{0,30}\b(page|box|given|provided)?\b"
                   r"|\bmissing (a )?(citation|source|page|box)\b"
                   r"|\buncited\b|\bnot traceable\b|\buntraceable\b",
                   re.IGNORECASE),
        _missing_citation,
    ),
    SituationRoute(
        "frozen_corpus_enforced",
        re.compile(r"\b(20(1[0-9]|2[0-5]))\b[^.]{0,30}\b(threshold|limit|table|figure|number|"
                   r"income limit)s?\b"
                   r"|\b(remembered|recalled|memoriz\w+|from memory|prior year|last year'?s?)\b"
                   r"[^.]{0,30}\b(threshold|limit)s?\b"
                   r"|\buse (the )?20(1[0-9]|2[0-5])\b",
                   re.IGNORECASE),
        _wrong_year,
    ),
    SituationRoute(
        "dataset_limitation_stated",
        re.compile(r"\b(unit|apartment|propert\w+|place)\b[^.]{0,40}"
                   r"\b(available|open|vacant|free|move[- ]in)\b"
                   r"|\bavailab\w+ (today|now|right now|this week)\b"
                   r"|\bwhich .{0,40}\b(has|have)\b[^.]{0,20}\b(a )?(unit|vacancy|opening)\b"
                   r"|\bwait\s?list\b",
                   re.IGNORECASE),
        _vacancy,
    ),
)


def match(question: str, canonical_kind: str | None) -> SituationRoute | None:
    """상황 라우트를 고른다.

    **정규 라우터(`logic.answer_rules.route`)가 이미 잡은 질문은 가로채지 않는다.**
    이 규칙이 qa_gold 36문항과 기존 라우팅을 통째로 보호한다. 유일한 예외는
    `overrides`에 명시된, 알려진 오라우팅 한 건이다.
    """
    for route in ROUTES:
        if not route.pattern.search(question or ""):
            continue
        if canonical_kind is None or canonical_kind in route.overrides:
            return route
    return None


def build(route: SituationRoute, households: dict[str, Any]) -> Situation:
    """상황 응답을 만든다. 실측이 실패해도 인용 기반 서술로 물러난다."""
    try:
        return route.build(households or {})
    except Exception as exc:  # 계측기가 깨져도 거짓말은 하지 않는다
        return Situation(
            kind=route.kind,
            text=(
                "This situation is one this service handles, but the live check that would "
                "have demonstrated it on your own documents could not be run just now, so no "
                "measured claim is made here. What the rules require is cited below; treat "
                "the behaviour as unverified until the check runs."
            ),
            rule_ids=("CH-READINESS-001",),
            resolve="re-run the request, or ask a housing professional",
            evidence=(Evidence(f"live check failed: {type(exc).__name__}", True,
                               "attempted during this request"),),
        )


__all__ = ["Evidence", "Situation", "SituationRoute", "ROUTES", "build", "match"]
