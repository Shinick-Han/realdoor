# -*- coding: utf-8 -*-
"""
region.py — 세입자가 페이지 위에 직접 그린 사각형 하나를 읽는다.

인라인 정정 편집기의 "Point at it on the page" 가 이 모듈을 부른다. 세입자가 페이지
이미지 위에 사각형을 끌어 그리면, 서버는 **그 사각형 안의 픽셀만** 잘라 인식기에 넣고
읽은 문자열과 신뢰도를 돌려준다. 그 결과는 화면에서 **제안**으로만 쓰인다 — 입력칸에
채워질 뿐, 세입자가 저장을 누르기 전에는 아무것도 기록되지 않는다.

이것이 신원 게이트의 영역이 아닌 이유
─────────────────────────────────────────────────────────────────────────────
추출 경로의 안전 규칙(CH-SAFETY-001)은 "기계가 스스로 고른 위치"를 제한한다 — 라벨을
먼저 알아보고 그 아래만 읽는다. 여기서는 위치를 고르는 것이 기계가 아니라 **사람**이다.
세입자가 자기 문서의 한 곳을 손으로 가리켰고, 기계는 그 픽셀을 읽어 주는 돋보기 역할만
한다. 읽은 값은 자동으로 어디에도 들어가지 않고, 정정 커밋은 기존 확인·정정 경로
(`/api/confirm`)를 그대로 거친다.

안전 규칙 (전부 이 파일 안에서 강제된다)
─────────────────────────────────────────────────────────────────────────────
* **세션의 문서만.** `document_id` 는 그 세션의 팩 사본이나 업로드 중 하나여야 한다.
  다른 세션의 업로드는 여기서 보이지 않는다 — 404.
* **경계는 페이지 안.** 사각형은 [x0, y0, x1, y1] PDF 포인트(왼쪽-아래 원점)이고,
  페이지 크기를 벗어나면 400 이다. 잘라낸 다음 조용히 맞춰 주지 않는다 — 화면과
  서버가 서로 다른 사각형을 두고 이야기하게 되기 때문이다.
* **크기 상한.** 페이지의 4분의 1을 넘는 사각형은 거절한다. 이 도구는 값 하나를
  읽는 돋보기이지 페이지 전체 OCR 이 아니고, 상한이 없으면 공개 URL 에서 렌더링과
  인식 비용을 무한히 시킬 수 있다. 렌더 픽셀도 별도로 상한이 있다.
* **디스크에 쓰지 않는다.** 업로드는 세션 메모리의 바이트에서, 팩 문서는 팩 디렉터리의
  원본에서 바로 렌더한다. 어느 쪽도 파일을 만들지 않는다.

인식은 `ocr/` 의 기존 경로를 그대로 쓴다: 잘라낸 조각을 RapidOCR 에 넣고
(탐지+인식, 빈손이면 인식 단독 재시도 — `ocr/ocr_extract.py::_recognize_line` 과 같은
이유: 한 줄짜리 조각에는 더 탐지할 것이 없다), 신뢰도가 보정된 바닥
(`ocr.ocr_extract.LOW_CONFIDENCE`) 아래면 제안을 내지 않는다. 필드 이름이 오면
`core.extract.parse_value` 로 그 필드의 문법에 맞는지 확인하고, 맞지 않으면 역시
제안을 내지 않는다 — 낮은 확신의 제안은 미리 채워진 입력칸이 하는 앵커링을 그대로
하기 때문에, 확신이 없으면 빈 입력칸이 정직한 답이다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException

#: 사각형의 최소 변 길이(PDF 포인트). 이보다 작으면 클릭이지 영역이 아니다.
MIN_SIDE_POINTS = 4.0

#: 사각형이 페이지 넓이에서 차지할 수 있는 최대 비율. 이 도구는 값 하나를 읽는
#: 돋보기다 — 페이지의 4분의 1이면 표 하나는 넉넉히 들어가고, 그보다 큰 요청은
#: 페이지 전체를 다시 OCR 시키려는 것이므로 거절한다.
MAX_PAGE_FRACTION = 0.25

#: 렌더된 조각의 긴 변 픽셀 상한. `ocr/ocr_extract.py` 가 잰 대로 인식기는 어차피
#: 자기 입력 상한(max_side_len)으로 줄여 버리므로, 그보다 큰 렌더는 비용만 낸다.
MAX_CROP_SIDE_PX = 1400

#: 렌더 배율 상한/하한 (px per pt). 작은 사각형일수록 크게 렌더해야 인식이 산다 —
#: `ocr/ocr_extract.py::_recognize_line` 이 같은 이유로 전체 페이지 배율 대신
#: 조각 단독 렌더를 쓴다.
MAX_SCALE = 8.0
MIN_SCALE = 2.0


def _bad(code: str, message: str) -> HTTPException:
    return HTTPException(400, {"code": code, "detail": message})


def resolve_document(session: Any, document_id: str) -> tuple[Any, dict[str, Any]]:
    """(pdf_source, view) — 이 세션이 쥐고 있는 문서만 나온다. 없으면 404."""
    from api.store import DOCS

    view = session.uploads.get(document_id)
    if view is not None:
        data = session.upload_bytes.get(document_id)
        if data is None:
            raise HTTPException(404, f"unknown document {document_id}")
        return data, view
    view = session.views.get(document_id)
    if view is not None:
        return str(DOCS / view["file_name"]), view
    raise HTTPException(404, f"unknown document {document_id}")


def validate_region(view: dict[str, Any], page: Any, box: Any) -> tuple[int, list[float]]:
    """페이지 번호와 사각형을 검증해 (page, [x0, y0, x1, y1]) 로 돌려준다.

    실패는 전부 400 이고, 무엇이 왜 안 되는지 문장으로 말한다. 잘라 맞춰 주지 않는다.
    """
    try:
        page_number = int(page)
    except (TypeError, ValueError):
        raise _bad("bad_page", "`page` must be a whole number.") from None
    page_count = int(view.get("page_count") or 1)
    if not 1 <= page_number <= page_count:
        raise _bad("bad_page",
                   f"page {page_number} is not in this document "
                   f"({page_count} page(s)).")

    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise _bad("bad_box", "`box` must be [x0, y0, x1, y1] in PDF points.")
    try:
        x0, y0, x1, y1 = (float(v) for v in box)
    except (TypeError, ValueError):
        raise _bad("bad_box", "`box` must hold four numbers.") from None
    if not all(v == v and abs(v) != float("inf") for v in (x0, y0, x1, y1)):
        raise _bad("bad_box", "`box` must hold four finite numbers.")

    size = view.get("page_size_points") or [612.0, 792.0]
    page_w, page_h = float(size[0]), float(size[1])
    if x0 < 0 or y0 < 0 or x1 > page_w or y1 > page_h:
        raise _bad("box_outside_page",
                   f"That box goes off the page. The page is {page_w} x {page_h} "
                   f"points and the box must sit inside it.")
    if x1 - x0 < MIN_SIDE_POINTS or y1 - y0 < MIN_SIDE_POINTS:
        raise _bad("box_too_small",
                   "That box is too small to read. Drag a rectangle around the value.")
    if (x1 - x0) * (y1 - y0) > MAX_PAGE_FRACTION * page_w * page_h:
        raise _bad("box_too_large",
                   "That box covers too much of the page. Drag a smaller box around "
                   "just the one value.")
    return page_number, [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]


def _read_crop(pdf_source: Any, page_number: int, box: list[float],
               page_h: float) -> tuple[str | None, float | None, list[tuple[str, float]]]:
    """사각형 안을 렌더해 읽는다. (합쳐 읽은 문자열, 최저 신뢰도, 조각들) — 못 읽으면
    (None, None, []).

    렌더는 `core.ocr_words._render_region` 을 그대로 쓴다 — 조각만 렌더하므로 메모리가
    조각 크기에 묶이고, 여백 처리(경계 글리프)가 이미 검증돼 있다. 그 함수의 rect 는
    pdfplumber 관례(위에서 잰 top/bottom)라서 여기서 좌표계를 한 번 뒤집는다.

    조각들(각 탐지의 문자열과 신뢰도)을 함께 돌려주는 이유: 사람이 그리는 사각형은
    값만 담지 않는다 — 라벨이 반쯤 걸쳐 들어오는 것이 보통이고, 그러면 합쳐 읽은
    문자열은 필드 문법에 맞지 않는다. 그때 조각 단위의 재시도가 값을 건진다
    (`read_region` 의 파스 사다리).
    """
    import numpy as np

    from core.ocr_words import _render_region
    from ocr.ocr_extract import _engine

    x0, y0, x1, y1 = box
    rect = [x0, page_h - y1, x1, page_h - y0]      # bottom-left → top-based
    long_side = max(x1 - x0, y1 - y0)
    scale = max(MIN_SCALE, min(MAX_SCALE, MAX_CROP_SIDE_PX / long_side))

    image, _, _ = _render_region(pdf_source, page_number, rect, scale)
    if image is None or image.width < 4 or image.height < 4:
        return None, None, []

    pixels = np.array(image)
    result, _ = _engine()(pixels)
    if not result:
        # 한 줄짜리 조각에서 탐지기가 빈손으로 오는 일이 있다. 인식 단독으로 한 번 더 —
        # `_recognize_line` 이 같은 상황에 쓰는 경로다.
        result, _ = _engine()(pixels, use_det=False, use_cls=False, use_rec=True)
        if not result:
            return None, None, []
        text = str(result[0][0]).strip()
        confidence = float(result[0][1]) if len(result[0]) > 1 else 0.0
        return (text or None), confidence, ([(text, confidence)] if text else [])

    rows: list[tuple[float, float, str, float]] = []
    for quad, text, confidence in result:
        cleaned = str(text).strip()
        if not cleaned:
            continue
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        rows.append((min(ys), min(xs), cleaned, float(confidence)))
    if not rows:
        return None, None, []
    # 읽는 순서: 위에서 아래로, 왼쪽에서 오른쪽으로. 세로가 겹치는 조각은 한 줄로 본다.
    rows.sort(key=lambda r: (round(r[0] / 10.0), r[1]))
    joined = " ".join(r[2] for r in rows)
    return joined, min(r[3] for r in rows), [(r[2], r[3]) for r in rows]


#: 실패했을 때 화면이 그대로 옮겨 적는 한 문장. 제안은 없고, 입력칸은 계속 열려 있다.
COULD_NOT_READ = "We could not read that area — type what it says."

#: 성공했을 때도 같이 나가는 경계 문장. 제안은 제안일 뿐이다.
SUGGESTION_NOTE = ("This is a suggestion read from the box you drew. Check it against "
                   "the page. Nothing is saved until you choose to save it.")


def read_region(session: Any, document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """한 사각형을 읽어 제안을 만든다. 제안이 없으면 그렇게 말한다."""
    from core.extract import ParseError, parse_value
    from ocr.ocr_extract import LOW_CONFIDENCE, _clean_value_text

    pdf_source, view = resolve_document(session, document_id)
    page_number, box = validate_region(view, payload.get("page"), payload.get("box"))
    size = view.get("page_size_points") or [612.0, 792.0]

    base = {"document_id": document_id, "page": page_number, "box": box}

    text, confidence, pieces = _read_crop(pdf_source, page_number, box, float(size[1]))
    if text is None or confidence is None or confidence < LOW_CONFIDENCE:
        return {**base, "could_read": False, "reading": None, "source_text": text,
                "confidence": None if confidence is None else round(confidence, 3),
                "note": COULD_NOT_READ}

    reading: Any = text
    field_name = payload.get("field")
    if field_name:
        # 파스 사다리. 그 필드의 문법으로 읽혀야 제안이 된다 — "$2,166.00" → 2166.0
        # 처럼 표기가 정규화되고, 문법에 맞지 않으면 제안이 없다.
        #
        # 1단: 합쳐 읽은 전체. 2단: 조각 하나씩 — 사람이 그린 사각형에는 라벨이 반쯤
        # 걸쳐 들어오는 것이 보통이라("GROSS PAY 440.00"), 전체는 문법에 안 맞아도
        # 조각 하나는 맞는다. 서로 다른 두 값이 파스되면 어느 쪽인지 **모르는** 것이므로
        # 제안하지 않는다 — 애매한 제안은 미리 채워진 오답과 같은 앵커다.
        def _try(raw: str) -> Any | None:
            try:
                value, _ = parse_value(str(field_name),
                                       _clean_value_text(str(field_name), raw))
                return value
            except (ParseError, KeyError):
                return None

        reading = _try(text)
        if reading is None:
            parsed = []
            for piece_text, piece_conf in pieces:
                if piece_conf < LOW_CONFIDENCE:
                    continue
                value = _try(piece_text)
                if value is not None:
                    parsed.append((value, piece_conf))
            distinct = {repr(v) for v, _ in parsed}
            if len(distinct) == 1:
                reading, confidence = parsed[0]
        if reading is None:
            return {**base, "could_read": False, "reading": None, "source_text": text,
                    "confidence": round(confidence, 3), "note": COULD_NOT_READ}

    return {**base, "could_read": True, "reading": reading, "source_text": text,
            "confidence": round(confidence, 3), "note": SUGGESTION_NOTE}
