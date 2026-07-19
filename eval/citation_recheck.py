# -*- coding: utf-8 -*-
"""
citation_recheck.py — 우리가 인용한 규칙 원문이 **지금도 그 출처의 그 자리에** 있는가.

성적표의 `citations` 절은 오랫동안 `not_run` 이었다. 그건 정직한 표기였지만
영원히 정직할 수는 없다. 이 파일이 그 절을 채운다.

무엇을 재는가
-------------
`pack/rules/rule_corpus.jsonl` 의 인용 11건을 두 부류로 나눈다.

  external_authority  — 바깥 기관이 낸 문서를 가리킨다(HUD, 연방 규정). https 로
                        도달 가능하고, 우리가 인용한 문장이 거기 그대로 있는지
                        **재대조할 수 있다**. 이 부류만 재확인 대상이다.
  self_issued         — 챌린지 팩 자신의 규약이다. 출처가 이 저장소 안의 파일이고
                        발급자도 우리 쪽이다. 여기에 "출처 재확인"을 적용하면
                        우리가 쓴 것을 우리가 읽고 맞다고 하는 순환이 된다.
                        대상 아님(`not_applicable`)으로 **표시**하고 세지 않는다.

재확인은 링크가 200 을 주는지 보는 것이 아니다. 규칙 본문이 주장하는 **구체적인
문구·숫자**를 출처에서 찾아 대조하고, 찾은 문구를 증거로 함께 적는다. 200 을 주는
빈 페이지는 통과가 아니다.

정직 규칙
---------
* **네트워크가 없거나 막히면 `not_run`.** 조용히 실패하지 않고, 실패도 아니라고
  하지 않는다. 타임아웃도 마찬가지다 — 못 한 것이지 틀린 것이 아니다.
* **일부만 되면 일부만 통과로 적는다.** 전부 초록으로 만들지 않는다.
* 규칙 문장 중 우리가 붙인 해석(예: "…가 아니다" 같은 부정 서술)은 출처에서
  인용할 수 있는 부분과 구분해 적는다. 인용할 수 없는 것을 인용한 척하지 않는다.

캐시
----
결과는 `eval/citation_recheck.json` 에 남는다. 성적표는 **이 파일만 읽고**
절대 직접 HUD 를 때리지 않는다 — 심사위원이 화면을 열 때마다 외부 서버로 요청이
나가서도, 시연이 네트워크 상태에 매달려서도 안 되기 때문이다. 대신 모든 항목이
`checked_at` 을 달고 다니고, 성적표는 그 시각을 화면에 찍는다. 발효일을 화면에
찍는 제품이 자기 확인 시각을 감출 수는 없다.

실행
----
    python eval/citation_recheck.py                 # 오래된 항목만 다시 가져온다
    python eval/citation_recheck.py --refresh       # 전부 다시 가져온다
    python eval/citation_recheck.py --offline       # 네트워크를 쓰지 않는다(강등 시험)
"""
from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "pack" / "rules" / "rule_corpus.jsonl"
ARTEFACT = ROOT / "eval" / "citation_recheck.json"
PACK = ROOT / "pack"

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_AGE_DAYS = 7.0

# huduser.gov 는 브라우저 UA 없이 요청하면 202 와 0 바이트를 돌려준다. 이건 우회가
# 아니라 사람이 열었을 때와 같은 문서를 받기 위한 것이고, 받은 바이트는 그대로 대조한다.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SELF_ISSUED_AUTHORITIES = {"hackathon_simulation"}


# =====================================================================================
# 무엇을 어디서 찾을 것인가 — 규칙별 대조 명세
# =====================================================================================
#   fetch     html | json | pdf
#   url       기본값은 규칙의 source_url. 기계가 읽는 표현이 따로 있으면 여기서 지정한다.
#   page      pdf 전용. 1부터 센다 — source_locator 가 "PDF page 130" 이면 130.
#   json_path json 전용. 대조할 문자열 필드.
#   anchor    이 문구부터 window 글자까지만 대조 범위로 삼는다(같은 페이지의 다른 지역
#             블록을 우리 것으로 착각하지 않기 위해).
#   phrases   전부 있어야 통과. 하나라도 없으면 mismatch.
#   absent    대조 범위 안에 **없어야** 하는 낱말(단어 경계로 찾는다).
#   caveat    규칙 문장 중 출처에서 인용할 수 없는 부분. 통과했다고 이 부분까지
#             확인된 것이 아님을 결과에 함께 싣는다.
CHECKS: dict[str, dict[str, Any]] = {
    "HUD-MTSP-001": {
        "fetch": "html",
        "phrases": ["FY 2026 MTSP Income Limits Effective May 01, 2026"],
        "caveat": ("The source writes the date as 'May 01, 2026'; the rule text writes "
                   "'May 1, 2026'. Same day, different rendering."),
    },
    "HUD-MTSP-002": {
        "fetch": "pdf",
        "page": 130,
        "anchor": "Boston-Cambridge-Quincy, MA-NH HMFA",
        "window": 400,
        "phrases": [
            "FY 2026 MFI: $164,600",
            "60% INCOME LIMIT 72000 82320 92580 102840 111120 119340 127560 135780",
        ],
    },
    "HUD-MTSP-003": {
        "fetch": "pdf",
        "page": 130,
        "anchor": "Boston-Cambridge-Quincy, MA-NH HMFA",
        "window": 400,
        "phrases": [
            "VERY LOW INCOME 60000 68600 77150 85700 92600 99450 106300 113150",
        ],
        "caveat": ("HUD prints this row as VERY LOW INCOME, which for this HMFA is the "
                   "50% limit; the rule text names it by its percentage."),
    },
    "HUD-DATA-001": {
        "fetch": "html",
        "anchor": "Other Datasets",
        "window": 1200,
        "phrases": [
            "LIHTC database contains information on",
            "housing units placed in service",
            "The database includes project address, number of units and low-income units",
        ],
        "absent": ["vacancy", "vacancies", "rent", "waitlist", "applicant",
                   "application", "eligibility"],
        "caveat": ("The rule's positive half is quoted above. Its negative half — that this "
                   "is not a vacancy, rent, waitlist or application-status feed — is not a "
                   "sentence HUD writes; it is checked here only as the absence of those "
                   "words from the dataset description, which is weaker evidence than a "
                   "quotation and is reported as such."),
    },
    "HUD-GEO-001": {
        "fetch": "json",
        "url": ("https://services.arcgis.com/VTyQ9soqVukalItT/ArcGIS/rest/services/"
                "LIHTC/FeatureServer/0?f=json"),
        "json_path": "description",
        "phrases": [
            "represent the general location of the property",
            "LVL2KX",
            "'R' - Interpolated rooftop",
            "'4' - ZIP+4 centroid",
            "only use addresses and their associated lat/long coordinates where the "
            "LVL2KX field is coded",
        ],
    },
    "FED-LIHTC-001": {
        "fetch": "html",
        "phrases": ["Low-income housing credit"],
        "caveat": ("Only the statute's identity is re-checked here. The rule's second "
                   "clause — that participants must not substitute uncited legal "
                   "interpretations — is the challenge pack's instruction, not text of "
                   "26 U.S.C. 42, and is not looked for at this source."),
    },
    "FED-MONITOR-001": {
        "fetch": "html",
        "phrases": [
            "1.42-5 Monitoring compliance with low-income housing credit requirements",
            "Compliance monitoring requirement",
            "State or local housing credit agency",
        ],
        "caveat": ("The rule's second clause — that this pack does not delegate an "
                   "eligibility decision to a model — is our own commitment and is not "
                   "sought in the regulation."),
    },
}


# =====================================================================================
# 텍스트 정규화
# =====================================================================================
_QUOTES = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", "​": "",
}


def normalise(text: str) -> str:
    """비교 가능한 한 줄로. 따옴표 모양과 공백 폭 차이로 불일치가 나면 안 된다."""
    for bad, good in _QUOTES.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    return normalise(html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw)))


# =====================================================================================
# 가져오기 — 실패는 실패로, 못 함은 못 함으로
# =====================================================================================
class Unreachable(Exception):
    """네트워크가 없거나, 막혔거나, 너무 느렸다. 불일치가 아니라 미실행이다.

    사람이 읽는 한 문장과 기계가 남긴 원문을 나눠 든다. 성적표에는 앞의 것만 싣는다 —
    운영체제가 자기 언어로 뱉은 소켓 오류 문자열은 이 화면을 여는 사람에게 아무 말도
    해주지 않고, 기계마다 다르게 나와서 같은 사실이 다르게 읽히게 만든다. 원문은
    버려지지 않고 산출물의 technical_detail 에 그대로 남는다.
    """

    def __init__(self, plain: str, technical: str | None = None) -> None:
        super().__init__(plain)
        self.plain = plain
        self.technical = technical


def fetch_bytes(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf,application/json,*/*",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        raise Unreachable(f"the source answered HTTP {exc.code} instead of the document",
                          f"HTTPError {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        slow = isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) \
            or "timed out" in str(reason).lower()
        plain = (f"the source did not answer within the {timeout:g} second limit"
                 if slow else
                 "the source could not be reached from the machine this ran on")
        raise Unreachable(plain, f"{type(exc).__name__}: {reason}") from exc
    if status != 200 or not body:
        # huduser.gov 가 UA 없이 준다는 바로 그 응답. 200 이 아니거나 0 바이트면
        # 우리는 문서를 받은 것이 아니다.
        raise Unreachable(
            f"the source answered {status} with {len(body)} bytes, which is not a document",
            f"status={status} bytes={len(body)}")
    return body


def source_text(spec: dict[str, Any], url: str, timeout: float) -> tuple[str, str]:
    """(대조할 텍스트, 어디서 왔는지 한 줄)."""
    kind = spec["fetch"]
    body = fetch_bytes(url, timeout)

    if kind == "html":
        return (html_to_text(body.decode("utf-8", "replace")),
                f"the page as it is served today ({len(body):,} bytes of HTML)")

    if kind == "json":
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except ValueError as exc:
            raise Unreachable(f"source did not return JSON ({exc})") from exc
        value = data.get(spec["json_path"])
        if not isinstance(value, str):
            raise Unreachable(f"JSON field {spec['json_path']!r} is absent or not text")
        return normalise(html.unescape(re.sub(r"(?s)<[^>]+>", " ", value))), \
            f"the {spec['json_path']} field of the layer's JSON"

    if kind == "pdf":
        try:
            import pdfplumber  # 지연 임포트: 재확인을 돌릴 때만 필요하다
        except ImportError as exc:
            raise Unreachable(f"pdfplumber is not installed ({exc})") from exc
        page_number = int(spec["page"])
        try:
            with pdfplumber.open(io.BytesIO(body)) as pdf:
                if page_number > len(pdf.pages):
                    raise Unreachable(
                        f"the PDF has {len(pdf.pages)} pages, so page {page_number} "
                        "no longer exists")
                text = pdf.pages[page_number - 1].extract_text() or ""
                pages = len(pdf.pages)
        except Unreachable:
            raise
        except Exception as exc:  # 손상된/바뀐 PDF. 읽지 못한 것이지 틀린 것이 아니다
            raise Unreachable(f"could not read the PDF ({type(exc).__name__}: {exc})") from exc
        return normalise(text), f"page {page_number} of the PDF, which today has {pages} pages"

    raise Unreachable(f"unknown fetch kind {kind!r}")


# =====================================================================================
# 대조
# =====================================================================================
def scope(text: str, spec: dict[str, Any]) -> tuple[str, str | None]:
    """anchor 가 있으면 그 지점부터 window 글자까지로 좁힌다."""
    anchor = spec.get("anchor")
    if not anchor:
        return text, None
    index = text.find(normalise(anchor))
    if index < 0:
        return "", f"the anchor {anchor!r} is no longer on this page"
    return text[index:index + int(spec.get("window", 1200))], None


def compare(text: str, spec: dict[str, Any]) -> dict[str, Any]:
    # 가져오는 쪽에서 이미 정규화하지만 여기서 한 번 더 한다. 대조 함수는 자기가 받은
    # 글자에 대해 혼자서도 옳아야 하고, 따옴표 모양이 달라 불일치가 나는 것은 출처가
    # 바뀐 것이 아니라 우리 비교가 틀린 것이다.
    scoped, anchor_problem = scope(normalise(text), spec)
    if anchor_problem:
        return {"matched": False, "missing": [spec["anchor"]], "unexpected": [],
                "detail": anchor_problem, "evidence": ""}

    phrases = spec.get("phrases", [])
    missing = [p for p in phrases if normalise(p) not in scoped]
    unexpected = [w for w in spec.get("absent", [])
                  if re.search(rf"\b{re.escape(w)}\b", scoped, re.IGNORECASE)]

    def quoted(count: int) -> str:
        return "1 passage" if count == 1 else f"{count} passages"

    if missing or unexpected:
        bits = []
        if missing:
            bits.append(f"{len(missing)} of the {quoted(len(phrases))} our rule quotes "
                        "could not be found there")
        if unexpected:
            bits.append("the source now uses wording the rule treats as absent: "
                        + ", ".join(unexpected))
        return {"matched": False, "missing": missing, "unexpected": unexpected,
                "detail": "; ".join(bits), "evidence": scoped[:400]}

    # 통과했을 때 증거는 요약이 아니라 **출처에서 오려낸 글자**여야 한다.
    longest = max(phrases or [""], key=len)
    index = scoped.find(normalise(longest))
    evidence = scoped[max(0, index - 60):index + len(longest) + 60].strip()
    found = ("the single passage our rule quotes was found again" if len(phrases) == 1
             else f"all {len(phrases)} passages our rule quotes were found again")
    return {"matched": True, "missing": [], "unexpected": [],
            "detail": found, "evidence": evidence}


# =====================================================================================
# 분류
# =====================================================================================
def load_corpus() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def classify(rule: dict[str, Any]) -> str:
    """external_authority 인가, self_issued 인가.

    두 조건을 **모두** 본다: 발급자가 바깥 기관이고, 출처가 바깥으로 나가는 링크일 것.
    둘 중 하나라도 아니면 재확인 대상이 아니다.
    """
    authority = str(rule.get("authority") or "")
    url = str(rule.get("source_url") or "")
    outside_issuer = authority not in SELF_ISSUED_AUTHORITIES
    outside_link = bool(re.match(r"^https?://", url, re.IGNORECASE))
    return "external_authority" if (outside_issuer and outside_link) else "self_issued"


def pack_file_for(rule: dict[str, Any]) -> Path | None:
    url = str(rule.get("source_url") or "")
    if re.match(r"^https?://", url, re.IGNORECASE):
        return None
    candidate = PACK / url
    return candidate if candidate.exists() else None


# =====================================================================================
# 한 건 확인
# =====================================================================================
def check_rule(rule: dict[str, Any], timeout: float, offline: bool) -> dict[str, Any]:
    rule_id = rule["rule_id"]
    kind = classify(rule)
    base = {
        "rule_id": rule_id,
        "classification": kind,
        "authority": rule.get("authority"),
        "source_url": rule.get("source_url"),
        "source_locator": rule.get("source_locator"),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if kind == "self_issued":
        pack_file = pack_file_for(rule)
        base.update({
            "outcome": "not_applicable",
            "detail": (
                "This rule is the challenge pack's own frozen convention. Its source is a "
                "file inside this repository"
                + (f" ({pack_file.relative_to(ROOT).as_posix()}, which is present)"
                   if pack_file else " which was not found on disk")
                + ", and its issuer is the pack itself, so re-fetching it would be us "
                  "reading back what we wrote. Not counted as verified and not counted "
                  "as failed."),
            "evidence": "",
        })
        return base

    spec = CHECKS.get(rule_id)
    if spec is None:
        base.update({
            "outcome": "not_run",
            "detail": ("No re-check has been written for this citation yet, so nothing was "
                       "compared. Reported as not run rather than as passing."),
            "evidence": "",
        })
        return base

    base["caveat"] = spec.get("caveat")

    if offline:
        base.update({
            "outcome": "not_run",
            "detail": "Run offline on purpose; no request was made to the source.",
            "evidence": "",
        })
        return base

    url = spec.get("url") or rule["source_url"]
    try:
        text, provenance = source_text(spec, url, timeout)
    except Unreachable as exc:
        base.update({
            "outcome": "not_run",
            "detail": (f"Nothing was compared, because {exc.plain}. This is a citation we "
                       "could not check, not a citation that failed."),
            "evidence": "",
        })
        if exc.technical:
            base["technical_detail"] = exc.technical
        return base

    result = compare(text, spec)
    base.update({
        "outcome": "matched" if result["matched"] else "did_not_match",
        "detail": (result["detail"][:1].upper() + result["detail"][1:]
                   + f", reading {provenance}."),
        "evidence": result["evidence"],
        "fetched_from": url,
    })
    if not result["matched"]:
        base["phrases_not_found"] = result["missing"]
        if result["unexpected"]:
            base["words_that_should_be_absent"] = result["unexpected"]
    return base


# =====================================================================================
# 캐시를 존중하며 전체 실행
# =====================================================================================
def _age_days(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - then).total_seconds() / 86400.0


def load_artefact(path: Path = ARTEFACT) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("citations"), list) else None


def run(timeout: float = DEFAULT_TIMEOUT,
        offline: bool = False,
        refresh: bool = False,
        max_age_days: float = DEFAULT_MAX_AGE_DAYS,
        artefact: Path = ARTEFACT) -> dict[str, Any]:
    """전체 재확인. 캐시가 신선하면 두고, 상하면 다시 가져온다.

    새로 가져오지 못한 항목은 **캐시에 남아 있던 결과를 유지**한다. 오프라인 시연에서
    화면이 비지 않게 하기 위해서이고, 그 결과는 자기 `checked_at` 을 그대로 달고 있으므로
    언제 확인된 것인지 읽는 사람이 안다. 캐시에도 없으면 `not_run` 이다.
    """
    now = datetime.now(timezone.utc)
    previous = load_artefact(artefact) or {}
    cached = {row["rule_id"]: row for row in previous.get("citations", [])
              if isinstance(row, dict) and row.get("rule_id")}

    results = []
    for rule in load_corpus():
        rule_id = rule["rule_id"]
        old = cached.get(rule_id)
        age = _age_days((old or {}).get("checked_at"), now)
        fresh_enough = (
            old is not None
            and old.get("outcome") in {"matched", "did_not_match", "not_applicable"}
            and age is not None and age < max_age_days
        )
        if fresh_enough and not refresh:
            row = dict(old)
            row["from_cache"] = True
            results.append(row)
            continue

        row = check_rule(rule, timeout=timeout, offline=offline)
        if row["outcome"] == "not_run" and old and old.get("outcome") in {
                "matched", "did_not_match"}:
            # 이번에 못 갔다고 지난번에 확인한 사실이 사라지지는 않는다. 다만 그 결과는
            # 지난번 시각을 달고 남으며, 이번에 왜 못 갔는지도 같이 적는다.
            row = dict(old)
            row["from_cache"] = True
            row["last_attempt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            row["last_attempt_detail"] = (
                "The source could not be reached on this run, so the result above is the "
                "one from checked_at and is not a fresh confirmation.")
            results.append(row)
            continue
        row["from_cache"] = False
        results.append(row)

    external = [r for r in results if r["classification"] == "external_authority"]
    payload = {
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "corpus": CORPUS.relative_to(ROOT).as_posix(),
        "rules_in_corpus": len(results),
        "external_citations": len(external),
        "self_issued_citations": len(results) - len(external),
        "matched": sum(1 for r in external if r["outcome"] == "matched"),
        "did_not_match": sum(1 for r in external if r["outcome"] == "did_not_match"),
        "could_not_check": sum(1 for r in external if r["outcome"] == "not_run"),
        "offline": offline,
        "citations": results,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch every external citation, ignoring cache age")
    parser.add_argument("--offline", action="store_true",
                        help="make no network request at all (degradation test)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--out", type=Path, default=ARTEFACT)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the result without writing the cache")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    payload = run(timeout=args.timeout, offline=args.offline, refresh=args.refresh,
                  max_age_days=args.max_age_days, artefact=args.out)

    for row in payload["citations"]:
        mark = {"matched": "OK ", "did_not_match": "XX ", "not_run": "-- ",
                "not_applicable": "n/a"}.get(row["outcome"], "?  ")
        cached = " (cached)" if row.get("from_cache") else ""
        print(f"{mark} {row['rule_id']:<17}{row['outcome']}{cached}")
        print(f"      {row['detail']}")
    print(f"\n{payload['matched']} of {payload['external_citations']} external citations "
          f"re-fetched and matched; {payload['did_not_match']} did not match; "
          f"{payload['could_not_check']} could not be checked. "
          f"{payload['self_issued_citations']} citations are the pack's own rules and are "
          "out of scope.")

    if not args.dry_run:
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        try:
            where = args.out.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            where = str(args.out)
        print(f"written to {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
