#!/usr/bin/env python3
"""썰 쇼츠 자동 제작 엔진

사용법:
    python3 sseol/make_short.py sseol/jobs/<작업이름>.json
    python3 sseol/make_short.py sseol/jobs/<작업이름>.json --test   # API 없이 시험 렌더

레퍼런스(커뮤니티 썰 쇼츠) 형식 — 자세한 수치는 sseol/REFERENCE.md
  검은 배경 · 맨 위 아주 두꺼운 2줄 제목(노랑/흰) · 가운데 그림(이라스토야 또는 AI)
  · 그림 아래쪽 검은 상자 자막(노랑) · 시작은 게시판 목록에서 글을 클릭하는 화면
  · 자연스러운 나레이션(긴 쉼만 줄임) · 웃음 포인트 효과음 · 배경음악 없음(설정으로 켤 수 있음) · 구독 부탁 없이 끝

장면 그림(images)은 여러 개 넣으면 장면 시간을 나눠 차례로 보여준다. 항목 형식:
  {"ira": "이라스토야 글 주소 또는 그림 주소"}   흰 바탕에 그림 (영상 1편 20장까지)
  {"ai": "English prompt"}                     AI 그림
  "board"                                      게시판 목록 클릭 화면 (보통 첫 장면)
  {"char": "민수", "face": "화남"}              등장인물 표정 (sseol/assets/characters/index.json)
  {"news"|"sns"|"chat"|"map": {...}}           가짜 기사·SNS·문자·지도 화면 (sseol/templates.py)
  그림 항목이나 장면에 "fx": "zoom" 또는 ["shake", "lines"] — 밈 효과 (FX 참고)

대화형 썰 (여러 목소리)
  장면에 "speaker": "엄마" 를 쓰면 그 대사는 그 사람 목소리로 따로 만든다 (없으면 나레이션).
  job 의 "cast": {"엄마": {"voice": "여자", "color": "yellow", "char": "엄마"}}
    voice = config.json 의 voices 이름 (또는 일레븐랩스 목소리 ID), color = 자막 색, char = 표정 라이브러리 인물
  장면 "mood": 화남·억울·놀람·당황·웃음·슬픔·고민 → 자막 색, 목소리 감정(v3 태그), 인물 표정이 같이 바뀐다.
  자막 색 우선순위: 장면 color > mood > cast color > 나레이션 색(대화형은 흰색)
  job "sub_style": "plain" 이면 상자 없이 그림 아래 검은 바탕에 색 글자 (레퍼런스 대화형), 기본 "box".

API 키는 환경변수(ELEVENLABS_API_KEY, OPENAI_API_KEY)가 있으면 쓰고,
없으면 클로드 코드 클라우드 환경의 "API credentials"가 자동으로 붙여준다고 보고 키 없이 요청한다.
"""
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import irasutoya  # noqa: E402
import templates  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
SR = 44100

# ── 레이아웃 (레퍼런스 측정값, 1080x1920 기준) ──────────────────
BG = (0, 0, 0)
TITLE_CENTERS = (268, 400)                  # 제목 두 줄 세로 중심
TITLE_MAX_W = 1040
IMG_TOP, IMG_H = 480, 960                   # 그림 영역 (가로 꽉 참)
SUB_CENTER_Y = 1362                         # 자막 상자 중심 (그림 아래쪽 안)
SUB_MAX_CHARS = 12                          # 자막 한 줄 최대 글자 수 (공백 제외)
SUB_PLAIN_Y = 1560                          # 상자 없는 자막 중심 (그림 아래 검은 바탕)
WHITE, YELLOW, RED = (255, 255, 255), (255, 236, 0), (255, 50, 40)
COLORS = {"white": WHITE, "yellow": YELLOW, "red": RED, "sky": (80, 200, 255), "blue": (90, 140, 255),
          "orange": (255, 150, 30), "green": (80, 230, 120), "pink": (255, 120, 190), "purple": (190, 130, 255),
          "gray": (190, 190, 190)}
# 감정: 자막 색 · 일레븐랩스 v3 감정 태그 · 표정 라이브러리 얼굴
MOODS = {
    "화남": ("red", "[angry]", "화남"),
    "억울": ("yellow", "[frustrated]", "억울"),
    "놀람": ("sky", "[surprised]", "놀람"),
    "당황": ("orange", "[nervous]", "당황"),
    "웃음": ("green", "[laughing]", "웃음"),
    "슬픔": ("blue", "[sad]", "억울"),
    "고민": ("purple", "[thoughtful]", "고민"),
}
NARRATOR = "나레이션"
# 밈 효과 (그림 항목 또는 장면의 "fx")
FX = {
    "zoom": "얼굴 쪽으로 빠르게 확대 (충격·깨달음)",
    "punch": "크게 튀어나왔다가 제자리 (등장·강조)",
    "shake": "화면 흔들림 (분노·충격)",
    "flash": "하얗게 번쩍 (반전 순간)",
    "lines": "만화 집중선 (놀람·강조)",
    "red": "빨간 화면 (분노)",
    "dark": "어두운 가장자리 (절망·공포)",
    "bw": "흑백 (회상·허무)",
}
CHAR_DIR = os.path.join(ROOT, "assets", "characters")
ZOOM_END = 1.04
IRA_LIMIT = 20                              # 이라스토야 영상 1편 최대 장수

DEFAULT_CONFIG = {
    "voice_id": "",                     # 나레이션 목소리 (voices 에 "나레이션" 이 없을 때)
    "voices": {},                       # 대화형 썰 역할별 목소리 {"여자": {"voice_id": ..., "voice_settings": {...}}}
    "mood_tags": True,                  # mood 에 맞춰 v3 감정 태그를 붙인다
    "dialogue_gap": 0.25,               # 화자가 바뀔 때 사이 쉼 (배속 전)
    "tts_model": "eleven_v3",           # 가장 자연스러운 최신 모델 (사용자 선택)
    "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
    "tempo": 1.25,                      # 배속 (목소리 높이는 그대로, 말만 빠르게)
    "max_pause": 0.3,                   # 배속 뒤 이보다 긴 쉼은 줄인다
    "pause_to": 0.22,
    "image_model": "gpt-image-1",
    "image_quality": "medium",
    "image_style": (
        "Simple, cute Japanese-style flat clip-art illustration with soft pastel colors and thin outlines, "
        "plain white background, single clear subject, no text, no letters, no numbers, no logos, no watermark. "
        "No real, identifiable people or celebrities; no existing cartoon characters or memes."
    ),
    "sfx_db": -10,                      # 효과음 크기 (목소리 평균 크기보다 이만큼 작게)
    "bgm": False,                       # 배경음악 (사용자 요청으로 기본 끔)
    "bgm_gap_db": 9,                    # 배경음악을 켤 때 목소리보다 이만큼 작게
    "loudness": -14,
}

FONT_SOURCES = {
    "black": [("Pretendard-Black.otf",
               "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/Pretendard-Black.otf")],
    "bold": [("Pretendard-ExtraBold.otf",
              "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/Pretendard-ExtraBold.otf")],
    "regular": [("Pretendard-Medium.otf",
                 "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/Pretendard-Medium.otf")],
}

DEFAULT_BOARD = [
    "요즘 편의점 알바 근황", "의외로 모르는 사람 많은 생활 꿀팁", "회사에서 있었던 레전드 사건",
    "우리 동네 중국집 사장님 클라스", "생각보다 비싼 물건들", "엄마가 보낸 카톡 모음",
    "군대에서 진짜 있었던 일", "요즘 초등학생들 수준", "택배 기사님이 남긴 메모",
]


def log(*a):
    print("▶", *a, flush=True)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    p = os.path.join(ROOT, "config.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def http_json(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def font_path(kind):
    fdir = os.path.join(ROOT, "fonts")
    os.makedirs(fdir, exist_ok=True)
    for name, url in FONT_SOURCES[kind]:
        p = os.path.join(fdir, name)
        if os.path.exists(p) and os.path.getsize(p) > 10000:
            return p
        urllib.request.urlretrieve(url, p)
        ImageFont.truetype(p, 40)
        log(f"폰트 받음: {name}")
        return p


# ── 나레이션 ────────────────────────────────────────────
def tts_elevenlabs(text, voice, cfg, out_mp3, tag=""):
    """voice = {"voice_id", "voice_settings"}. tag(v3 감정 태그)는 앞에 붙여 읽히고, 글자 타이밍에서는 뺀다."""
    if not voice.get("voice_id"):
        raise RuntimeError("sseol/config.json 에 voice_id(일레븐랩스 목소리 ID)를 넣어주세요")
    headers = {}
    if os.environ.get("ELEVENLABS_API_KEY"):
        headers["xi-api-key"] = os.environ["ELEVENLABS_API_KEY"]
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voice['voice_id']}/with-timestamps"
           f"?output_format=mp3_44100_128")
    sent = f"{tag} {text}" if tag else text
    res = http_json(url, {"text": sent, "model_id": cfg["tts_model"],
                          "voice_settings": voice["voice_settings"]}, headers)
    with open(out_mp3, "wb") as f:
        f.write(base64.b64decode(res["audio_base64"]))
    al = res.get("alignment") or res.get("normalized_alignment")
    chars = "".join(al.get("characters", []))
    st, en = al["character_start_times_seconds"], al["character_end_times_seconds"]
    if chars.endswith(text) and len(st) == len(chars):
        k = len(chars) - len(text)
        return st[k:], en[k:]
    # 글자 수가 안 맞으면(정규화 등) 전체 길이에 고르게 나눈다
    a, b = (st[0] if st else 0.0), (en[-1] if en else 1.0)
    step = (b - a) / max(1, len(text))
    return [a + i * step for i in range(len(text))], [a + (i + 1) * step for i in range(len(text))]


def mp3_to_array(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def shorten_pauses(voice, starts, ends, max_pause, pause_to):
    """긴 쉼을 줄여 쉬지 않고 이어 말하게 한다. 글자 타이밍도 같이 옮긴다."""
    hop = int(SR * 0.01)
    n = len(voice) // hop
    rms = np.sqrt((voice[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
    silent = 20 * np.log10(rms / (rms.max() + 1e-9)) < -38
    cuts = []
    i = 0
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            a, b = i * hop / SR, j * hop / SR
            keep = 0.03 if i == 0 else 0.2 if j == n else (pause_to if b - a > max_pause else b - a)
            if b - a > keep:
                m = (a + b) / 2
                cuts.append((m - (b - a - keep) / 2, m + (b - a - keep) / 2))
            i = j
        else:
            i += 1
    if not cuts:
        return voice, starts, ends
    pieces, last = [], 0
    for a, b in cuts:
        pieces.append(voice[last:int(a * SR)])
        last = int(b * SR)
    pieces.append(voice[last:])

    def remap(t):
        removed = 0.0
        for a, b in cuts:
            if t >= b:
                removed += b - a
            elif t > a:
                removed += t - a
                break
            else:
                break
        return t - removed

    return np.concatenate(pieces), [remap(t) for t in starts], [remap(t) for t in ends]


def speed_up(voice, starts, ends, tempo):
    """목소리 높이는 그대로 두고 배속 (ffmpeg atempo). 글자 타이밍도 같이 줄인다."""
    if abs(tempo - 1.0) < 1e-3:
        return voice, starts, ends
    pcm = (np.clip(voice, -1, 1) * 32767).astype(np.int16).tobytes()
    raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ac", "1", "-ar", str(SR), "-i", "-",
                          "-af", f"atempo={tempo}", "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         input=pcm, check=True, capture_output=True).stdout
    out = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return out, [t / tempo for t in starts], [t / tempo for t in ends]


def insert_pause(voice, starts, ends, at, dur):
    """at 초 위치에 dur 초 쉼을 넣는다 (웃음 포인트 앞 '뜸')."""
    k = int(at * SR)
    voice = np.concatenate([voice[:k], np.zeros(int(dur * SR), np.float32), voice[k:]])
    starts = [t + dur if t >= at - 1e-6 else t for t in starts]
    ends = [t + dur if t > at else t for t in ends]
    return voice, starts, ends


# ── 그림 ────────────────────────────────────────────────
def gen_image(prompt, cfg, out_png):
    headers = {}
    if os.environ.get("OPENAI_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["OPENAI_API_KEY"]
    res = http_json("https://api.openai.com/v1/images/generations",
                    {"model": cfg["image_model"], "prompt": f"{prompt}\n\nStyle: {cfg['image_style']}",
                     "size": "1536x1024", "quality": cfg["image_quality"], "n": 1}, headers)
    with open(out_png, "wb") as f:
        f.write(base64.b64decode(res["data"][0]["b64_json"]))


def fetch_irasutoya(ref, out_png):
    """글 주소면 그 글의 첫 그림(또는 #2 처럼 번호, #angry 처럼 파일 이름 일부), 그림 주소면 그대로 받는다."""
    url, n, key = ref, 1, None
    m = re.match(r"(.*)#([^#/]+)$", ref)
    if m:
        url = m.group(1)
        n, key = (int(m.group(2)), None) if m.group(2).isdigit() else (1, m.group(2))
    if re.search(r"irasutoya\.com/\d{4}/\d{2}/", url):
        imgs = irasutoya.images(url)
        if key:
            imgs = [u for u in imgs if key in u.rsplit("/", 1)[-1]]
        if not imgs:
            raise RuntimeError(f"이라스토야 그림을 못 찾음: {ref}")
        url = imgs[min(n, len(imgs)) - 1]
    data = irasutoya.get(url)
    with open(out_png, "wb") as f:
        f.write(data)
    return url


def fit_into(img, w, h, bg=(255, 255, 255), pad=36):
    """흰 바탕 w x h 안에 그림을 비율 그대로 넣는다 (투명 부분은 흰색)."""
    canvas = Image.new("RGB", (w, h), bg)
    im = img.convert("RGBA")
    s = min((w - 2 * pad) / im.width, (h - 2 * pad) / im.height)
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
    return canvas


def cover(img, w, h):
    s = max(w / img.width, h / img.height)
    im = img.convert("RGB").resize((math.ceil(img.width * s), math.ceil(img.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def placeholder_image(i, label, w, h):
    rng = np.random.default_rng(i + 7)
    c = tuple(int(v) for v in rng.integers(150, 235, 3))
    im = Image.new("RGB", (w, h), c)
    d = ImageDraw.Draw(im)
    d.text((w / 2, h / 2), f"그림 {i}", font=ImageFont.truetype(font_path("bold"), 70), fill=(60, 60, 60),
           anchor="mm")
    return im


# ── 게시판 목록 클릭 화면 ──────────────────────────────────
def make_board(post_title, others):
    """어두운 게시판 목록 (사이트 이름·로고 없음). 가운데 줄이 이번 글."""
    rows = 9
    rh = IMG_H // rows
    im = Image.new("RGB", (W, IMG_H), (14, 14, 18))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(font_path("regular"), 38)
    fb = ImageFont.truetype(font_path("bold"), 38)
    titles = list(others[:rows - 1])
    titles.insert(rows // 2, post_title)
    for i, t in enumerate(titles):
        y = i * rh
        me = i == rows // 2
        if me:
            d.rectangle((0, y, W, y + rh), fill=(44, 34, 74))
        d.line((0, y + rh - 1, W, y + rh - 1), fill=(32, 32, 40), width=2)
        d.rounded_rectangle((28, y + rh / 2 - 13, 56, y + rh / 2 + 13), 4,
                            outline=(120, 170, 120) if me else (70, 90, 70), width=3)
        d.text((76, y + rh / 2), t, font=fb if me else f, fill=(250, 250, 250) if me else (110, 110, 118),
               anchor="lm")
    return im


def make_cursor(scale=1.0):
    s = int(64 * scale)
    cur = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(cur)
    pts = [(0.05, 0.02), (0.05, 0.78), (0.24, 0.6), (0.38, 0.92), (0.5, 0.86), (0.36, 0.55), (0.62, 0.55)]
    d.polygon([(x * s, y * s) for x, y in pts], fill=(255, 255, 255), outline=(0, 0, 0), width=max(2, s // 20))
    return cur


# ── 소리 (직접 합성) ─────────────────────────────────────
def _env(n, a=0.005, decay=8.0):
    t = np.arange(n) / SR
    return np.minimum(1, t / a) * np.exp(-t * decay)


def sfx(name):
    t = np.arange(int(SR * 0.6)) / SR
    if name == "pop":
        n = int(SR * 0.12)
        tt = t[:n]
        out = np.sin(2 * np.pi * (500 * tt + 4000 * tt ** 2)) * _env(n, 0.002, 30)
    elif name == "ding":
        out = (np.sin(2 * np.pi * 1318.5 * t) + 0.35 * np.sin(2 * np.pi * 2637 * t)
               + 0.15 * np.sin(2 * np.pi * 3955.5 * t)) * _env(len(t), 0.003, 6)
    elif name == "kaching":                     # 띠링 (돈 소리)
        out = np.zeros(len(t))
        for st, fr in ((0.0, 2093.0), (0.09, 2637.0)):
            k = int(st * SR)
            tt = np.arange(len(t) - k) / SR
            out[k:] += (np.sin(2 * np.pi * fr * tt) + 0.4 * np.sin(2 * np.pi * fr * 1.5 * tt)) * _env(len(tt), 0.002, 9)
    elif name == "tada":                        # 짜잔
        out = np.zeros(int(SR * 0.9))
        for st, fr in ((0.0, 523.25), (0.12, 783.99)):
            k = int(st * SR)
            n = len(out) - k
            tt = np.arange(n) / SR
            out[k:] += sum(np.sin(2 * np.pi * fr * h * tt) / h for h in (1, 2, 3)) * _env(n, 0.005, 3.5)
    elif name == "boing":
        f = 180 + 120 * np.exp(-t * 6) * np.sin(2 * np.pi * 9 * t)
        out = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(len(t), 0.005, 5)
    elif name == "whoosh":
        rng = np.random.default_rng(3)
        nz = rng.standard_normal(len(t))
        k = np.convolve(nz, np.ones(12) / 12, "same")
        out = (nz - k) * np.sin(np.pi * t / t[-1]) ** 2 * 0.6
    elif name == "dundun":                      # 두둥
        out = np.zeros(len(t))
        for st in (0.0, 0.22):
            k = int(st * SR)
            n = len(t) - k
            tt = np.arange(n) / SR
            out[k:] += np.sin(2 * np.pi * (70 * tt - 30 * tt ** 2)) * _env(n, 0.003, 6)
    elif name == "fail":                        # 띠로리 (내려가는 세 음)
        out = np.zeros(int(SR * 0.9))
        for i, fr in enumerate((523, 494, 466)):
            k = int(i * 0.22 * SR)
            n = int(0.3 * SR)
            tt = np.arange(n) / SR
            out[k:k + n] += np.sign(np.sin(2 * np.pi * fr * tt)) * 0.35 * _env(n, 0.004, 5)
    else:
        return np.zeros(1, np.float32)
    return (out / (np.abs(out).max() + 1e-9) * 0.22).astype(np.float32)


def load_sfx(name):
    """sseol/sfx/<이름>.mp3(.wav) 가 있으면 그 소리, 없으면 직접 만든 소리"""
    for ext in (".mp3", ".wav"):
        p = os.path.join(ROOT, "sfx", name + ext)
        if os.path.exists(p):
            return mp3_to_array(p)
    return sfx(name)


def pluck(freq, dur, rng):
    """카플러스-스트롱 기타 뜯는 소리"""
    n = int(SR * dur)
    p = max(2, int(SR / freq))
    buf = rng.uniform(-1, 1, p)
    out = np.zeros(n)
    for i in range(n):
        out[i] = buf[i % p]
        buf[i % p] = 0.5 * (buf[i % p] + buf[(i + 1) % p]) * 0.996
    return out


def make_bgm(total, rms_target):
    """저작권 걱정 없는 경쾌한 배경음악 (120BPM 기타 뜯기 + 가벼운 박자)"""
    rng = np.random.default_rng(5)
    beat = 0.5
    prog = [(261.63, 329.63, 392.00), (196.00, 246.94, 293.66),
            (220.00, 261.63, 329.63), (174.61, 220.00, 261.63)]   # C G Am F
    notes = {}
    n = int(SR * (total + 1))
    out = np.zeros(n)
    step = beat / 2
    k = 0
    while k * step < total + 0.5:
        bar = int(k * step // (beat * 4))
        ch = prog[bar % 4]
        pat = [0, 1, 2, 1, 0, 2, 1, 2]
        f = ch[pat[k % 8]] * (2 if k % 8 in (2, 5) else 1)
        key = round(f, 1)
        if key not in notes:
            notes[key] = pluck(f, 0.6, rng)
        a = int(k * step * SR)
        seg = notes[key][:n - a]
        out[a:a + len(seg)] += seg * (1.0 if k % 2 == 0 else 0.7)
        if k % 2 == 0:                                         # 가벼운 하이햇
            hh = rng.standard_normal(int(0.03 * SR)) * _env(int(0.03 * SR), 0.001, 120) * 0.25
            out[a:a + len(hh)] += hh[:n - a]
        if k % 4 == 0:                                         # 부드러운 킥
            kn = int(0.18 * SR)
            tt = np.arange(kn) / SR
            kick = np.sin(2 * np.pi * (90 * tt - 120 * tt ** 2)) * _env(kn, 0.002, 18) * 0.8
            out[a:a + kn] += kick[:n - a]
        k += 1
    out = out[:int(SR * total)]
    return (out / (np.sqrt((out ** 2).mean()) + 1e-9) * rms_target).astype(np.float32)


def load_bgm(path, total):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", path, "-t", f"{total:.2f}",
                          "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


# ── 글자 ────────────────────────────────────────────────
def fit_font(path, lines, max_w, start, min_size=40):
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    size = start
    while size > min_size:
        f = ImageFont.truetype(path, size)
        if all(tmp.textlength(l, font=f) <= max_w for l in lines):
            return f
        size -= 2
    return ImageFont.truetype(path, min_size)


def make_title(lines, yellow_line):
    layer = Image.new("RGBA", (W, IMG_TOP), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lines = [l for l in lines if l][:2]
    f = fit_font(font_path("black"), lines, TITLE_MAX_W, 136, 70)
    centers = TITLE_CENTERS if len(lines) == 2 else ((TITLE_CENTERS[0] + TITLE_CENTERS[1]) // 2,)
    for i, l in enumerate(lines):
        d.text((W / 2, centers[i]), l, font=f, fill=YELLOW if i == yellow_line else WHITE, anchor="mm")
    return layer


def chunk_text(text, max_chars=SUB_MAX_CHARS):
    words = text.split()
    chunks, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand.replace(" ", "")) > max_chars and cur:
            chunks.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        if chunks and len(cur.replace(" ", "")) <= 3:      # "함" 같은 짧은 꼬리는 앞 줄에 붙인다
            chunks[-1] += " " + cur
        else:
            chunks.append(cur)
    return chunks


def rgb(color):
    """색 이름(white, yellow, red, sky, orange, green ...) 또는 "#RRGGBB" → (r, g, b)"""
    if isinstance(color, (list, tuple)):
        return tuple(color)
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    return COLORS.get(color, YELLOW)


def make_sub(text, color, reds, style="box", label=None):
    """box: 검은 상자 + 색 글자 / plain: 상자 없이 검은 테두리 색 글자 (그림 아래 검은 바탕용).
    reds 에 든 단어는 빨간색. label 이 있으면 위에 작게 화자 이름."""
    plain = style == "plain"
    f = fit_font(font_path("bold"), [text], W - 100, 68 if plain else 62, 42)
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = text.split(" ")
    sp = tmp.textlength(" ", font=f)
    widths = [tmp.textlength(w, font=f) for w in words]
    tw = sum(widths) + sp * (len(words) - 1)
    asc, desc = f.getmetrics()
    bw, bh = int(tw + 36), int(asc + desc + 14)
    lh = 64 if label else 0
    layer = Image.new("RGBA", (W, bh + lh), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0 = (W - bw) // 2
    base = rgb(color)
    if label:
        d.text((W / 2, lh / 2 - 6), label, font=ImageFont.truetype(font_path("bold"), 42), fill=base,
               anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0))
    if not plain:
        d.rectangle((x0, lh, x0 + bw, lh + bh), fill=(0, 0, 0, 235))
    x = x0 + 18
    rs = {w for r in (reds or []) for w in r.split()}
    for w, ww in zip(words, widths):
        d.text((x, lh + bh / 2), w, font=f, fill=RED if w in rs else base, anchor="lm",
               stroke_width=5 if plain else 0, stroke_fill=(0, 0, 0))
        x += ww + sp
    layer.info["cy"] = lh + bh // 2               # 글자 줄의 세로 중심 (붙일 때 기준)
    return layer


def load_characters():
    p = os.path.join(CHAR_DIR, "index.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("characters", {})


# ── 밈 효과 ─────────────────────────────────────────────
def static_fx(img, fx):
    """색을 바꾸는 효과는 그림에 한 번만 입힌다"""
    if "bw" in fx:
        img = img.convert("L").convert("RGB")
    if "red" in fx:
        img = Image.blend(img, Image.new("RGB", img.size, (230, 20, 20)), 0.33)
    if "red" in fx or "dark" in fx:
        yy, xx = np.mgrid[0:img.height, 0:img.width]
        r = np.sqrt(((xx - img.width / 2) / (img.width / 2)) ** 2 + ((yy - img.height / 2) / (img.height / 2)) ** 2)
        k = np.clip(1.25 - r * (0.75 if "dark" in fx else 0.45), 0.15, 1.0)[..., None]
        img = Image.fromarray((np.asarray(img, np.float32) * k).astype(np.uint8))
    return img


_LINES = {}


def speed_lines(v):
    """만화 집중선 (가장자리에서 가운데로 모이는 검은 선). 4가지를 번갈아 써서 살짝 움직이게"""
    if v not in _LINES:
        rng = np.random.default_rng(v + 11)
        im = Image.new("RGBA", (W, IMG_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        cx, cy, R = W / 2, IMG_H / 2, math.hypot(W, IMG_H)
        for _ in range(110):
            ang = rng.uniform(0, 2 * math.pi)
            r0 = rng.uniform(0.36, 0.5) * min(W, IMG_H) * 1.15
            wd = rng.uniform(0.004, 0.013)
            pts = [(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang)),
                   (cx + R * math.cos(ang - wd), cy + R * math.sin(ang - wd)),
                   (cx + R * math.cos(ang + wd), cy + R * math.sin(ang + wd))]
            d.polygon(pts, fill=(0, 0, 0, 225))
        _LINES[v] = im
    return _LINES[v]


# ── 메인 ────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    job_path = sys.argv[1]
    test_mode = "--test" in sys.argv
    cfg = load_config()
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    job_id = job.get("id") or os.path.splitext(os.path.basename(job_path))[0]
    out_dir = os.path.join(ROOT, "output", job_id)
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)
    scenes = job["scenes"]

    # 1) 나레이션 원고
    full, spans = "", []
    for s in scenes:
        t = re.sub(r"\s+", " ", s["text"]).strip()
        if full:
            full += " "
        spans.append((len(full), len(full) + len(t)))
        full += t
    log(f"나레이션 {len(full)}자 (공백 제외 {len(full.replace(' ', ''))}자), 장면 {len(scenes)}개")

    # 2) 나레이션 생성 — 같은 목소리·감정이 이어지는 장면끼리 묶어 한 번에 만든다
    cast = job.get("cast") or {}
    voices = cfg.get("voices") or {}

    def speaker_of(s):
        return s.get("speaker") or NARRATOR

    def voice_of(name):
        key = (cast.get(name) or {}).get("voice", name)
        v = voices.get(key)
        if v is None and re.fullmatch(r"[A-Za-z0-9]{16,}", str(key)):
            v = key                                         # 일레븐랩스 목소리 ID 를 바로 쓴 경우
        if v is None:
            if name != NARRATOR:
                log(f"⚠ '{name}' 목소리가 config.json voices 에 없어 나레이션 목소리로 읽습니다")
            v = voices.get(NARRATOR) or cfg["voice_id"]
        if isinstance(v, str):
            v = {"voice_id": v}
        return {"voice_id": v.get("voice_id", ""), "voice_settings": v.get("voice_settings", cfg["voice_settings"])}

    groups = []                                             # [첫 장면, 끝 장면, 목소리, 감정 태그]
    for i, s in enumerate(scenes):
        v = voice_of(speaker_of(s))
        tag = MOODS[s["mood"]][1] if cfg.get("mood_tags") and s.get("mood") in MOODS else ""
        if groups and groups[-1][2] == v and groups[-1][3] == tag:
            groups[-1][1] = i
        else:
            groups.append([i, i, v, tag])
    speakers = sorted({speaker_of(s) for s in scenes})
    if speakers != [NARRATOR]:
        log(f"대화형: 화자 {len(speakers)}명 ({', '.join(speakers)}), 목소리 묶음 {len(groups)}개")

    if test_mode:
        per = 0.15
        starts = [i * per for i in range(len(full))]
        ends = [(i + 1) * per for i in range(len(full))]
        voice = np.zeros(int(SR * (len(full) * per)), dtype=np.float32)
        log("시험 모드: 무음 나레이션")
    else:
        pieces, starts, ends, t0 = [], [0.0] * len(full), [0.0] * len(full), 0.0
        gap = float(cfg.get("dialogue_gap", 0.25))
        reused = 0
        for gi, (g0, g1, v, tag) in enumerate(groups):
            ca, cb = spans[g0][0], spans[g1][1]
            text = full[ca:cb]
            meta = json.dumps([text, v, cfg["tts_model"], tag], ensure_ascii=False, sort_keys=True)
            # 파일 이름을 내용으로 정해서, 장면을 넣거나 빼도 안 바뀐 대사는 다시 만들지 않는다
            mp3 = os.path.join(work, f"voice_{hashlib.sha1(meta.encode()).hexdigest()[:10]}.mp3")
            saved = {}
            if os.path.exists(mp3) and os.path.exists(mp3 + ".json"):
                with open(mp3 + ".json") as f:
                    saved = json.load(f)
            if saved.get("meta") == meta:
                st, en = saved["starts"], saved["ends"]
                reused += 1
            else:
                log(f"일레븐랩스 목소리 만드는 중… ({gi + 1}/{len(groups)}) {speaker_of(scenes[g0])} {tag}".rstrip())
                st, en = tts_elevenlabs(text, v, cfg, mp3, tag)
                with open(mp3 + ".json", "w") as f:
                    json.dump({"meta": meta, "starts": st, "ends": en}, f)
            arr = mp3_to_array(mp3)
            act = arr[np.abs(arr) > 0.02]                   # 목소리마다 크기가 달라서 같은 크기로 맞춘다
            if len(act):
                arr = np.clip(arr * (0.1 / (np.sqrt((act ** 2).mean()) + 1e-9)), -1, 1)
            if gi:
                pieces.append(np.zeros(int(SR * gap), np.float32))
                starts[ca - 1], ends[ca - 1] = t0, t0 + gap  # 묶음 사이 띄어쓰기 자리
                t0 += gap
            for k in range(len(text)):
                starts[ca + k], ends[ca + k] = t0 + st[k], t0 + en[k]
            pieces.append(arr.astype(np.float32))
            t0 += len(arr) / SR
        if reused:
            log(f"이전에 만든 목소리 {reused}개 재사용")
        voice = np.concatenate(pieces)
        voice, starts, ends = speed_up(voice, starts, ends, float(cfg.get("tempo", 1.0)))
        voice, starts, ends = shorten_pauses(voice, starts, ends, cfg["max_pause"], cfg["pause_to"])
    for i in range(len(scenes) - 1, 0, -1):               # 웃음 포인트 앞 '뜸'
        if scenes[i].get("pause"):
            at = starts[spans[i][0]] - 0.02
            voice, starts, ends = insert_pause(voice, starts, ends, at, float(scenes[i]["pause"]))
    voice_len = len(voice) / SR
    log(f"나레이션 {voice_len:.1f}초 (초당 {len(full.replace(' ', '')) / voice_len:.1f}글자)")
    total = voice_len + 0.35

    def t_at(ci, use_end=False):
        ci = max(0, min(ci, len(starts) - 1))
        return ends[ci] if use_end else starts[ci]

    scene_times = []
    for i, (a, b) in enumerate(spans):
        st = 0.0 if i == 0 else t_at(a)
        en = total if i == len(spans) - 1 else t_at(spans[i + 1][0])
        scene_times.append((st, en))

    # 3) 자막 (장면별 sub 가 있으면 그 글로, 없으면 나레이션을 잘라서)
    dialogue = speakers != [NARRATOR] or bool(cast)
    narr_color = job.get("narration_color", "white" if dialogue else "yellow")

    def color_of(s):
        if s.get("color"):
            return s["color"]
        if s.get("mood") in MOODS:
            return MOODS[s["mood"]][0]
        return (cast.get(speaker_of(s)) or {}).get("color") or narr_color

    subs = []
    for i, s in enumerate(scenes):
        a, b = spans[i]
        color, reds = color_of(s), s.get("red", [])
        style = s.get("sub_style", job.get("sub_style", "box"))
        label = speaker_of(s) if job.get("show_speaker") and speaker_of(s) != NARRATOR else None
        y = SUB_PLAIN_Y if style == "plain" else SUB_CENTER_Y

        def sub(text):
            return make_sub(text, color, reds, style, label), y
        if s.get("sub") is not None:
            lines = s["sub"] if isinstance(s["sub"], list) else [s["sub"]]
            st, en = scene_times[i]
            for j, l in enumerate(lines):
                if l:
                    subs.append([st + (en - st) * j / len(lines), st + (en - st) * (j + 1) / len(lines), *sub(l)])
            continue
        seg = full[a:b]
        pos = 0
        for ch in chunk_text(seg):
            k = seg.find(ch, pos)
            k = pos if k < 0 else k
            pos = k + len(ch)
            subs.append([t_at(a + k), t_at(a + pos - 1, True), *sub(re.sub(r"[.,…]+", "", ch).strip())])
    subs.sort(key=lambda x: x[0])
    for j in range(len(subs) - 1):
        subs[j][1] = subs[j + 1][0]
    if subs:
        subs[-1][1] = total

    # 4) 그림
    post_title = job.get("post_title") or " ".join(job["title"])
    board = make_board(post_title, job.get("board") or DEFAULT_BOARD)
    slots = []           # (시작, 끝, 그림 또는 "board")
    credits, ira_files, n = [], {}, 0
    chars = load_characters()
    fonts_cache = {}

    def tfont(size, kind="bold"):
        if (size, kind) not in fonts_cache:
            fonts_cache[size, kind] = ImageFont.truetype(font_path(kind), size)
        return fonts_cache[size, kind]

    def ira_image(ref, p):
        """같은 그림은 한 번만 받고 한 장으로 센다"""
        if ref not in ira_files:
            if len(ira_files) >= IRA_LIMIT:
                raise RuntimeError(f"이라스토야 그림이 {IRA_LIMIT}장을 넘었습니다. 일부를 AI 그림으로 바꿔 주세요")
            ira_files[ref] = p
            credits.append(ref)
        p = ira_files[ref]
        if test_mode and not os.path.exists(p):
            return placeholder_image(n, "", W, IMG_H)
        if not os.path.exists(p):
            log(f"이라스토야 그림 받는 중… ({os.path.basename(p)})")
            fetch_irasutoya(ref, p)
        return Image.open(p)

    def picture(it, p):
        """그림 항목 → (그림, 넣는 방식: pad 흰 여백 / full 여백 없음 / cover 꽉 채움)"""
        if "char" in it:
            ch = chars.get(it["char"])
            if not ch:
                raise RuntimeError(f"등장인물 '{it['char']}' 이 sseol/assets/characters/index.json 에 없습니다")
            ref = ch["faces"].get(it.get("face") or "기본") or ch["faces"].get("기본")
            if ch.get("source") == "ira":
                return ira_image(ref, os.path.join(work, "char_" + re.sub(r"\W", "_", ref[-40:]) + ".png")), "pad"
            return Image.open(os.path.join(CHAR_DIR, ref)).convert("RGBA"), "pad"
        if "ira" in it:
            return ira_image(it["ira"], p), "pad"
        if not os.path.exists(p):
            if test_mode:
                placeholder_image(n, "", W, IMG_H).save(p)
            else:
                log(f"AI 그림 만드는 중… ({os.path.basename(p)})")
                gen_image(it["ai"], cfg, p)
        return Image.open(p), "cover" if it.get("fill") else "full"

    def add(slot):
        """칸 추가 + 밈 효과 중 색 바꾸기(red·dark·bw)는 미리 그림에 입힌다"""
        a, b, img = slot
        bad = [f for f in cur_fx if f not in FX]
        if bad:
            raise RuntimeError(f"모르는 효과 {bad}. 쓸 수 있는 것: {', '.join(FX)}")
        if img != "board":
            img = static_fx(img, cur_fx)
        slots.append((a, b, img, cur_fx))

    for i, s in enumerate(scenes):
        items = s.get("images")
        if not items:
            c = (cast.get(speaker_of(s)) or {}).get("char")
            face = MOODS[s["mood"]][2] if s.get("mood") in MOODS else "기본"
            items = ["board"] if i == 0 else [{"char": c, "face": face}] if c else [{"ai": s["text"]}]
        st, en = scene_times[i]
        for j, it in enumerate(items):
            a = st + (en - st) * j / len(items)
            b = st + (en - st) * (j + 1) / len(items)
            fx = (it.get("fx") if isinstance(it, dict) else None) or s.get("fx") or []
            cur_fx = [fx] if isinstance(fx, str) else list(fx)
            if it == "board":
                add((a, b, "board"))
                continue
            n += 1
            p = os.path.join(work, f"img_{i + 1:02d}_{j + 1}.png")
            kind = next((k for k in templates.TEMPLATES if k in it), None)
            if kind:
                spec = it[kind]
                templates.check_names(kind, spec)
                pic = picture(spec["img"], p)[0] if spec.get("img") else None
                if kind == "chat" and spec.get("reveal"):           # 말풍선이 하나씩 올라온다
                    m = max(1, len(spec.get("msgs", [])))
                    for k in range(m):
                        add((a + (b - a) * k / m, a + (b - a) * (k + 1) / m,
                                      templates.render_chat(spec, W, IMG_H, tfont, k + 1)))
                elif kind == "chat":
                    add((a, b, templates.render_chat(spec, W, IMG_H, tfont)))
                elif kind == "map":
                    add((a, b, templates.render_map(spec, W, IMG_H, tfont)))
                else:
                    render = templates.render_news if kind == "news" else templates.render_sns
                    add((a, b, render(spec, W, IMG_H, tfont, pic)))
                continue
            img, how = picture(it, p)
            add((a, b, cover(img, W, IMG_H) if how == "cover"
                          else fit_into(img, W, IMG_H, pad=0 if how == "full" else 36)))
    n_ira = len(ira_files)
    with open(os.path.join(out_dir, "credits.txt"), "w", encoding="utf-8") as f:
        f.write(f"이라스토야 그림 {n_ira}장 (영상 1편 {IRA_LIMIT}장까지)\n")
        f.write("\n".join(credits) + "\n")
    log(f"그림 {len(slots)}칸 (이라스토야 {n_ira}장)")

    # 5) 소리
    mix = np.zeros(int(SR * total), dtype=np.float32)
    mix[:len(voice)] += voice[:len(mix)]
    voiced = voice[np.abs(voice) > 0.02]
    vrms = float(np.sqrt((voiced ** 2).mean())) if len(voiced) else 0.1
    for i, s in enumerate(scenes):
        if s.get("sfx"):
            fx = load_sfx(s["sfx"])
            act = fx[np.abs(fx) > np.abs(fx).max() * 0.05]          # 소리 나는 부분의 크기 기준
            fx = fx / (np.sqrt((act ** 2).mean()) + 1e-9) * vrms * 10 ** (cfg["sfx_db"] / 20)
            at = scene_times[i][0]
            if s.get("sfx_on"):                              # 이 단어가 나올 때 맞춰서
                k = full.find(s["sfx_on"], spans[i][0], spans[i][1])
                if k >= 0:
                    at = t_at(k)
            at += float(s.get("sfx_at", 0))
            k = max(0, int(at * SR))
            mix[k:k + len(fx)] += fx[:len(mix) - k]
    voiced = voice[np.abs(voice) > 0.02]
    vrms = float(np.sqrt((voiced ** 2).mean())) if len(voiced) else 0.1
    target = vrms * 10 ** (-cfg["bgm_gap_db"] / 20)
    bdir = os.path.join(ROOT, "bgm")
    cands = sorted(f for f in os.listdir(bdir) if f.lower().endswith((".mp3", ".wav", ".m4a"))) \
        if os.path.isdir(bdir) else []
    if not cfg.get("bgm"):
        log("배경음악: 없음")
    elif cands:
        name = job.get("bgm") if job.get("bgm") in cands else cands[0]
        log(f"배경음악: {name}")
        b = load_bgm(os.path.join(bdir, name), total)[:len(mix)]
        mix[:len(b)] += b / (np.sqrt((b ** 2).mean()) + 1e-9) * target
    else:
        log("배경음악: 직접 만든 경쾌한 기타 반주")
        mix += make_bgm(total, target)[:len(mix)]
    fade = int(SR * 0.25)
    mix[-fade:] *= np.linspace(1, 0, fade)
    wav_path = os.path.join(work, "mix.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())

    # 음량 맞추기 (loudnorm 2단계: 먼저 재고, 잰 값으로 정확히 맞춤)
    lt = cfg["loudness"]
    meas = subprocess.run(["ffmpeg", "-v", "info", "-i", wav_path, "-af",
                           f"loudnorm=I={lt}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    m = json.loads(meas[meas.rfind("{"):meas.rfind("}") + 1])
    loudnorm = (f"loudnorm=I={lt}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
                f"offset={m['target_offset']}:linear=true")

    # 6) 화면
    title = make_title(job["title"], int(job.get("title_yellow", 0)))
    cursors = [make_cursor(1.0), make_cursor(0.85)]
    out_mp4 = os.path.join(out_dir, f"{job_id}.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", wav_path, "-map", "0:v", "-map", "1:a",
           "-af", loudnorm,
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-shortest", "-movflags", "+faststart", out_mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n_frames = int(total * FPS)
    si, sub_i = 0, 0
    log(f"영상 합성 중… ({total:.1f}초, {n_frames}프레임)")
    row_y = IMG_TOP + (IMG_H // 9) * 4 + (IMG_H // 9) // 2
    for fi in range(n_frames):
        t = fi / FPS
        while si < len(slots) - 1 and t >= slots[si][1]:
            si += 1
        st, en, src, fx = slots[si]
        frame = Image.new("RGB", (W, H), BG)
        if src == "board":
            frame.paste(board, (0, IMG_TOP))
            p = min(1.0, (t - st) / 0.7)
            p = 1 - (1 - p) ** 3
            cx, cy = int(420 + (130 - 420) * p), int(row_y + 200 + (8 - 200) * p)
            click = 0.75 <= t - st < 0.9
            frame.paste(cursors[1 if click else 0], (cx, cy), cursors[1 if click else 0])
        else:
            prog = min(1.0, max(0.0, (t - st) / max(0.1, en - st)))
            z = 1.0 + (ZOOM_END - 1.0) * prog
            dt = t - st
            cx, cy = W / 2, IMG_H / 2
            if "zoom" in fx:                                  # 0.3초 만에 얼굴 쪽으로 1.35배
                e = 1 - (1 - min(1.0, dt / 0.3)) ** 3
                z *= 1 + 0.35 * e
                cy = IMG_H / 2 - IMG_H * 0.1 * e
            if "punch" in fx:                                 # 1.25배에서 0.15초 만에 제자리
                z *= 1 + 0.25 * max(0.0, 1 - dt / 0.15)
            if "shake" in fx and dt < 0.6:
                z *= 1.05
                amp = 22 * (1 - dt / 0.6)
                cx += amp * math.sin(dt * 95)
                cy += amp * math.cos(dt * 71)
            cw, chh = W / z, IMG_H / z
            x0, y0 = cx - cw / 2, cy - chh / 2
            pic = src.resize((W, IMG_H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + chh))
            if "lines" in fx:
                lines_fx = speed_lines(fi // 3 % 4)
                pic.paste(lines_fx, (0, 0), lines_fx)
            if "flash" in fx and dt < 0.25:
                pic = Image.blend(pic, Image.new("RGB", pic.size, (255, 255, 255)), 0.9 * (1 - dt / 0.25))
            frame.paste(pic, (0, IMG_TOP))
        frame.paste(title, (0, 0), title)
        while sub_i < len(subs) - 1 and t >= subs[sub_i][1]:
            sub_i += 1
        if subs and subs[sub_i][0] - 0.05 <= t < subs[sub_i][1] and src != "board":
            layer, y = subs[sub_i][2], subs[sub_i][3]
            frame.paste(layer, (0, y - layer.info["cy"]), layer)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 실패")
    log(f"완성: {out_mp4}")
    return out_mp4


if __name__ == "__main__":
    main()
