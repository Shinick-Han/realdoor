#!/usr/bin/env bash
# Hugging Face Space 의 README.md 앞에 YAML front matter 를 붙인다.
#
# ── 왜 별도 스크립트인가 ───────────────────────────────────────────────
# HF Spaces 는 이 블록을 **저장소 루트 README.md 의 맨 위**에서만 읽는다. 다른 설정
# 파일은 없다. 그런데 이 레포의 README.md 는 심사위원이 읽는 문서이고, 지금 다른
# 작업자가 편집 중이다. 그래서 워킹트리의 README.md 를 미리 건드리지 않는다 —
# **HF 로 push 하는 순간에만** 이 스크립트를 돌린다.
#
# 붙여도 본문은 그대로 읽힌다. GitHub 은 front matter 를 본문 위 작은 표로 렌더링하고
# 나머지 마크다운은 손대지 않는다. 그래도 GitHub 쪽 README 를 그 표 없이 두고 싶다면,
# HF 원격으로만 push 하는 브랜치에서 이 스크립트를 돌리고 그 브랜치를 origin 에는
# 올리지 않으면 된다.
#
# ── 쓰는 법 ────────────────────────────────────────────────────────────
#   bash deploy/hf_space_readme.sh            # README.md 에 붙인다 (이미 있으면 아무 일 없음)
#   bash deploy/hf_space_readme.sh --check    # 붙어 있는지만 본다 (CI/사전 점검용)
#
# 두 번 돌려도 두 번 붙지 않는다. 배포 스크립트는 재실행이 안전해야 한다.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README="$ROOT/README.md"

# title 은 Space 카드의 제목, emoji 는 그 옆 아이콘. sdk/app_port 는 필수다 —
# app_port 가 Dockerfile 의 기본 포트(7860)와 어긋나면 Space 는 영원히 "Building" 에
# 머물다 timeout 난다. 이 두 숫자는 항상 같이 움직여야 한다.
read -r -d '' FRONT_MATTER <<'YAML' || true
---
title: RealDoor
emoji: 🚪
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Ready, not eligible — application-readiness copilot for renters
---
YAML

if head -n 1 "$README" 2>/dev/null | grep -q '^---$'; then
  echo "front matter already present in README.md — nothing to do"
  exit 0
fi

if [ "${1:-}" = "--check" ]; then
  echo "README.md has no HF front matter; the Space will not build. Run this script without --check."
  exit 1
fi

printf '%s\n\n' "$FRONT_MATTER" | cat - "$README" > "$README.hf.tmp"
mv "$README.hf.tmp" "$README"
echo "front matter prepended to README.md (app_port 7860 — must match the Dockerfile)"
