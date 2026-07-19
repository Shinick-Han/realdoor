# -*- coding: utf-8 -*-
"""
지역 비교표가 **화면에서 하는 주장**을 지킨다.

이 파일은 채점에 참여하지 않는다. 지역 패널은 step 4 아래에 붙는 참고 표시이고,
어떤 값도 리포트로 흘려보내지 않는다. 그런데도 테스트가 필요한 이유는 하나다 —
화면이 보스턴 행을 가리켜 **"this is the figure used above"** 라고 말하기 때문이다.
그 문장은 검증 가능한 주장이지 장식이 아니다. 주장을 하는 쪽이 증명도 들고 있어야 한다.

그래서 여기서 재는 것은 세 가지다:

  1. 보스턴 행이 `logic/constants.py` 의 동결 표와 **글자 그대로** 같은가.
     다르면 화면의 문장이 거짓이 된다. 값이 아니라 문장이 깨지는 것이다.
  2. 팩에 동결된 지역이 정확히 하나인가. 둘이면 패널이 어느 쪽을 "우리가 쓴 값"으로
     부를지 알 수 없고, 영이면 비교의 기준점이 없다.
  3. HERA Special 지역이 조건 없는 단일 숫자로 표시될 수 없는 모양인가.
     HUD 가 두 번째 표를 내는 지역은 `hera_special_60_percent` 를 **반드시** 들고 있어야
     하고, 반대로 그 키가 있으면 `hera_limit_type` 이 Special 이어야 한다. 한쪽만 있으면
     UI 가 표를 하나만 그리게 되고, 그건 2007~2008 조건이 화면에서 사라진다는 뜻이다.

UI 번들(`ui/fixtures/mtsp_regions.json`)과 원본(`pack_ext/mtsp_regions.json`)이 같은지도
본다. 번들은 손으로 편집하는 파일이 아니라 복사본이고, 갈라지면 화면이 원본에 없는 숫자를
보여주게 된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOURCE = ROOT / "pack_ext" / "mtsp_regions.json"
BUNDLED = ROOT / "ui" / "fixtures" / "mtsp_regions.json"

SIZES = [str(n) for n in range(1, 9)]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def data() -> dict:
    return load(SOURCE)


@pytest.fixture(scope="module")
def frozen_region(data: dict) -> dict:
    return [r for r in data["regions"] if r["is_pack_frozen"]][0]


def test_bundled_copy_is_verbatim() -> None:
    """UI 번들은 원본의 복사본이다. 재생성 경로는 scripts/export_fixtures.py."""
    assert BUNDLED.exists(), (
        f"{BUNDLED.relative_to(ROOT)} 가 없다. "
        "python scripts/export_fixtures.py 로 다시 뜬다."
    )
    assert load(BUNDLED) == load(SOURCE), (
        "UI 번들이 pack_ext 원본과 다르다. 번들은 손으로 고치는 파일이 아니다 — "
        "python scripts/export_fixtures.py && python ui/tools/build_fixtures.py"
    )


def test_exactly_one_region_is_pack_frozen(data: dict) -> None:
    """비교에는 기준점이 하나여야 한다. 화면이 '우리가 쓴 값'이라고 부를 행."""
    frozen = [r["region_id"] for r in data["regions"] if r["is_pack_frozen"]]
    assert frozen == ["MTSP-MA-BOSTON"], f"동결 지역이 하나가 아니다: {frozen}"


def test_frozen_region_matches_the_scoring_table(frozen_region: dict) -> None:
    """화면의 주장: 보스턴 행 = step 4 가 실제로 쓴 숫자.

    `logic.constants` 를 **읽기만** 한다. 채점 경로를 건드리지 않고, 그 경로가 들고 있는
    값을 옆에 놓고 비교할 뿐이다. 이 단언이 깨지면 고쳐야 하는 쪽은 참고 표다.
    """
    from logic import constants as C  # 읽기 전용 import

    ui_60 = {int(k): v for k, v in frozen_region["limits_60_percent"].items()}
    ui_50 = {int(k): v for k, v in frozen_region["limits_50_percent"].items()}

    assert ui_60 == dict(C.LIMITS_60_PCT), (
        "보스턴 60% 행이 동결 표와 다르다. 화면은 이 행을 '위에서 쓴 값'이라고 말한다."
    )
    assert ui_50 == dict(C.LIMITS_50_PCT)
    assert frozen_region["median_family_income"] == C.MEDIAN_FAMILY_INCOME
    assert frozen_region["effective_date"] == str(C.LIMITS_EFFECTIVE_DATE)


@pytest.mark.parametrize("region_id", ["MTSP-IL-CHICAGO", "MTSP-GA-ATLANTA"])
def test_hera_regions_carry_a_second_table(data: dict, region_id: str) -> None:
    """HERA Special 지역은 표가 둘이다. 하나만 들고 있으면 UI 가 조건을 잃는다."""
    region = [r for r in data["regions"] if r["region_id"] == region_id][0]
    assert region["hera_limit_type"] == "Special"
    special = region.get("hera_special_60_percent")
    assert special is not None, (
        f"{region_id} 는 HERA Special 인데 두 번째 표가 없다. "
        "UI 가 조건 없는 단일 숫자를 그리게 된다 — 정확히 금지된 것."
    )
    assert sorted(special) == SIZES
    # 두 번째 표는 더 높다. 낮다면 어느 쪽이 어느 쪽인지 라벨이 뒤바뀐 것이다.
    for size in SIZES:
        assert special[size] > region["limits_60_percent"][size], (
            f"{region_id} 크기 {size}: HERA Special 이 표준 표보다 높지 않다."
        )
    assert "2007" in region["hera_special_note"] and "2008" in region["hera_special_note"]


def test_no_stray_hera_table(data: dict) -> None:
    """반대 방향. Regular 로 표시된 지역이 두 번째 표를 들고 있으면 안 된다."""
    for region in data["regions"]:
        if region["hera_limit_type"] != "Special":
            assert "hera_special_60_percent" not in region, (
                f"{region['region_id']} 는 Regular 인데 HERA 표를 들고 있다."
            )


def test_every_region_is_displayable(data: dict) -> None:
    """화면이 각 행에서 요구하는 것: 8개 크기 전부, 그리고 출처 둘."""
    assert len(data["regions"]) == 7
    for region in data["regions"]:
        rid = region["region_id"]
        assert sorted(region["limits_60_percent"]) == SIZES, f"{rid}: 크기 1-8 이 아니다"
        assert region["source_url"].startswith("https://"), f"{rid}: 링크가 없다"
        assert region["source_locator"], f"{rid}: 출처 위치가 비었다"
        assert region["authority"] == "official_hud", f"{rid}: 출처 권위가 HUD 가 아니다"


def test_nine_person_limits_are_not_published(data: dict) -> None:
    """8인 초과는 HUD 가 발표하지 않는다. 어떤 지역도 9를 들고 있으면 안 된다.

    UI 는 세대 크기를 동결 표에서 역인덱스로 찾고 못 찾으면 숫자를 아예 내지 않는다.
    그 경로가 의미를 가지려면 데이터에도 9가 없어야 한다.
    """
    for region in data["regions"]:
        for table in ("limits_60_percent", "limits_50_percent", "hera_special_60_percent"):
            values = region.get(table) or {}
            assert "9" not in values, f"{region['region_id']}.{table} 에 9인 값이 있다"
