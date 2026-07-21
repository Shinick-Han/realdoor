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
  조용한 실패다. 그래서 종류는 두 경로로만 정해진다: 사람이 명시적으로 주거나,
  페이지가 **스스로 인쇄한 제목**에서 지명된다(`api/nominate.py` — 닫힌 표, 완전
  일치, 근거 동봉). 둘 다 아니면 업로드는 이유를 말하고 사람에게 묻는다.
* **디스크에 쓰지 않는다.** 올린 바이트는 세션 안(메모리)에만 있고 세션이 사라지면
  같이 사라진다. `.cache/extractions` 는 팩 문서용 캐시이며 업로드는 거기 들어가지 않는다.
  "isolated or ephemeral processing" 이 약속이 아니라 구조가 되는 지점이다.

추출 경로 선택
─────────────────────────────────────────────────────────────────────────────
텍스트 레이어가 비어 있으면 `core.extract` 는 **전부 기권한다** — 그게 정직한 동작이지만,
스캔본을 올린 사람에게는 아무것도 못 읽은 것으로 보인다. OCR 전환은 자동이 아니므로
여기서 명시적으로 판단한다: 페이지에 단어가 하나도 없으면 `ocr.extract_document_ocr`.
어느 경로를 탔는지는 응답에 담아서 화면이 말할 수 있게 한다.

라벨 모델은 **여기서만** 켠다 (그리고 왜 팩 경로에서는 안 켜는가)
─────────────────────────────────────────────────────────────────────────────
`scripts/measure_label_mapping.py` 가 두 모집단에서 라벨 매핑을 쟀다:

    팩 형태 문서      93.1% → 93.1%   (이득 0)
    hold-out 문서     55.9% → 76.5%   (이득 +20.6pt)   오답은 양쪽 다 0

업로드는 **처음 보는 문서**가 들어오는 유일한 입구다 — 올리는 사람의 PDF 는 우리 팩의
명명 규칙도, 우리 표의 어휘도 따르지 않는다. hold-out 이 바로 그 모집단이고, 이득이
측정된 곳이 여기다. 그래서 이 경로는 `tracking_layered_mapper` 를 쓴다.

팩 경로(`api/store.py`)는 표만 쓴 채로 둔다. 이유는 "네트워크를 피한다"가 아니다 —
캡션만 나가는 구조(`core/label_llm.assert_no_values`)에서 모델 호출 자체는 문제가 아니다.
이유는 **거기서는 이득이 0으로 측정됐다**는 것 하나다. 이득이 0인 자리에 실행마다
흔들릴 수 있는 변수를 넣으면 `scripts/verify.py` 의 157/159 · 90/90 이 실행마다 달라질
수 있고, 그 대가로 얻는 정확도는 없다. **이득이 측정되지 않은 곳에는 변수를 넣지 않는다.**

모델이 켜져 있어도 이 경로가 하는 일은 늘어나지 않는다. `core.extract` 의 3단 순서
(정본 표 → 유의어 표 → 모델)에서 모델은 **두 표가 모두 놓친 라벨에만** 불려 오고,
이름을 댄 뒤에도 값은 바뀌지 않은 기하(열 정렬·`VALUE_Y_WINDOW`·타입 파싱)를 그대로
통과해야 한다. 그래서 모델이 틀리면 오답이 아니라 기권이 된다. 키가 없거나 게이트웨이가
죽어 있으면 `model_mapper` 는 전부 None 을 돌려주고, 이 경로는 표만 쓴 것과 동일하게
동작한다 — 업로드는 실패하지 않는다.

OCR 경로에는 켜지 않는다. `ocr.extract_document_ocr` 는 `fallback_mapper` 를 받지 않고,
OCR 이 읽어 낸 라벨 문자열은 인식 오류를 품고 있어서 hold-out 측정이 다루던 입력이 아니다.
여기서도 원칙은 같다 — 이득이 측정되지 않은 곳에는 넣지 않는다.
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

from core.extract import (
    EXPECTED_FIELDS,
    MODEL_MAPPER_NOTE,
    extract_document,
    read_words,
    tracking_layered_mapper,
)

#: 10 MiB. 팩의 합성 문서는 전부 100 KB 미만이므로 넉넉하다. 상한을 두는 이유는
#: 메모리에만 들고 있기 때문이다 — 세션 하나가 프로세스를 굶기면 안 된다.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: 첫 페이지가 스스로를 밝히지 못할 때(제목 없음·스캔·표에 없는 제목·상충하는 제목)
#: **보이는 기본값**으로 읽는 종류. 가장 흔한 소득 문서인 급여명세서다. 사람이 "읽기"를
#: 눌렀을 때 질문이 아니라 읽기가 돌아 나가야 한다는 것이 이 제품의 일관된 선호이고
#: (api/upload.py 상단 철학), 한 클릭으로 고칠 수 있는 **보이는** 가정이 조용한 가정보다
#: 언제나 낫다. 이 기본값은 결과 옆에 "pay_stub 로 가정했습니다 — 아니면 여기서 바꾸세요"
#: 로 함께 표시되지, 읽기를 막는 관문이 되지 않는다.
DEFAULT_DOCUMENT_TYPE = "pay_stub"

#: PDF 와 이미지(PNG/JPEG)를 받는다. 매직바이트가 진짜 검사이고 MIME 은 보조다 — MIME 은
#: 클라이언트가 자기 마음대로 붙여 보내는 값이라 그것만 믿으면 검사한 척이 된다. 이미지는
#: 도어에서 한 장짜리 PDF 로 감싼 뒤(normalize_to_pdf) 이후 경로가 스캔 PDF 와 **똑같이**
#: 읽는다 — 텍스트 레이어가 없어 OCR 로 가고, 제목이 없어 item 3 의 보이는 기본값으로 읽힌다.
PDF_MAGIC = b"%PDF-"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
IMAGE_MAGICS = (PNG_MAGIC, JPEG_MAGIC)
ACCEPTED_MAGICS = (PDF_MAGIC, *IMAGE_MAGICS)
ACCEPTED_CONTENT_TYPES = frozenset({
    "application/pdf", "application/x-pdf", "application/octet-stream",
    "image/png", "image/jpeg", "image/jpg",
})


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


def validate_bytes(data: bytes, content_type: str | None) -> None:
    """바이트 자체의 검사만 — 종류를 아직 모르는 단계에서도 돌 수 있어야 한다.

    지명(api/nominate.py)은 PDF 를 실제로 열어 읽으므로, 그 전에 여기서 빈 파일·
    크기 상한·매직바이트를 걸러야 한다. `validate` 에서 쪼개 낸 것이고 검사 내용과
    순서는 한 글자도 다르지 않다 — 종류 검사보다 먼저 도는 것만 달라졌다.
    """
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
            f"This service reads PDF, PNG or JPG documents only. The browser sent that file "
            f"as {content_type!r}.",
        )
    if not data.startswith(ACCEPTED_MAGICS):
        raise UploadRejected(
            "not_a_pdf",
            "That file is not a PDF, PNG or JPG. Its first bytes are not one of those "
            "headers, whatever its name or type says.",
        )


def normalize_to_pdf(data: bytes) -> bytes:
    """이미지 업로드(PNG/JPEG)를 **한 장짜리 PDF 로 감싼다**. PDF 는 손대지 않는다.

    도어에서 이미지를 한 번 PDF 로 바꿔 두면, 이 지점 이후로 흐르는 바이트는 언제나 PDF 다 —
    분절(segment_pages)·텍스트 레이어 판정(has_text_layer)·OCR·페이지 렌더가 이미지용 분기를
    새로 두지 않고 스캔 PDF 와 **똑같은 경로**로 돈다. 이미지는 텍스트 레이어가 없으므로
    has_text_layer 가 False → `ocr.extract_document_ocr` 로 가고, 인쇄된 제목도 없으므로 지명이
    실패해 item 3 의 보이는 기본값(pay_stub, 한 클릭으로 고치는 가정)으로 읽힌다. 스캔본을
    올렸을 때와 한 글자도 다르지 않다.

    페이지 크기는 미국 레터(612×792pt)에 맞춘다. OCR 상자 기하(ocr/ocr_extract.py 의 폰트 크기·
    베이스라인 보정)는 레터 페이지에서 잰 값이라, 이미지를 레터 높이(11in)로 매핑해야 렌더된
    페이지 위에서 상자가 글자에 정확히 얹힌다. resolution 을 height/11 로 주면 페이지 높이가 정확히
    792pt 로 떨어지고 너비는 같은 DPI 로 비례하므로 종횡비는 왜곡 없이 보존된다. PDF 는 감싸지
    않고 그대로 돌려주므로 **기존 PDF 업로드는 바이트 단위로 같다**.
    """
    if not data.startswith(IMAGE_MAGICS):
        return data
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.load()  # 손상·잘린 이미지는 여기서 드러난다 (지연 로딩이라 open 만으로는 안 잡힌다)
    except Exception as exc:  # 손상된 이미지는 오류지 기권이 아니다
        raise UploadRejected(
            "unreadable_image",
            f"We could not read that image ({type(exc).__name__}). It may be damaged or "
            f"truncated.",
        ) from exc
    if img.mode not in ("L", "RGB"):
        # 팔레트·알파(P/RGBA/LA 등)는 PDF 저장이 받지 않으므로 RGB 로 편다.
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=max(img.height, 1) / 11.0)
    return buf.getvalue()


def validate(data: bytes, file_name: str, content_type: str | None,
             document_type: str | None) -> str:
    """받아들일 수 있는 업로드인지 확인하고, 정규화된 문서 종류를 돌려준다."""
    if not document_type:
        raise UploadRejected(
            "document_type_required",
            "Choose what kind of document this is. The kind is never taken from the file "
            "name — it comes from the title the page prints at the top, or from your "
            "choice here. Without either, there is no kind to read it as.",
        )
    doc_type = str(document_type).strip().lower()
    if doc_type not in EXPECTED_FIELDS:
        raise UploadRejected(
            "document_type_unsupported",
            f"We do not know how to read a document of type {doc_type!r}. "
            f"We can read: {', '.join(supported_document_types())}.",
        )
    validate_bytes(data, content_type)
    return doc_type


#: 지명 실패의 이유별 문장. 세 문장 모두 같은 다음 걸음("choose the kind")으로
#: 끝난다 — 지명이 없는 업로드는 오류가 아니라 오늘까지의 동작(사람에게 묻기)이다.
_NOT_ANNOUNCED = {
    "no_text_layer": (
        "This page has no text we can read for a title — it looks like a scan — so the "
        "page does not announce what it is. Choose the kind of document below and we "
        "will read it that way."
    ),
    "no_title_match": (
        "The page did not announce what it is: nothing printed at the top of it matches "
        "a kind of document we know. Choose the kind of document below and we will read "
        "it that way."
    ),
    "conflicting_titles": (
        "The page prints titles for more than one kind of document, and choosing "
        "between them would be a guess. Choose the kind of document below and we will "
        "read it that way."
    ),
}


def nominate_or_ask(data: bytes) -> dict[str, Any]:
    """문서 종류를 인쇄된 제목에서 지명한다. 못 하면 **이유를 말하고 묻는다**.

    반환되는 지명에는 근거(일치한 인쇄 문구 + 페이지/좌표)가 붙어 있다. 근거 없는
    지명은 이 함수의 반환형에 존재하지 않는다 — 화면의 근거 문장이 선택이 아니라
    필수인 이유이고, 보이는 오지명(한 클릭에 고칠 수 있는)과 조용한 오지명을
    가르는 선이다. 지명 규칙 전체와 그 위험은 api/nominate.py 에 있다.
    """
    from api import nominate as nominate_mod

    nomination, reason = nominate_mod.nominate(data)
    if nomination is None:
        raise UploadRejected(
            "type_not_announced",
            _NOT_ANNOUNCED.get(reason, _NOT_ANNOUNCED["no_title_match"]),
        )
    return nomination


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


def _page_sizes(data: bytes) -> list[list[float]]:
    """각 페이지의 (폭, 높이) 포인트. 결합 문서는 페이지마다 크기가 다를 수 있고,
    화면이 모든 페이지를 그리려면 페이지별 종횡비가 필요하다."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [[round(float(p.width), 2), round(float(p.height), 2)] for p in pdf.pages]
    except Exception:
        return []


def _split_pdf(data: bytes, page_start: int, page_end: int) -> bytes:
    """원본 PDF 에서 [page_start, page_end] (1-기반, 포함) 페이지만 담은 하위 PDF 바이트.

    페이지 내용 스트림을 그대로 복사하므로 추출 좌표·값이 원본과 **바이트 단위로**
    같다(측정: api/test_upload.py). 렌더는 이 하위 PDF 를 쓰지 않는다 — 페이지 이미지는
    언제나 원본 바이트를 원본 페이지 번호로 렌더한다. 하위 PDF 는 오직 추출용이다.

    pdfium 은 스레드 안전하지 않으므로 렌더와 **같은 락**(PDFIUM_LOCK) 아래서 만든다.
    """
    import pypdfium2 as pdfium

    from api.store import PDFIUM_LOCK

    with PDFIUM_LOCK:
        src = pdfium.PdfDocument(data)
        try:
            dst = pdfium.PdfDocument.new()
            try:
                dst.import_pages(src, list(range(page_start - 1, page_end)))
                buf = io.BytesIO()
                dst.save(buf)
            finally:
                dst.close()
        finally:
            src.close()
    return buf.getvalue()


def segment_pages(data: bytes) -> tuple[list[dict[str, Any]], int, list[list[float]]]:
    """한 PDF 를 페이지별로 훑어 **하위 문서**로 쪼갠다 — 결합 문서 대응의 핵심.

    규칙(브리프 item 2): 두 경우를 한 규칙으로 가른다.
      * 인쇄된 제목이 알려진 종류를 지명하는 페이지는 그 종류의 **새 하위 문서를 연다**.
      * 지명하는 제목이 없는 페이지는 **현재 하위 문서를 잇는다**(같은 종류·같은 문서) —
        제목 없는 2쪽짜리 급여명세서의 2페이지가 새 문서가 아닌 이유가 이것이다.

    제로-오답(브리프 불변식): 지명도 없고 이을 현재 문서도 없는 페이지(첫 페이지에
    제목이 없거나 스캔이거나 상충함)는 **추측한 종류로 읽지 않는다** — item 3 의 보이는
    기본값(DEFAULT_DOCUMENT_TYPE)으로 열되, 그 가정은 결과 옆에 표시되고 한 클릭으로
    바뀐다(assumed=True). 조용한 오답은 없고, 보이는 가정만 있다.

    반환: (segments, page_count, page_sizes)
      segment = {"page_start", "page_end", "document_type", "nomination"|None, "assumed"}
    """
    from api import nominate as nominate_mod

    noms: list[dict[str, Any] | None] = []
    page_sizes: list[list[float]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            page_sizes.append([round(float(page.width), 2), round(float(page.height), 2)])
            nom, _reason = nominate_mod.nominate_page(page, i)
            noms.append(nom)
    page_count = len(noms)

    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for i in range(1, page_count + 1):
        nom = noms[i - 1]
        if nom is not None:
            if current is not None:
                segments.append(current)
            current = {"page_start": i, "page_end": i,
                       "document_type": nom["document_type"],
                       "nomination": nom, "assumed": False}
        elif current is None:
            # 제목 없는 선두 페이지(들). 이을 문서가 없으므로 item 3 의 보이는 기본값으로
            # 하위 문서를 연다 — 이후 제목 없는 페이지는 이 문서를 잇는다.
            current = {"page_start": i, "page_end": i,
                       "document_type": DEFAULT_DOCUMENT_TYPE,
                       "nomination": None, "assumed": True}
        else:
            current["page_end"] = i
    if current is not None:
        segments.append(current)
    if not segments:
        # 페이지가 0장인 PDF — 사실상 없지만, 빈 목록을 내면 호출자가 무너진다.
        segments = [{"page_start": 1, "page_end": max(page_count, 1),
                     "document_type": DEFAULT_DOCUMENT_TYPE,
                     "nomination": None, "assumed": True}]
    return segments, page_count, page_sizes


def read_document_file(data: bytes, file_name: str, *,
                       explicit_type: str | None = None) -> list[dict[str, Any]]:
    """올린 파일 하나를 **하위 문서 뷰들**로 읽는다 (결합 문서면 여럿, 보통 하나).

    * `explicit_type` 이 주어지면(사람이 종류를 골랐거나 "종류 바꾸기") 파일 전체를
      그 한 종류의 **하나의** 하위 문서로 읽는다 — 사람의 명시적 선택이 페이지별
      분절보다 우선한다.
    * 아니면 페이지별로 지명해 분절한다(segment_pages). 각 하위 문서의 페이지 범위를
      **그 자신의 종류로** 읽고, 필드의 페이지 번호는 원본 파일 기준으로 되돌린다 —
      item 1 의 렌더가 올바른 페이지에 상자를 그리도록.

    각 하위 문서는 팩 문서의 뷰와 같은 모양이라, 화면이 업로드용 시각언어를 새로
    발명하지 않고 기존 근거 표시(페이지 이미지 위 상자 + 필드 표)를 그대로 쓴다.
    """
    if explicit_type:
        page_sizes = _page_sizes(data)
        page_count = len(page_sizes) or 1
        segments = [{"page_start": 1, "page_end": page_count,
                     "document_type": explicit_type, "nomination": None, "assumed": False}]
    else:
        segments, page_count, page_sizes = segment_pages(data)

    file_id = f"UF-{uuid.uuid4().hex[:8].upper()}"
    single = len(segments) == 1 and segments[0]["page_start"] == 1 \
        and segments[0]["page_end"] == page_count

    views: list[dict[str, Any]] = []
    for index, seg in enumerate(segments):
        start, end = seg["page_start"], seg["page_end"]
        # 파일 전체를 덮는 하나뿐인 분절이면 원본 바이트를 그대로 쓴다 — 쪼갤 이유가
        # 없고(단일 문서 업로드는 오늘과 바이트 단위로 같아야 한다), pdfium 도 안 부른다.
        sub_data = data if single else _split_pdf(data, start, end)
        seg_sizes = page_sizes[start - 1:end] or None
        view = read_upload(
            sub_data, file_name, seg["document_type"],
            page_offset=start - 1, page_sizes=seg_sizes,
        )
        view["file_id"] = file_id
        view["sub_index"] = index
        view["sub_count"] = len(segments)
        view["page_start"] = start
        view["page_end"] = end
        _mark_nomination(view, seg["nomination"], seg["assumed"])
        views.append(view)
    return views


def _mark_nomination(view: dict[str, Any], nomination: dict[str, Any] | None,
                     assumed: bool) -> None:
    """하위 문서의 종류 출처를 뷰와 limits 에 실어 화면이 근거/가정을 보이게 한다."""
    if nomination is not None:
        # 종류가 사람의 선택이 아니라 페이지의 인쇄된 제목에서 지명됐다. 근거(일치한
        # 문구 + 페이지/좌표)를 그대로 싣는다 — 근거 없는 지명을 화면이 보여 줄 방법이
        # 없어야 하고, 그래서 근거는 여기서도 분리 불가다.
        view["nomination"] = dict(nomination)
        view["limits"].insert(0, (
            "The kind of document was not chosen by you: the page prints "
            f"“{nomination.get('matched_text', '')}” at the top, and that "
            "is the whole reason it was read as this kind. If the page is about "
            "that kind of document rather than being one, change the kind and "
            "read it again."
        ))
    elif assumed:
        # 페이지가 스스로를 밝히지 못했다. item 3: 질문으로 막는 대신 보이는 기본값으로
        # 읽고, 그 가정을 결과 옆에 표시한다. 한 클릭으로 고칠 수 있는 보이는 가정이
        # 조용한 것보다 언제나 낫다.
        view["assumed_type"] = True
        view["limits"].insert(0, (
            "This page did not print a title we recognise, so we did not ask what it "
            f"is — we read it as a {view.get('document_type')}, the most common income "
            "document, and showed you the result. If that is not what this is, change "
            "the kind above and we will read it again that way."
        ))


def read_upload(data: bytes, file_name: str, document_type: str,
                upload_id: str | None = None, *,
                page_offset: int = 0,
                page_sizes: list[list[float]] | None = None) -> dict[str, Any]:
    """올린 바이트 한 덩어리를 `DocumentView` + 업로드 메타데이터로 만든다.

    반환값은 팩 문서의 뷰와 **같은 모양**이다. 화면이 업로드용 시각언어를 따로 발명하지
    않고 기존 근거 표시(페이지 이미지 위 상자 + 필드 표)를 그대로 쓸 수 있어야 하기 때문이다.

    `page_offset` 은 결합 문서의 하위 PDF 를 읽을 때 필드의 페이지 번호를 **원본 파일
    기준**으로 되돌리는 값이다(하위 PDF 의 1페이지가 원본의 3페이지일 수 있다). 기본값
    0 에서는 아무것도 옮기지 않으므로 단일 문서 업로드는 오늘과 바이트 단위로 같다.
    """
    uid = upload_id or f"UP-{uuid.uuid4().hex[:8].upper()}"
    text_layer = has_text_layer(data)

    if text_layer:
        # 3단 매퍼: 정본 표 → 유의어 표 → 모델. 앞의 두 표가 놓친 라벨에만 모델이 불려 온다.
        # `tracking_layered_mapper` 를 쓰는 이유는 매핑이 달라져서가 아니라 -- 매핑은
        # `layered_mapper` 와 같다 -- **출처가 기록되어야** 하기 때문이다. 어느 필드를 모델이
        # 이름 댔는지 모르면 화면이 그 필드를 따로 표시할 수 없다.
        view = extract_document(data, document_type=document_type,
                                fallback_mapper=tracking_layered_mapper(document_type),
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
    # 모델이 이름을 댄 필드. `MODEL_MAPPER_NOTE` 는 `core.extract` 가 붙인 것이고 여기서는
    # 읽기만 한다 -- 출처 판정을 두 곳에서 하면 반드시 한쪽만 갱신되는 날이 온다.
    model_named = [
        f for f in located if MODEL_MAPPER_NOTE in (f.get("notes") or "")
    ]

    view["upload_id"] = uid
    view["source"] = "ocr" if path_taken == "ocr" else "text_layer"
    view["extraction_path"] = path_taken
    view["text_layer_present"] = text_layer
    view["field_count"] = len(fields)
    view["located_count"] = len(located)
    view["abstained_count"] = len(abstained)
    view["read_nothing"] = not located
    view["model_named_fields"] = [f.get("field") for f in model_named]
    view["model_named_count"] = len(model_named)
    # 리포트가 싣는 것과 같은 동결 기준일(logic/readiness.py 도 같은 상수를 싣는다).
    # 업로드 패널은 세대 리포트 없이 홀로 서므로, 월 단위 날짜의 정직한 삼분법
    # (달 전체가 60일 창 안/밖/걸침 — ui/dist/app.js::monthWindowPosition)을 화면이
    # 계산하려면 기준일이 뷰에 실려 있어야 한다. 문서의 기계 상태는 그대로다.
    from logic.constants import REFERENCE_DATE

    view["reference_date"] = REFERENCE_DATE.isoformat()
    # 화면이 이 한계를 그대로 옮겨 적을 수 있도록 서버가 말한다. 추출은 필드 사이의
    # 산술을 하지 않는다 — 시급×시간 ≠ 총액인 명세서도 총액을 high 로 읽는다. 그 모순은
    # 세대 단위 계산(logic/income.py)에서만 드러나고, 업로드는 세대에 합류하지 않는다.
    view["limits"] = [
        "We read each value from the label above it. We do not check the values against "
        "each other, so a document whose own arithmetic disagrees still reads cleanly here.",
        "This document was read on its own. It is never added to any example household and "
        "it changes no figure in any of them.",
        "Everything you upload in this session is kept together as one file of your own. "
        "You can open that file from the list on page 1 and walk both pages with it. "
        "Deleting the session removes all of it.",
        "Nothing here means approved, denied, or ineligible. A qualified housing "
        "professional makes that determination.",
    ]
    if model_named:
        # 화면이 이 필드들을 따로 짚을 수 있게 **이름을 적어서** 말한다. 업로드 패널의 필드
        # 표는 certainty 를 보여 주지만("Low"), 유의어 표가 읽은 낮은 확신과 모델이 이름 댄
        # 낮은 확신을 구별해 주지는 않는다. 그 구별이 여기 한 문장에 있다.
        #
        # 값은 모델이 읽지 않았다는 말을 같이 적는다. 이게 과장 없는 사실이고 -- 모델은
        # 라벨을 골랐을 뿐이고 값은 바뀌지 않은 기하가 읽었다 -- 사람이 무엇을 확인해야
        # 하는지도 이 문장이 정한다: 값이 맞는지가 아니라 **라벨이 그 필드가 맞는지**.
        names = ", ".join(view["model_named_fields"])
        view["limits"].insert(
            0,
            f"We did not recognise the label on {len(model_named)} of these fields "
            f"({names}), so a language model named the field from the label's wording. "
            f"It read no value: the value under each of those labels was located by the "
            f"same rules as every other field, and each is marked Low certainty below. "
            f"Please check that those fields are what their labels on the page actually say.",
        )
    if path_taken == "ocr":
        view["limits"].insert(
            1,
            "This page had no text layer, so it was read by OCR on page 1 only. OCR recovers "
            "fewer fields than a text layer does, and what it cannot read it declines to guess.",
        )
    # 하위 PDF 의 지역 페이지 번호(1..분절길이)를 원본 파일 기준으로 되돌린다. page_offset
    # 이 0 이면(단일 문서) 아무것도 옮기지 않으므로 오늘과 바이트 단위로 같다. item 1 의
    # 렌더가 각 필드를 원본의 올바른 페이지에 그리려면 이 번호가 원본 기준이어야 한다.
    if page_offset:
        for f in fields:
            if isinstance(f.get("page"), int):
                f["page"] = f["page"] + page_offset
    # 이 (하위)문서가 덮는 원본 페이지들 — 번호와 크기. 화면이 **모든 페이지**를 그리고
    # 각 페이지에 그 페이지의 필드만 얹으려면(item 1) 페이지 목록이 뷰에 실려야 한다.
    seg_len = int(view.get("page_count") or 1)
    default_size = view.get("page_size_points") or [612, 792]
    view["pages"] = [
        {"page": i + page_offset,
         "size": (page_sizes[i - 1] if page_sizes and i - 1 < len(page_sizes)
                  else list(default_size))}
        for i in range(1, seg_len + 1)
    ]
    return view
