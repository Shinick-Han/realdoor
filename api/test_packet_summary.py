# -*- coding: utf-8 -*-
"""
test_packet_summary.py — 패킷의 표지(packet_summary.html)와, 표지를 얹으면서
아무것도 재구성하지 않았다는 사실을 잰다.

패킷은 지금까지 JSON 둘 + README 였고, 그것을 내려받은 세입자가 "왜 JSON 이지?" 라고
묻는 것이 합리적이었다 — 패킷의 수신인이 어디에도 적혀 있지 않았기 때문이다. 표지는
그 공백을 메우는 추가물이다. 여기서 재는 것은 넷:

  1. ZIP 에 packet_summary.html 이 실제로 들어 있다.
  2. 정정된 값의 행이 기계 판독값과 정정값을 **둘 다** 보인다
     ("machine read X; applicant corrected to Y") — 정정은 증거 옆의 주석이지
     증거의 변경이 아니라는 경계가 표지에서도 지켜지는지.
  3. 생성된 HTML 에 판정 어휘 토큰이 없다. 금지 목록은 eval/test_no_decision.py 의
     것을 **가져와서** 쓴다 — 두 벌로 베끼면 언젠가 갈라진다.
  4. 두 JSON 파일은 표지가 생기기 **이전**의 캡처(api/packet_baseline/)와
     바이트 단위로 같다. 세션마다 달라지는 세 값(generated_at, session_id,
     engine_version)만 자리표시자로 바꾼 뒤 비교한다 — engine_version 은 커밋
     해시라서 커밋마다 바뀌는 것이 정상이고, 그것까지 같기를 요구하면 이 테스트는
     모든 커밋에서 깨진다. 추출 결과 자체가 바뀌면(core/ 가 바뀌면) 이 캡처는
     다시 떠야 한다; 그때 이 테스트가 깨지는 것은 버그가 아니라 알림이다.
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "eval") not in sys.path:
    sys.path.insert(0, str(ROOT / "eval"))

from api.store import STORE

HH = "HH-001"
DOC_PAY = "HH-001-D02"
BASELINE = ROOT / "api" / "packet_baseline"

_GENERATED_AT = re.compile(r'("generated_at": ")[^"]*(")')
_SESSION_ID = re.compile(r'("session_id": ")[^"]*(")')
_ENGINE = re.compile(r'("engine_version": ")[^"]*(")')


def _normalize(text: str) -> str:
    """세션마다 달라지는 세 값만 자리표시자로. 나머지는 바이트 그대로 남는다."""
    text = _GENERATED_AT.sub(r"\g<1>GENERATED_AT\g<2>", text)
    text = _SESSION_ID.sub(r"\g<1>SESSION_ID\g<2>", text)
    text = _ENGINE.sub(r"\g<1>ENGINE_VERSION\g<2>", text)
    return text


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.app import app

    STORE.warm()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def session(client):
    sid = client.post("/api/session").json()["session_id"]
    yield sid
    STORE.delete(sid)


def _h(sid: str) -> dict:
    return {"X-Session-Id": sid}


def _packet(client, sid: str) -> zipfile.ZipFile:
    r = client.post(f"/api/packet/{HH}", headers=_h(sid))
    assert r.status_code == 200, r.text
    return zipfile.ZipFile(io.BytesIO(r.content))


# ── 1. 표지가 들어 있다 ─────────────────────────────────────────────────────
def test_the_zip_contains_the_cover_sheet(client, session):
    with _packet(client, session) as z:
        names = z.namelist()
        html = z.read("packet_summary.html").decode("utf-8")

    assert "packet_summary.html" in names
    # 원래 있던 파일은 전부 그대로 있다 — 추가이지 대체가 아니다.
    for name in ("readiness_report.json", "activity_log.json", "README.txt"):
        assert name in names, f"{name} disappeared from the packet"

    # 자기완결: 스크립트 없음, 외부 리소스 없음. 패킷은 영원히 오프라인로 열려야 한다.
    assert "<script" not in html.lower()
    assert "http://" not in html and "https://" not in html
    # 수신인이 첫 화면에 적혀 있다.
    assert "the person who decides" in html
    # 정정=주석 경계가 문장으로 있다.
    assert "not re-rendered or modified" in html


def test_the_readme_is_an_address_book(client, session):
    with _packet(client, session) as z:
        readme = z.read("README.txt").decode("utf-8")
    # 첫 줄이 패킷 전체의 수신인을 말한다.
    assert readme.splitlines()[0].startswith("This packet is for the person")
    # 파일마다 누구를 위한 것인지 한 줄씩.
    assert "open this one" in readme
    # 두 JSON 은 각각 "열 필요 없다"는 줄을 가진다.
    assert readme.count("You do") == 2 and "not need to open it" in readme
    # 판정 없음·전송 없음 문장은 그대로 남는다.
    assert "NOT an eligibility decision" in readme
    assert "Nothing here has been sent to any property or provider" in readme


# ── 2. 정정된 행은 두 값을 다 보인다 ────────────────────────────────────────
def test_a_corrected_value_shows_both_readings(client, session):
    r = client.post("/api/confirm", headers=_h(session),
                    json={"document_id": DOC_PAY, "field": "gross_pay", "value": 2440})
    assert r.status_code == 200, r.text

    with _packet(client, session) as z:
        html = z.read("packet_summary.html").decode("utf-8")

    # 기계가 읽은 2166.0 은 리포트에서 정정값으로 덮였지만, 표지는 둘 다 말해야 한다.
    assert "machine read 2166; applicant corrected to 2440" in html
    # 표지의 값 칸 자체는 리포트가 지금 들고 있는 값 — 정정값 — 이다.
    assert "<td>2440</td>" in html


def test_a_confirmed_value_is_marked_as_seen(client, session):
    read = client.get(f"/api/report/{HH}", headers=_h(session)).json()
    value = next(f["value"] for d in read["documents"] if d["document_id"] == DOC_PAY
                 for f in d["fields"] if f["field"] == "gross_pay")
    client.post("/api/confirm", headers=_h(session),
                json={"document_id": DOC_PAY, "field": "gross_pay", "value": value})
    with _packet(client, session) as z:
        html = z.read("packet_summary.html").decode("utf-8")
    assert "machine-read; confirmed by the applicant" in html


# ── 3. 판정 어휘 토큰 없음 ──────────────────────────────────────────────────
def test_no_banned_tokens_in_the_generated_html(client, session):
    """금지 목록과 토큰 분해 규칙을 eval/test_no_decision.py 에서 가져온다.
    표지는 프로즈이므로 키 검사보다 넓게 — **모든** 단어 토큰을 검사한다."""
    import test_no_decision as guard

    client.post("/api/confirm", headers=_h(session),
                json={"document_id": DOC_PAY, "field": "gross_pay", "value": 2440})
    with _packet(client, session) as z:
        html = z.read("packet_summary.html").decode("utf-8")

    tokens = {t.lower() for t in guard._KEY_SPLIT.split(html) if t}
    hits = tokens & guard.BANNED_TOKENS
    assert not hits, f"banned decision vocabulary in packet_summary.html: {sorted(hits)}"


# ── 4. 두 JSON 은 바이트 하나 바뀌지 않았다 ─────────────────────────────────
@pytest.mark.parametrize("name", ["readiness_report.json", "activity_log.json"])
def test_json_parts_unchanged_byte_for_byte(client, session, name):
    baseline = (BASELINE / name).read_text(encoding="utf-8")
    with _packet(client, session) as z:
        now = _normalize(z.read(name).decode("utf-8"))
    assert now == baseline, (
        f"{name} changed. The cover sheet was supposed to be an addition; if core/ "
        f"extraction changed on purpose, re-capture api/packet_baseline/ and say so "
        f"in the commit."
    )
