#!/usr/bin/env bash
# push_hf.sh — deploy the current tree to the RealDoor Hugging Face Space(s).
#
# ── why this script exists ─────────────────────────────────────────────────
# HF Spaces are a DEPLOY target, not a source repo. Pushing master to them fails
# three different ways, each learned the hard way:
#   1. HF's pre-receive hook scans the WHOLE pushed history for binary files, so
#      deleting a big file in a later commit does not help — the blob still rides
#      in an ancestor. Fix: push a single flat orphan commit with no history.
#   2. HF requires binaries in Xet/LFS. The 24 demo-household PDFs are read at
#      runtime (api/store.py extracts them for /api/report/HH-00x), so they must
#      ship — via git-lfs. Everything else binary is dev/eval and is stripped.
#   3. The judge-facing README.md must stay clean on GitHub, but HF reads its
#      config from a YAML front-matter block at the top of README.md. So the
#      front matter is added only here, on a throwaway branch, never on master.
#
# The result: master and origin are never touched. This builds a fresh orphan
# commit from whatever is committed on the current branch, pushes it to HF, and
# returns you to where you started. Re-runnable.
#
# ── usage ──────────────────────────────────────────────────────────────────
#   bash deploy/push_hf.sh                 # push to both: space (live) + space2
#   bash deploy/push_hf.sh space2          # canary only (verify before live)
#   bash deploy/push_hf.sh space           # live only
#
# After pushing, poll the Space until the new build is warm:
#   curl -s https://shinick-realdoor.hf.space/api/health
# and confirm engine_version changed, documents_loaded:24, warm:"completed".
# Push to space2 (canary) FIRST, verify it is not an empty product, then space.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REMOTES=("$@")
if [ ${#REMOTES[@]} -eq 0 ]; then
  REMOTES=(space space2)
fi

# Runtime needs these binaries — ship via LFS. Everything else binary is stripped.
LFS_GLOB="pack/synthetic_documents/documents/*.pdf"

# Not needed at runtime (eval fixtures, dev screenshots, the participant guide) —
# stripped so the image is small and the HF binary hook has less to reject.
STRIP_PATHS=(testdata pack/participant-guide)
# plus every ui/screenshots-* directory, resolved dynamically:
while IFS= read -r d; do STRIP_PATHS+=("$d"); done < <(git ls-files 'ui/screenshots-*' | sed -E 's#(^ui/screenshots-[^/]+)/.*#\1#' | sort -u)

START_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
STAGE_BRANCH="__hf_stage_$$"
FLAT_BRANCH="__hf_flat_$$"

cleanup() {
  git checkout -q "$START_BRANCH" 2>/dev/null || true
  git branch -D "$STAGE_BRANCH" 2>/dev/null || true
  git branch -D "$FLAT_BRANCH" 2>/dev/null || true
}
trap cleanup EXIT

# Refuse to deploy a tree whose extraction code is dirty — the deployed build
# must correspond to a committed state, never to a working copy.
if [ -n "$(git status --porcelain core api eval ocr logic pack 2>/dev/null | grep -vE '^\?\?')" ]; then
  echo "ERROR: tracked extraction paths (core/api/eval/ocr/logic/pack) have uncommitted changes." >&2
  echo "Commit or stash them first — the Space must deploy a committed state." >&2
  exit 1
fi

SOURCE_SHA="$(git rev-parse --short HEAD)"
echo ">> deploying committed tree $SOURCE_SHA on branch '$START_BRANCH' to: ${REMOTES[*]}"

# 1. Stage branch: strip non-runtime binaries and add the HF front matter.
git checkout -q -b "$STAGE_BRANCH"
bash deploy/hf_space_readme.sh >/dev/null
for p in "${STRIP_PATHS[@]}"; do
  git rm -r -q --cached --ignore-unmatch "$p" >/dev/null 2>&1 || true
  git rm -r -q --ignore-unmatch "$p"          >/dev/null 2>&1 || true
done
git add README.md
git commit -q -m "deploy stage: HF front matter + strip eval/dev artifacts" || true

# 2. Flatten to a single orphan commit so no large blob rides in history, and
#    move the runtime demo PDFs into LFS.
git checkout -q --orphan "$FLAT_BRANCH"
git lfs install --local >/dev/null 2>&1 || { echo "ERROR: git-lfs not available." >&2; exit 1; }
git lfs track "$LFS_GLOB" >/dev/null
git rm -q -r --cached "pack/synthetic_documents/documents" >/dev/null 2>&1 || true
git add .gitattributes
git add "pack/synthetic_documents/documents"
# The orphan index already holds every other tracked file from the stage commit;
# committing without `add -A` keeps untracked scratch (ui/shots, .cache, …) out.
git commit -q -m "RealDoor — HF Space deploy (flat tree from $SOURCE_SHA; demo PDFs via LFS)"

LFS_N="$(git lfs ls-files | wc -l | tr -d ' ')"
BIN_LEFT="$(git ls-tree -r --name-only HEAD | grep -iE '\.(pdf|png|jpg|jpeg|gif|ico|woff2?|ttf|otf|docx)$' | grep -vE '^pack/synthetic_documents/documents/' | head -1 || true)"
echo ">> flat commit built: $(git rev-parse --short HEAD) | LFS files: $LFS_N | non-LFS binary left: ${BIN_LEFT:-none}"
if [ -n "$BIN_LEFT" ]; then
  echo "ERROR: a non-LFS binary remains ($BIN_LEFT); HF will reject. Add it to LFS_GLOB or STRIP_PATHS." >&2
  exit 1
fi

# 3. Force-push the flat commit to each HF remote's main.
for r in "${REMOTES[@]}"; do
  echo ">> pushing to '$r' ..."
  git push --force "$r" "$FLAT_BRANCH:main"
done

echo ">> done. Deployed $SOURCE_SHA to: ${REMOTES[*]}"
echo ">> verify:  curl -s https://shinick-realdoor.hf.space/api/health   (expect new engine_version, documents_loaded:24, warm:\"completed\")"
