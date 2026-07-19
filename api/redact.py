# -*- coding: utf-8 -*-
"""
redact.py — 모델 제공자로 나가기 **직전**에, 확신할 수 있는 식별자만 지운다.

이 모듈이 무엇이 아닌지부터 적는다. **이것은 개인정보 필터가 아니다.** 문맥으로만
개인정보인 줄 알 수 있는 것 — 이름, 직장명, 다니는 학교, "우리 애 담임이 사는 동네" —
은 여기서 하나도 걸리지 않는다. 그런 것을 걸러내려면 문장의 의미를 판단해야 하고,
판단하려면 그 문장을 모델에 보내야 한다. 보내지 않고 판단하는 방법을 우리는 모른다.
그래서 시도하지 않는다. 시도한 척하는 것이 안 하는 것보다 나쁘다.

여기서 지우는 것은 **형태만 보고도 식별자인 줄 아는 것**뿐이다. 정규식이 확신할 수
있는 범위 밖으로는 한 발도 나가지 않는다:

  * 이메일 주소        — `@` 와 도메인 형태. 오탐이 거의 없다.
  * SSN 형태           — `\\d{3}-\\d{2}-\\d{4}`. 전화번호보다 먼저 본다.
  * 전화번호           — 미국·한국의 흔한 표기.
  * 번지가 붙은 주소 줄 — 숫자 + 거리 이름 + `Street`/`Avenue` 류 접미어가 **모두**
                          있을 때만. 접미어가 없으면 건드리지 않는다.
  * 우편번호           — **스스로 우편번호라고 밝힌 것만.** 맨 다섯 자리 숫자는
                          지우지 않는다. `45000` 은 우편번호일 수도 있고 연봉일 수도
                          있는데, 연봉을 지우면 의도 분류가 망가지고 그건 이 서비스가
                          답을 못 하게 만든다. 그래서 `MA 02139` 처럼 주(州) 약자가
                          앞에 붙었거나 `zip`/`우편번호` 라고 적혀 있을 때만 지운다.

**금액은 지우지 않는다.** 그 자체로 사람을 지목하지 않고, 의도 분류에는 오히려
쓸모가 있다.

치환은 삭제가 아니라 **자리표시자**다. `[email removed]` 처럼 무엇이 있던 자리인지
남긴다. 통째로 지우면 문장 구조가 무너져 분류기가 주제를 못 찾는다 — 우리가 고치려던
것보다 큰 손해다.

지운 결과는 **모델 호출에만** 쓴다. 결정론 라우터에 되묻는 앵커 확인은 원문으로 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: (이름, 정규식, 자리표시자).
#:
#: **순서가 의미를 가진다.** 이메일을 먼저 보는 이유는 주소 안의 숫자를 전화번호
#: 규칙이 먼저 먹어치우면 남은 껍데기가 이메일로 안 보이기 때문이고, SSN 을 전화번호
#: 보다 먼저 보는 이유는 둘 다 숫자와 하이픈이라 나중에 오는 쪽이 진다.
_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b"),
        "[email removed]",
    ),
    (
        # 미국 SSN 표기. 전화번호 규칙보다 먼저 걸려야 한다.
        "ssn_shaped",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[id number removed]",
    ),
    (
        # 미국: (617) 555-0134 / 617-555-0134 / 617.555.0134 / +1 617 555 0134
        # 한국: 010-1234-5678 / 02-123-4567 / +82 10-1234-5678
        # 구분자가 **있을 때만** 잡는다. 맨 숫자열은 금액일 수 있으므로 건드리지 않는다.
        "phone",
        re.compile(
            r"(?<![\w-])(?:"
            r"\+?\d{1,3}[\s.-]?)?"
            r"(?:\(\d{2,4}\)|\d{2,4})"
            r"[\s.-]\d{3,4}[\s.-]\d{4}"
            r"(?![\w-])"
        ),
        "[phone number removed]",
    ),
    (
        # 번지 + 거리 이름 + 접미어가 **전부** 있을 때만. 접미어 목록 밖은 통과시킨다.
        # "302 Glass Street" 는 잡고, "302 documents" 나 "60-day rule" 은 잡지 않는다.
        "street_address",
        re.compile(
            r"\b\d{1,6}[A-Za-z]?\s+"
            r"(?:[A-Za-z][A-Za-z.'-]*\s+){0,3}"
            r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|"
            r"Court|Ct|Place|Pl|Terrace|Ter|Trail|Trl|Way|Circle|Cir|"
            r"Highway|Hwy|Parkway|Pkwy|Square|Sq)\b\.?"
            r"(?:\s*(?:Apt|Unit|Suite|Ste|#)\s*[\w-]+)?",
            re.IGNORECASE,
        ),
        "[address removed]",
    ),
    (
        # ZIP+4 는 그 형태 자체가 우편번호다. 오탐 여지가 사실상 없다.
        "postal_code",
        re.compile(r"\b\d{5}-\d{4}\b"),
        "[postal code removed]",
    ),
    (
        # 다섯 자리 우편번호는 **스스로 밝힐 때만**. 그 밖의 다섯 자리 숫자는 금액일
        # 수 있고, 금액을 지우면 의도 분류가 나빠진다.
        #
        # 앞의 두 글자를 `[A-Z]{2}` 로 잡았다가 대소문자 무시 때문에 "my income **is
        # 45000** a year" 가 통째로 지워졌다. 그 회귀를 막으려고 실제 주(州) 약자
        # 목록으로 좁히고, 이 분기만 대소문자를 구분한다. 목록 밖은 통과시킨다 —
        # 놓치는 편이 연봉을 지우는 편보다 낫다.
        "postal_code",
        re.compile(
            r"(?:\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|"
            r"ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|PR|RI|"
            r"SC|SD|TN|TX|UT|VT|VA|VI|WA|WV|WI|WY)\s+\d{5}\b"
            r"|(?i:\bzip(?:\s*code)?\b|\bpostal\s*code\b|우편번호)\s*:?\s*\d{5}\b)"
        ),
        "[postal code removed]",
    ),
)


@dataclass(frozen=True)
class Redaction:
    """한 문장에 대한 제거 결과. 원문은 담지 않는다."""

    text: str
    #: 패턴 이름 → 그 패턴이 지운 개수. 지운 게 없으면 키가 없다.
    by_pattern: dict[str, int] = field(default_factory=dict)

    @property
    def removed(self) -> int:
        return sum(self.by_pattern.values())


def scrub(text: str) -> Redaction:
    """식별자 형태를 자리표시자로 바꾼 문장과, 무엇을 몇 개 바꿨는지.

    **완전하지 않다.** 이 함수가 0을 돌려주었다는 것은 "개인정보가 없다"가 아니라
    "우리가 아는 형태가 없다"는 뜻일 뿐이다. 호출부는 그 차이를 지워서는 안 된다.
    """
    out = text or ""
    counts: dict[str, int] = {}
    for name, pattern, placeholder in _PATTERNS:
        out, hits = pattern.subn(placeholder, out)
        if hits:
            counts[name] = counts.get(name, 0) + hits
    return Redaction(out, counts)


def pattern_names() -> tuple[str, ...]:
    """성적표가 "무엇을 보긴 봤는지" 를 적을 수 있도록 이름만 내준다."""
    seen: list[str] = []
    for name, _, _ in _PATTERNS:
        if name not in seen:
            seen.append(name)
    return tuple(seen)
