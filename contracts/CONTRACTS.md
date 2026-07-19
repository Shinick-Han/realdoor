# CONTRACTS — 동결 (2026-07-19 04:25 KST)

⚠️ **이 파일이 동결된 뒤에야 병렬 스트림이 시작된다.**
UI(Lovable)와 코어는 이 계약만 보고 서로를 모른 채 병렬로 만들어진다.
변경이 필요하면 **지휘자만** 바꾸고, 모든 스트림에 즉시 통지한다.

---

## 0. 절대 규칙 (계약보다 상위)

브리프 원문: *"A submission that **approves, denies, scores, ranks, silently suppresses**
options, or exposes sensitive data **cannot win regardless of model quality**."*

따라서 **어떤 응답에도 다음 필드가 존재해서는 안 된다**:
`eligible`, `approved`, `denied`, `score`, `rank`, `priority`, `qualified`, `recommendation`.

허용되는 상태값은 아래 열거형뿐이다. 코어는 이 금지어를 **테스트로 강제**한다
(`eval/test_no_decision.py`).

---

## 1. 열거형 (팩의 `submission.schema.json`에서 파생 — 임의 확장 금지)

```
Comparison      = "below_or_equal" | "above" | "no_frozen_threshold"
ReadinessStatus = "READY_TO_REVIEW" | "NEEDS_REVIEW"
EvidenceKind    = "extracted" | "confirmed_by_renter" | "corrected_by_renter"
Certainty       = "high" | "low" | "abstain"
ItemState       = "present" | "missing" | "expired" | "undatable" | "unreadable"
```

### 개정 이력 (04:55) — 팩에 없는 값 제거
- ~~`expiring_soon`~~ **삭제.** 팩 어디에도 "soon"의 임계가 없다. 우리가 임계를 만들면
  그건 **인용 없는 규칙**이고, 우리가 하지 말자고 한 바로 그 짓이다. UI에 남은 일수를
  숫자로 보여주는 것으로 충분하다.
- `undatable` **신설.** 문서를 읽는 데는 성공했으나 날짜 정밀도가 부족한 경우
  (예: gig statement의 `statement_month = "2026-06"` — 일(日)이 없음).
  `unreadable`로 뭉뚱그리면 "우리가 못 읽었다"는 거짓 신호가 된다.
  **일자를 지어내지 않고, 못 읽었다고도 말하지 않는다.**

`no_frozen_threshold` 와 `abstain` 이 **기권 슬롯**이다. 불확실하면 여기로 간다.

---

## 2. `ExtractedField` — 추출된 필드 1건

```json
{
  "field": "person_name",
  "value": "Mara North",
  "page": 1,
  "bbox": [40, 648, 94.01, 662],
  "bbox_units": "pdf_points_bottom_left_origin",
  "certainty": "high",
  "evidence_kind": "extracted",
  "source_text": "Mara North",
  "notes": null
}
```
- `bbox`는 팩 gold와 **동일 좌표계**(PDF points, 좌하단 원점). UI는 이걸로 오버레이를 그린다.
- `certainty="abstain"`이면 `value`는 `null`이고 UI는 **사람에게 입력을 요구**한다.

## 3. `DocumentView` — 문서 1건

```json
{
  "document_id": "HH-001-D01",
  "household_id": "HH-001",
  "document_type": "application_summary",
  "file_name": "hh-001_d01_application_summary.pdf",
  "page_count": 1,
  "page_size_points": [612, 792],
  "fields": [ ExtractedField, ... ],
  "document_date": "2026-07-10",
  "state": "present",
  "days_until_stale": 52,
  "stale_rule_id": "CH-READINESS-001"
}
```

### ⚠️ 신선도 규칙 — 팩이 동결한 값만 쓴다
```
REFERENCE_DATE = 2026-07-18          # 이벤트 날짜. 오늘(07-19)이 아니다.
CURRENCY_WINDOW_DAYS = 60            # 팩 RULES_README 동결 관행
→ 문서가 current 하려면 document_date >= 2026-05-19
```
출처: `pack/rules/RULES_README.md` — *"A document is current for this simulation when dated
no more than **60 days** before 2026-07-18. **This is a challenge convention, not a universal
LIHTC rule.**"* 및 `CH-READINESS-001` (*"current under the challenge's 60-day convention"*).

🚫 **실제 HUD 규정(4350.3의 120일 검증 유효기간)을 쓰지 마라.** 그것은 현실에서는 맞지만
이 과제에서는 **틀린 답**이다. 채점은 동결된 관행 기준으로 이뤄진다.
*(이 항목은 최초 계약 작성 시 지휘자가 외부 사전지식으로 120일을 잘못 기입했다가 팩 원문
대조에서 발견해 정정한 것이다. 인용 없는 지식이 인용된 출처를 덮어쓴 사례로 기록해 둔다.)*

## 4. `RuleCitation` — 모든 주장에 붙는 근거

```json
{
  "rule_id": "HUD-MTSP-002",
  "authority": "official_hud",
  "effective_date": "2026-05-01",
  "text": "For the Boston-Cambridge-Quincy, MA-NH HMFA ...",
  "source_url": "https://www.huduser.gov/portal/datasets/mtsp/...",
  "source_locator": "PDF page 130",
  "verified_against_source": null
}
```
- `verified_against_source`: `true|false|null`. **tavily로 원문을 실제 확인했는지.**
  null = 미확인. 우리가 확인한 것만 true. **여기서 거짓말하면 우리 논지가 죽는다.**

## 5. `Calculation` — 결정론 계산 1건

```json
{
  "name": "annualized_income",
  "inputs": [{"label": "gross_pay", "value": 1500.0, "from_document": "HH-001-D02"},
             {"label": "frequency", "value": "biweekly", "from_document": "HH-001-D02"}],
  "formula": "amount * 26",
  "result": 39000.0,
  "threshold": 72000.0,
  "threshold_rule_id": "HUD-MTSP-002",
  "comparison": "below_or_equal",
  "effective_date": "2026-05-01"
}
```
- `threshold`가 없으면 `comparison="no_frozen_threshold"` 이고 `threshold=null`.
- **이 계산은 순수함수다.** LLM이 관여하지 않는다.

## 6. `ChecklistItem` — 준비도 항목 1건

⚠️ `required_because_rule_id`는 **팩의 11개 규칙 ID 중 하나여야 한다.**
(`CH-DOC-STUBS`는 존재하지 않는 ID였다 — 지휘자가 지어낸 것으로, 아래 예시에서 정정했다.
필요 서류의 근거는 `pack/evaluation/application_checklists.json`과 `CH-READINESS-001`이다.)

```json
{
  "item_id": "CHK-PAYSTUB",
  "label": "Recent pay stubs",
  "required_because_rule_id": "CH-READINESS-001",
  "state": "missing",
  "satisfied_by": [],
  "detail": "0 of 2 required pay stubs found",
  "action_for_renter": "Upload your two most recent pay stubs"
}
```

## 7. `ReadinessReport` — **UI가 렌더링하는 최상위 객체**

```json
{
  "household_id": "HH-001",
  "generated_at": "2026-07-19T04:25:00Z",
  "ruleset_version": "pack-v1/2026-05-01",
  "readiness_status": "NEEDS_REVIEW",
  "documents": [ DocumentView, ... ],
  "calculations": [ Calculation, ... ],
  "checklist": [ ChecklistItem, ... ],
  "citations": [ RuleCitation, ... ],
  "abstentions": [
    {"about": "annualized_income", "reason": "pay frequency not stated on document",
     "what_would_resolve_it": "renter confirms pay frequency"}
  ],
  "human_decision_notice": "This is not an eligibility decision. A qualified housing professional must decide.",
  "engine_version": "sha:<git short sha>"
}
```

**`abstentions` 배열이 제품의 핵심이다.** 비어 있으면 안 된다는 뜻이 아니라,
**모르는 것을 숨기지 않는다**는 뜻이다. UI는 이걸 반드시 표시한다.

---

## 8. API 표면 (FastAPI, `api/`)

| 메서드 | 경로 | 반환 |
|---|---|---|
| GET | `/api/households` | `[{household_id, document_count}]` |
| GET | `/api/report/{household_id}` | `ReadinessReport` |
| POST | `/api/confirm` | `{household_id, field, value}` → 갱신된 `ReadinessReport` |
| GET | `/api/document/{document_id}/page/{n}.png` | 렌더된 페이지 이미지 (bbox 오버레이용) |
| POST | `/api/packet/{household_id}` | 패킷 zip |
| DELETE | `/api/session/{household_id}` | `{deleted: true}` — 세션 삭제 시연용 |
| GET | `/api/selftest` | 우리 자체 평가 결과 (아래 §9) |

## 9. `/api/selftest` — **우리 제품의 자기 성적표**

```json
{
  "extraction": {"fields_total": 96, "exact_match": 91, "accuracy": 0.948,
                 "abstained": 3, "wrong": 2},
  "adversarial": {"total": 24, "passed": 24, "failed": []},
  "calculations": {"total": 6, "verified_against_pack_starter": 6},
  "accessibility": {"tool": "axe-core", "violations": 0, "checked_pages": 3},
  "citations": {"total": 11, "verified_against_live_source": 0},
  "generated_at": "..."
}
```
**이 엔드포인트가 데모의 마지막 화면이다.** 남들은 "잘 됩니다"라고 말하고,
우리는 이 숫자를 띄운다. 숫자가 나쁘면 나쁜 대로 띄운다.

---

## 10. 스트림 소유권 (충돌 0 규율)

| 스트림 | 소유 디렉토리 | 산출물 |
|---|---|---|
| **A. 코어** | `core/` | 추출·계산·규칙·체크리스트·기권 (순수함수) |
| **B. 평가** | `eval/` | gold 대조, adversarial 24건 하네스, no-decision 테스트 |
| **C. API** | `api/` | FastAPI, 위 계약 그대로 서빙 |
| **D. UI** | `ui/` | Lovable 생성물 + axe-core 검사 |
| **E. 제출물** | `docs/` | 영상 대본 3편, summary 150-300단어, README |

**남의 디렉토리에 쓰지 않는다.** 계약 변경이 필요하면 지휘자에게 보고.
