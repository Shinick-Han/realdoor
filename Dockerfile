# RealDoor — Hugging Face Spaces (Docker SDK, CPU basic).
#
# 이 이미지가 지켜야 하는 것 네 가지, 그리고 각각이 어디에 있는지:
#
#   1. UI 가 이미지 안에 있어야 한다. `api/app.py:408` 이 `ui/dist` 를 마운트하고,
#      없으면 `/` 가 `{"error":"ui_not_built"}` 를 낸다. → 아래 `COPY . .`
#   2. 워커는 **하나**여야 한다. 세션이 프로세스 메모리 dict 이므로(`api/store.py:288`)
#      워커가 둘이면 세션이 무작위로 404 난다. → CMD 에 `--workers` 를 주지 않는다.
#   3. `--host 0.0.0.0`. README 의 두 예시는 둘 다 127.0.0.1 이라 그대로 쓰면
#      컨테이너 밖에서 닿지 않는다.
#   4. OCR 이 컨테이너 안에서 실제로 돌아야 한다. → 아래 libgl1 설명.

FROM python:3.12-slim-bookworm

# 베이스 태그를 `slim` 이 아니라 `slim-bookworm` 으로 고정한 이유: 아래 apt 패키지
# 이름이 데비안 릴리스마다 다르다(trixie 에서는 libglib2.0-0 이 libglib2.0-0t64 다).
# 베이스가 조용히 넘어가면 apt 가 깨지고, 그 실패는 배포일에 일어난다.

# `rapidocr-onnxruntime` 은 `opencv-python` 을 끌고 오고, opencv 는 headless 빌드가
# 아니면 libGL 을 dlopen 한다. slim 이미지에는 그게 없다. 빠뜨리면 **부팅은 성공하고**
# (OCR import 가 lazy 다, `ocr/ocr_extract.py:267`) 스캔본 PDF 를 처음 만나는 순간에만
# 터진다 — 즉 심사위원의 첫 업로드에서 처음 드러난다. 그게 이 줄이 여기 있는 이유다.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# HF Docker Space 는 UID 1000 으로 돈다. 루트로 만든 파일은 런타임에 읽지 못할 수 있다.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR $HOME/app

# 의존성을 소스보다 **먼저** 복사한다. 코드 한 줄 고칠 때마다 onnxruntime 을 다시
# 받지 않기 위해서다. 재빌드가 5~15분에서 1분 밑으로 내려간다.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# ⚠ `.cache/extractions` (1.5MB) 가 이미지에 들어오면 첫 부팅이 수 초로 끝난다.
#   들어오지 않으면 startup 훅의 `STORE.warm()` 이 팩 24문서를 추출하고 그중 8개에
#   OCR 을 돌린다. `.cache/` 는 `.gitignore:9` 에 있으므로 **HF 로 push 하기 전에**
#   `git add -f .cache/extractions` 를 해야 이 COPY 가 그걸 집어 간다.
#   빌드 컨텍스트에 없으면 그냥 없는 채로 지나가고, 대가는 첫 부팅 시간뿐이다.

# HF 는 7860 을 기대한다(README front matter 의 `app_port`). Render/Railway/Fly 는
# `$PORT` 를 주입한다. CMD 를 셸 형식으로 두면 한 이미지가 양쪽에서 다 돈다 —
# exec 형식(JSON 배열)이면 `${PORT}` 가 확장되지 않고 문자 그대로 넘어간다.
EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
  CMD python -c "import os,urllib.request,sys; \
sys.exit(0 if b'\"ok\":true' in urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','7860')+'/api/health', timeout=8).read() else 1)"

CMD python -m uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-7860}
