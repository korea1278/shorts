"""제미나이(구글) 예비 엔진 — OpenAI 가 안 될 때(크레딧 소진 등) 대신 쓴다 (2026-10-22 사용자 요청)

키: 환경변수 GEMINI_API_KEY (클라우드 환경 설정에 넣음). 허용 도메인: generativelanguage.googleapis.com
모델이 붐비거나(503) 없어지면(404) 목록의 다음 모델로 넘어간다.

    gemini.text(parts, json_mode=True)   → 답 글 (사진 판별·B-roll 설명)
    gemini.transcribe(mp3_path)          → 받아쓰기 글
    gemini.image(prompt, aspect="3:2")   → PNG 바이트 (무료 등급 키는 그림 0장 — 결제 등록해야 됨)
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
TEXT_MODELS = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-latest", "gemini-3.5-flash-lite"]
IMAGE_MODELS = ["gemini-3.1-flash-image", "gemini-2.5-flash-image", "gemini-3-pro-image"]


def available():
    return bool(os.environ.get("GEMINI_API_KEY"))


def _call(models, payload, timeout=300):
    if not available():
        raise RuntimeError("GEMINI_API_KEY 없음")
    errs = []
    for m in models:
        for attempt in range(2):
            req = urllib.request.Request(API.format(m), data=json.dumps(payload).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    res = json.loads(r.read().decode("utf-8"))
                parts = res["candidates"][0]["content"]["parts"]
                return parts
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")
                try:
                    msg = json.loads(msg)["error"]["message"]
                except Exception:
                    pass
                errs.append(f"{m}: {e.code} {msg.splitlines()[0][:120]}")
                if e.code == 503 and attempt == 0:      # 붐빔 → 잠깐 쉬고 한 번 더
                    time.sleep(3)
                    continue
                break
            except (KeyError, IndexError) as e:
                errs.append(f"{m}: 답이 비어 있음 ({e})")
                break
    raise RuntimeError("제미나이 실패 — " + " / ".join(errs))


def text(parts, json_mode=False, max_tokens=None):
    """parts: 글(str) 또는 {"mime": ..., "data": bytes} 목록"""
    body = []
    for p in parts if isinstance(parts, list) else [parts]:
        if isinstance(p, str):
            body.append({"text": p})
        else:
            body.append({"inlineData": {"mimeType": p["mime"], "data": base64.b64encode(p["data"]).decode()}})
    gc = {}
    if json_mode:
        gc["responseMimeType"] = "application/json"
    if max_tokens:
        gc["maxOutputTokens"] = max_tokens
    out = _call(TEXT_MODELS, {"contents": [{"parts": body}], "generationConfig": gc})
    return "".join(p.get("text", "") for p in out if not p.get("thought"))


def transcribe(mp3_path):
    with open(mp3_path, "rb") as f:
        data = f.read()
    return text(["이 한국어 음성을 들리는 그대로 받아써 주세요. 고치거나 덧붙이지 말고 받아쓴 글만 답하세요.",
                 {"mime": "audio/mpeg", "data": data}]).strip()


def image(prompt, aspect="3:2"):
    out = _call(IMAGE_MODELS, {"contents": [{"parts": [{"text": prompt}]}],
                               "generationConfig": {"responseModalities": ["IMAGE"],
                                                    "imageConfig": {"aspectRatio": aspect}}})
    for p in out:
        if "inlineData" in p:
            return base64.b64decode(p["inlineData"]["data"])
    raise RuntimeError("제미나이가 그림을 안 줌")
