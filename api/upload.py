# -*- coding: utf-8 -*-
"""
upload.py — 사용자가 올린 한 장의 PDF를 근거와 함께 읽는다.

브리프 Required Build 01 첫 줄이 "Upload synthetic pay stubs or benefit letters" 이고
인수 데모 1번이 "Upload a synthetic document and show extracted evidence" 다.
이 모듈은 그 **한 문장까지만** 한다 — 올린 문서를 읽고 근거를 보여주는 데까지.

의도적으로 하지 않는 것 (그리고 왜)
─────────────────────────────────────────────────────────────────────────────
* **세대 계산에 합류시키지 않는다.** 인수 데모가 요구하는 것은 추출 근거까지다.
  올린 문서를 세대에 편입하려면 (a) 누구의 문서인지 판별하고 (b) 이미 있는 팩 문서와의
  중복을 처리하고 (c) 골드가 없는 문서로 연소득을 다시 계산해야 한다. 셋 다 근거 없이
  추측하는 일이고, 추측은 이 제품이 하지 않기로 한 바로 그것이다. 그래서 업로드 결과는
  자기 자신에 대해서만 말한다.
* **문서 종류를 파일 이름에서 추측하지 않는다.** `core.extract.infer_document_type` 의
  정규식은 팩의 명명 규칙(`hh-001_d01_pay_stub`)에 묶여 있어서, 임의의 파일 이름은
  전부 `unknown` 이 된다. `unknown` 은 오류를 내지 않고 **빈 필드 목록**을 낸다 —
  조용한 실패다. 그래서 종류는 호출자가 **명시적으로** 준다. 못 고르면 업로드도 안 된다.
* **디스크에 쓰지 않는다.** 올린 바이트는 세션 안(메모리)에만 있고 세션이 사라지면
  같이 사라진다. `.cache/extractions` 는 팩 문서용 캐시이며 업로드는 거기 들어가지 않는다.
  "isolated or ephemeral processing" 이 약속이 아니라 구조가 되는 지점이다.

추출 경로 선택
─────────────────────────────────────────────────────────────────────────────
텍스트 레이어가 비어 있으면 `core.extract` 는 **전부 기권한다** — 그게 정직한 동작이지만,
스캔본을 올린 사람에게는 아무것도 못 읽은 것으로 보인다. OCR 전환은 자동이 아니므로
여기서 명시적으로 판단한다: 페이지에 단어가 하나도 없으면 `ocr.extract_document_ocr`.
어느 경로를 탔는지는 응답에 담아서 화면이 말할 수 있게 한다.
"""
from __future__ import annotations

import io
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pdfplumber

from core.extract import EXPECTED_FIELDS, extract_document, read_words

#: 10 MiB. 팩의 합성 문서는 전부 100 KB 미만이므로 넉넉하다. 상한을 두는 이유는
#: 메모리에만 들고 있기 때문이다 — 세션 하나가 프로세스를 굶기면 안 된다.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: PDF 만 받는다. 매직바이트가 진짜 검사이고 MIME 은 보조다 — MIME 은 클라이언트가
#: 자기 마음대로 붙여 보내는 값이라 그것만 믿으면 검사한 척이 된다.
PDF_MAGIC = b"%PDF-"
ACCEPTED_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/octet-stream"})


class UploadRejected(ValueError):
    """올린 파일을 읽을 수 없다. 사용자에게 **왜** 인지 그대로 말해 준다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def supported_document_types() -> list[str]:
    """읽을 줄 아는 문서 종류. `EXPECTED_FIELDS` 에서 **매번 새로 읽는다**.

    하드코딩 사본을 두지 않는 이유: 추출기가 새 종류를 배우면 화면의 선택지도 같이
    늘어나야 하고, 배우지 못한 종류가 선택지에 남아 있으면 안 된다. 사본은 반드시
    한쪽만 갱신되는 날이 온다.
    """
    return sorted(EXPECTED_FIELDS.keys())


def validate(data: bytes, file_name: str, content_type: str | None,
             document_type: str | None) -> str:
    """받아들일 수 있는 업로드인지 확인하고, 정규화된 문서 종류를 돌려준다."""
    if not document_type:
        raise UploadRejected(
            "document_type_required",
            "Choose what kind of document this is. We cannot tell from the file name: "
            "our reader only recognises the pack's own naming convention, and anything "
            "else is read as an unknown type, which produces no fields at all.",
        )
    doc_type = str(document_type).strip().lower()
    if doc_type not in EXPECTED_FIELDS:
        raise UploadRejected(
            "document_type_unsupported",
            f"We do not know how to read a document of type {doc_type!r}. "
            f"We can read: {', '.join(supported_document_types())}.",
        )
    if not data:
        raise UploadRejected("empty_file", "That file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            "file_too_large",
            f"That file is {len(data) / 1048576:.1f} MB. The limit is "
            f"{MAX_UPLOAD_BYTES // 1048576} MB, because an uploaded document is held in "
            f"memory for this session only and never written to disk.",
        )
    if content_type and content_type.split(";")[0].strip().lower() not in ACCEPTED_CONTENT_TYPES:
        raise UploadRejected(
            "not_a_pdf",
            f"This service reads PDF documents only. The browser sent that file as "
            f"{content_type!r}.",
        )
    if not data.startswith(PDF_MAGIC):
        raise UploadRejected(
            "not_a_pdf",
            "That file is not a PDF. Its first bytes are not a PDF header, whatever its "
            "name or type says.",
        )
    return doc_type


def has_text_layer(data: bytes) -> bool:
    """페이지에 실제 단어가 하나라도 있는가.

    `core.extract.read_words` 를 그대로 쓴다 — 나중에 워터마크 필터가 바뀌어도 이 판단과
    추출이 같은 정의를 공유하도록. 스캔본은 여기서 False 가 되고 OCR 로 넘어간다.
    """
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                if read_words(page, page_number):
                    return True
    except Exception as exc:  # 손상된 PDF 는 오류지 기권이 아니다
        raise UploadRejected(
            "unreadable_pdf",
            f"We could not open that PDF ({type(exc).__name__}). It may be damaged or "
            f"password-protected.",
        ) from exc
    return False


def read_upload(data: bytes, file_name: str, document_type: str,
                upload_id: str | None = None) -> dict[str, Any]:
    """올린 바이트 한 덩어리를 `DocumentView` + 업로드 메타데이터로 만든다.

    반환값은 팩 문서의 뷰와 **같은 모양**이다. 화면이 업로드용 시각언어를 따로 발명하지
    않고 기존 근거 표시(페이지 이미지 위 상자 + 필드 표)를 그대로 쓸 수 있어야 하기 때문이다.
    """
    uid = upload_id or f"UP-{uuid.uuid4().hex[:8].upper()}"
    text_layer = has_text_layer(data)

    if text_layer:
        view = extract_document(data, document_type=document_type,
                                file_name=file_name, document_id=uid)
        path_taken = "text_layer"
    else:
        # 텍스트 레이어가 비었다. core 는 여기서 전부 기권하므로 넘기지 않으면 회수가 없다.
        from ocr.ocr_extract import extract_document_ocr

        view = extract_document_ocr(data, document_type=document_type,
                                    file_name=file_name, document_id=uid)
        path_taken = "ocr"

    fields = view.get("fields", [])
    located = [f for f in fields if f.get("certainty") != "abstain"]
    abstained = [f for f in fields if f.get("certainty") == "abstain"]

    view["upload_id"] = uid
    view["source"] = "ocr" if path_taken == "ocr" else "text_layer"
    view["extraction_path"] = path_taken
    view["text_layer_present"] = text_layer
    view["field_count"] = len(fields)
    view["located_count"] = len(located)
    view["abstained_count"] = len(abstained)
    view["read_nothing"] = not located
    # 화면이 이 한계를 그대로 옮겨 적을 수 있도록 서버가 말한다. 추출은 필드 사이의
    # 산술을 하지 않는다 — 시급×시간 ≠ 총액인 명세서도 총액을 high 로 읽는다. 그 모순은
    # 세대 단위 계산(logic/income.py)에서만 드러나고, 업로드는 세대에 합류하지 않는다.
    view["limits"] = [
        "We read each value from the label above it. We do not check the values against "
        "each other, so a document whose own arithmetic disagrees still reads cleanly here.",
        "This document was read on its own. It is not added to any household and it changes "
        "no figure anywhere else in this walkthrough.",
        "Only the document you uploaded most recently is kept. Uploading another replaces "
        "it, and deleting the session removes it with everything else.",
        "Nothing here means approved, denied, or ineligible. A qualified housing "
        "professional makes that determination.",
    ]
    if path_taken == "ocr":
        view["limits"].insert(
            1,
            "This page had no text layer, so it was read by OCR on page 1 only. OCR recovers "
            "fewer fields than a text layer does, and what it cannot read it declines to guess.",
        )
    return view
