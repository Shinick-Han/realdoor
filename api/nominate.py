# -*- coding: utf-8 -*-
"""
nominate.py — 문서 종류를 **페이지가 스스로 인쇄한 제목**에서 지명한다.

이 제품의 명제는 "기계가 근거를 대고, 사람이 확인한다" 이다. 지금까지 문서 종류만은
그 명제 밖에 있었다: 페이지 맨 위에 "Earnings Statement" 라고 인쇄돼 있는데도
사람에게 먼저 물었다. 이 모듈이 그 마지막 질문을 명제 안으로 들여온다 —
**기계가 인쇄된 증거에서 지명하고, 사람이 확인한다.** 지명은 항상 근거(일치한
인쇄 문구 + 페이지/좌표)와 함께 나가고, 화면은 그 근거를 한 문장으로 보여 주며
한 번의 클릭으로 바꿀 수 있게 한다.

어떻게 지명하는가 — 그리고 왜 이 모양인가
─────────────────────────────────────────────────────────────────────────────
* **닫힌 표, 완전 일치.** `NOMINATION_TABLE` 은 손으로 적은 닫힌 집합이고, 조회는
  제목 영역의 런(run) 전체를 정규화(대문자·공백 접기)한 뒤의 **사전 완전 일치**다.
  부분 문자열 검색도, 유사도 점수도 없다. `core/extract.py` 의 LABEL_MAP 과 같은
  종류의 물건이다: 표에 없는 것은 지명되지 않고, 지명되지 않으면 사람에게 묻는다.
* **제목 영역만 본다.** 1페이지 상단 28% 의 텍스트 런만 후보다. 문서가 자기 종류를
  선언하는 자리는 제목이지 본문이 아니고, 본문까지 넓히면 아래의 위험이 커진다.

⚠️ 이름을 붙여 둔 위험: **종류 단어를 인쇄하지만 그 종류가 아닌 문서.**
─────────────────────────────────────────────────────────────────────────────
이 저장소에 살아 있는 반례가 둘 있다:
  * testdata/confirm_raw/md_labor_paystatement_template_instructions.pdf —
    급여명세서에 **대한 안내문**. "Pay Statement" 라는 단어를 여러 번 인쇄한다.
  * testdata/confirm_raw/lcc_understanding_your_paycheck.pdf —
    급여명세서를 읽는 법을 가르치는 **해설서**. "Pay Check/Stub" 을 제목에 인쇄한다.
둘 다 급여명세서가 아니다. 방어는 완전 일치 그 자체다: 이런 문서의 제목은
"Understanding Your Pay Check/Stub", "... Template - Instructions" 처럼 **수식어가
붙은 런**이고, 런 전체 완전 일치에서는 수식어가 곧 불일치다. 그래서 표에는
"SAMPLE ...", "UNDERSTANDING ...", "... INSTRUCTIONS" 류의 문구를 절대 넣지 않는다 —
어떤 종류에 **대한** 페이지는 같은 명사를 수식어와 함께 인쇄하기 때문이다.
그래도 잘못 지명될 수는 있다. 그때의 안전망은 표시다: 지명은 항상 일치한 인쇄
문구와 함께 화면에 나가고(api/app.py 가 `nomination` 을 응답에 싣는다), 세입자가
한 번의 클릭으로 바꿀 수 있다. **보이는 오지명은 수용하고, 조용한 오지명은
수용하지 않는다** — 그래서 근거 문장은 선택이 아니라 필수다.

측정 (api/test_nominate.py 가 세 말뭉치 전체에 대해 고정한다)
─────────────────────────────────────────────────────────────────────────────
pack 24 + testdata/uploads 26 + testdata/confirm_raw 14 에 대해: 오지명 0 건.
표가 놓치는 문서(제목이 자신을 선언하지 않는 실물 급여명세서 등)는 지명 없이
사람에게 묻는 오늘까지의 동작으로 떨어진다 — 놓침은 질문이 되고, 질문은 실패가
아니다.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pdfplumber

from core.extract import _join_run, _split_runs, group_lines, read_words

#: 1페이지에서 제목으로 인정하는 영역: 상단 28%. 실측으로 고른 값이다 —
#: 세 말뭉치의 자기 선언 제목은 전부 이 안에 있고(회사명·문서 id 와 함께),
#: 이보다 넓히면 본문의 라벨("EMPLOYMENT VERIFICATION" 항목 제목 등)이 후보로
#: 들어오기 시작한다.
TITLE_REGION_FRACTION = 0.28

#: 인쇄된 제목 문구(정규화 후) → 문서 종류. **닫힌 표.**
#:
#: 모든 항목은 세 말뭉치에서 실제로 관측된 인쇄 문구다. 지어낸 유의어는 없다 —
#: 표를 넓히고 싶으면 그 문구가 실제 문서에 인쇄된 것을 보인 다음에 넣는다.
#: 값의 종류 집합은 core.extract.EXPECTED_FIELDS 의 키 집합과 같아야 하며
#: (api/test_nominate.py 가 고정), 그래서 지명된 종류는 항상 읽을 줄 아는 종류다.
NOMINATION_TABLE: dict[str, str] = {
    # ── application_summary ── (pack, testdata/uploads)
    "APPLICATION SUMMARY": "application_summary",
    # ── pay_stub ──
    "PAY STUB": "pay_stub",                       # pack
    # 괄호는 임금 산정 방식(시급제)을 말할 뿐 장르를 바꾸지 않는다. "SAMPLE"/
    # "UNDERSTANDING" 같은 장르 수식어와 달리, 이 문구가 붙은 페이지는 여전히
    # 급여명세서 자신이다 (confirm_raw/ca_dlse_paystub_hourly.pdf 에서 관측).
    "PAY STUB (HOURLY)": "pay_stub",
    "EARNINGS STATEMENT": "pay_stub",             # testdata/uploads, il_dol 실물
    "STATEMENT OF EARNINGS": "pay_stub",          # up_017
    # ── employment_letter ──
    "EMPLOYMENT LETTER": "employment_letter",     # pack
    "EMPLOYMENT VERIFICATION": "employment_letter",   # up_018, 실물 서식 3종
    "VERIFICATION OF EMPLOYMENT": "employment_letter",  # up_007, up_008
    # ── benefit_letter ──
    "BENEFIT LETTER": "benefit_letter",           # pack
    "BENEFIT AWARD NOTICE": "benefit_letter",     # up_009, up_025
    # ── gig_statement ──
    "GIG STATEMENT": "gig_statement",             # pack
    # 급여명세서의 어휘와 겹쳐 보이지만, 관측된 용례(up_011, up_012)는 모두 긱
    # 플랫폼의 월간 명세다. 완전 일치라 "EARNINGS STATEMENT"(pay_stub)와는
    # 절대 섞이지 않는다. 틀리면 화면의 근거 문장이 보이는 오지명으로 만든다.
    "MONTHLY EARNINGS STATEMENT": "gig_statement",
}


def _normalize(text: str) -> str:
    """대문자 + 공백 접기. 이 이상은 하지 않는다 — 구두점 제거나 어간 추출을
    시작하는 순간 '완전 일치'가 조용히 유사도 검색이 된다."""
    return " ".join(str(text).split()).upper()


def nominate(data: bytes) -> tuple[dict[str, Any] | None, str]:
    """올린 PDF 바이트에서 문서 종류 지명을 시도한다.

    반환: (nomination, reason)
      nomination  {"document_type", "matched_text", "page", "bbox"} — 근거 포함.
                  bbox 는 추출 필드와 같은 관례([x0, y0, x1, y1], PDF 포인트,
                  좌하단 원점)라 화면이 같은 좌표 기계로 다룰 수 있다.
      reason      지명이 없을 때 왜 없는지:
                    "matched"             지명 있음
                    "no_text_layer"       1페이지에 읽을 텍스트가 없다(스캔본).
                                          OCR 로는 지명하지 않는다 — 인식 오류가
                                          섞인 문자열의 완전 일치는 측정된 적이
                                          없고, 이 표는 인쇄된 글자를 전제한다.
                    "no_title_match"      제목 영역의 어떤 런도 표에 없다
                    "conflicting_titles"  서로 다른 종류의 문구가 함께 인쇄돼
                                          있다 — 고르는 것은 추측이므로 묻는다

    호출자는 이미 PDF 매직바이트를 검사했다(api/upload.py). 여기서 열기에
    실패하면 그건 손상된 파일이고, 그 판정은 업로드 본 경로가 한다 — 지명은
    조용히 포기하고 사람에게 묻는 쪽으로 떨어진다.
    """
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return None, "no_text_layer"
            page = pdf.pages[0]
            height = float(page.height)
            words = read_words(page, 1)
    except Exception:
        return None, "no_text_layer"
    if not words:
        return None, "no_text_layer"

    floor = height * (1.0 - TITLE_REGION_FRACTION)
    title_words = [w for w in words if w.baseline >= floor]
    if not title_words:
        return None, "no_title_match"

    matches: list[dict[str, Any]] = []
    for line in group_lines(title_words):
        for run in _split_runs(line):
            doc_type = NOMINATION_TABLE.get(_normalize(_join_run(run)))
            if doc_type is None:
                continue
            matches.append({
                "document_type": doc_type,
                "matched_text": _join_run(run),
                "page": 1,
                "bbox": [
                    round(min(w.x0 for w in run), 2),
                    round(min(w.glyph_bottom for w in run), 2),
                    round(max(w.x1 for w in run), 2),
                    round(max(w.glyph_top for w in run), 2),
                ],
            })

    if not matches:
        return None, "no_title_match"
    types = {m["document_type"] for m in matches}
    if len(types) > 1:
        # 페이지가 두 가지 종류를 선언한다. 어느 쪽인지 고르는 것은 인쇄된 증거를
        # 읽는 일이 아니라 가중치를 매기는 일이고, 그건 이 모듈이 하지 않기로 한
        # 바로 그것이다(no fuzzy scoring). 사람에게 묻는다.
        return None, "conflicting_titles"
    # 같은 종류가 여러 번 인쇄됐으면(il_dol 처럼 제목이 두 번 찍히는 문서가 실재한다)
    # 가장 위의 것 — group_lines 가 위에서 아래로 돌므로 첫 번째 — 을 근거로 든다.
    return matches[0], "matched"
