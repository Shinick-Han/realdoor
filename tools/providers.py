# -*- coding: utf-8 -*-
"""
providers.py — 외부 API 단일 창구.

교리를 코드로 강제한다:
  1. 모든 외부 호출은 **디스크 캐시**를 통과한다. 같은 입력 → 같은 출력.
     → 데모 경로가 결정론적이 되고(무대에서 안 죽는다), 재실행 비용이 0이 된다.
  2. 판정 로직은 여기 없다. 여기는 **추출·검색·나레이션**만. 판단은 순수함수로 따로.
  3. 모든 호출이 usage.jsonl에 기록된다 → 비용·토큰을 추측하지 않고 실측한다.

키는 환경변수에서만 읽는다. 절대 파일에 쓰지 않는다.
  OPENAI_API_KEY / TAVILY_API_KEY / ELEVENLABS_API_KEY

사용:
    from providers import search, complete, cache_stats
    hits = search("bedaquiline resistance Rv0678 very major error rate")
    out  = complete("Extract the claimed specialties as JSON list", text)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / "providers"
USAGE_LOG = ROOT / ".cache" / "usage.jsonl"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 데모 모드: 캐시 미스 시 네트워크로 나가지 않고 예외를 던진다.
# 발표 직전에 HN_OFFLINE=1 로 켜두면 "라이브 호출이 무대에서 죽는" 사고가 원천 차단된다.
OFFLINE = os.environ.get("HN_OFFLINE", "") == "1"


class CacheMiss(RuntimeError):
    """OFFLINE=1 인데 캐시에 없음 = 데모 경로에 구멍이 있다는 뜻."""


def _key(kind: str, payload: dict) -> str:
    blob = json.dumps({"kind": kind, **payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _cache_get(k: str):
    f = CACHE_DIR / f"{k}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def _cache_put(k: str, value):
    (CACHE_DIR / f"{k}.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _log(record: dict):
    record["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _require(var: str) -> str:
    v = os.environ.get(var)
    if not v:
        raise RuntimeError(
            f"{var} 미설정. setx {var} \"...\" 로 등록하고 새 셸을 열어라. "
            f"키를 파일에 쓰지 마라."
        )
    return v


# ─────────────────────────────────────────────────────────── 검색 (ground 역할)

def search(query: str, max_results: int = 5, depth: str = "advanced",
           include_raw: bool = False) -> dict:
    """tavily 검색. 외부 현실에 묻는 창구 — 모델에게 묻지 않는다.

    반환: {"query", "results":[{title,url,content,score}], "answer"?}
    """
    k = _key("tavily", {"q": query, "n": max_results, "d": depth, "raw": include_raw})
    hit = _cache_get(k)
    if hit is not None:
        _log({"provider": "tavily", "cached": True, "key": k, "query": query[:120]})
        return hit
    if OFFLINE:
        raise CacheMiss(f"OFFLINE인데 캐시 없음: search({query[:60]!r})")

    from tavily import TavilyClient
    client = TavilyClient(api_key=_require("TAVILY_API_KEY"))
    res = client.search(
        query=query,
        max_results=max_results,
        search_depth=depth,
        include_raw_content=include_raw,
    )
    _cache_put(k, res)
    _log({"provider": "tavily", "cached": False, "key": k, "query": query[:120],
          "n_results": len(res.get("results", []))})
    return res


# ─────────────────────────────────────────────────── 추출/서술 (마지막 1인치만)

def complete(instruction: str, content: str = "", *, model: str = "gpt-4o-mini",
             json_schema: dict | None = None, max_tokens: int = 1500,
             temperature: float = 0.0) -> Any:
    """OpenAI 호출. **판정이 아니라 추출·서술에만** 쓴다.

    json_schema를 주면 구조화 출력을 강제하고 dict를 돌려준다.
    temperature=0 고정이 기본 — 재현성이 우선이다.
    """
    k = _key("openai", {"i": instruction, "c": content, "m": model,
                        "s": json_schema, "t": temperature, "mt": max_tokens})
    hit = _cache_get(k)
    if hit is not None:
        _log({"provider": "openai", "cached": True, "key": k, "model": model})
        return hit
    if OFFLINE:
        raise CacheMiss(f"OFFLINE인데 캐시 없음: complete({instruction[:60]!r})")

    from openai import OpenAI
    client = OpenAI(api_key=_require("OPENAI_API_KEY"))

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": content or "(no content)"},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "out", "schema": json_schema, "strict": True},
        }

    r = client.chat.completions.create(**kwargs)
    text = r.choices[0].message.content
    out = json.loads(text) if json_schema else text

    u = r.usage
    _log({"provider": "openai", "cached": False, "key": k, "model": model,
          "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens})
    _cache_put(k, out)
    return out


# ───────────────────────────────────────────────────────────── 나레이션 (영상용)

def narrate(text: str, out_path: str | Path,
            voice_id: str = "21m00Tcm4TlvDq8ikWAM") -> Path:
    """ElevenLabs TTS → mp3. 제출 영상 3편(각 60초) 나레이션용."""
    out_path = Path(out_path)
    k = _key("11labs", {"t": text, "v": voice_id})
    cached_mp3 = CACHE_DIR / f"{k}.mp3"
    if cached_mp3.exists():
        out_path.write_bytes(cached_mp3.read_bytes())
        _log({"provider": "elevenlabs", "cached": True, "key": k})
        return out_path
    if OFFLINE:
        raise CacheMiss("OFFLINE인데 나레이션 캐시 없음")

    import requests
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": _require("ELEVENLABS_API_KEY"),
                 "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=120,
    )
    r.raise_for_status()
    cached_mp3.write_bytes(r.content)
    out_path.write_bytes(r.content)
    _log({"provider": "elevenlabs", "cached": False, "key": k, "chars": len(text)})
    return out_path


# ────────────────────────────────────────────────────────────────────── 진단

def cache_stats() -> dict:
    files = list(CACHE_DIR.glob("*"))
    by_provider: dict[str, int] = {}
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            try:
                p = json.loads(line).get("provider", "?")
            except json.JSONDecodeError:
                continue
            by_provider[p] = by_provider.get(p, 0) + 1
    return {"cached_objects": len(files), "calls_logged": by_provider,
            "offline": OFFLINE, "cache_dir": str(CACHE_DIR)}


def keys_present() -> dict:
    return {v: bool(os.environ.get(v)) for v in
            ("OPENAI_API_KEY", "TAVILY_API_KEY", "ELEVENLABS_API_KEY")}


if __name__ == "__main__":
    print("keys :", keys_present())
    print("cache:", cache_stats())
