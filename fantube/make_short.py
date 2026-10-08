#!/usr/bin/env python3
"""팬튜브 쇼츠 자동 제작 엔진

사용법:
    python3 fantube/make_short.py fantube/jobs/<작업이름>.json
    python3 fantube/make_short.py fantube/jobs/<작업이름>.json --test   # API 없이 시험 렌더

작업 파일(JSON) 하나로 9:16 쇼츠를 만든다. (레퍼런스 분석 형식)
  상단 둥근 검은 판에 2줄 제목(흰색/노란색) · 화면 가득 세로 사진(약 2초마다 교체, 천천히 확대)
  · 사진 위 가운데 흰색 한 줄 자막 · 하단 좋아요·구독 버튼 애니메이션
  · 장면 전환 '띵' 효과음 · 잔잔한 배경음악 · 일레븐랩스 나레이션(빠르게, 쉼 짧게, 글자 단위 싱크)

장면의 그림은 "image": "프롬프트" 하나 또는 "images": ["프롬프트1", "프롬프트2"] 여러 개.
여러 개면 장면 시간을 나눠서 차례로 보여준다.

API 키는 환경변수(ELEVENLABS_API_KEY, OPENAI_API_KEY)가 있으면 쓰고,
없으면 클로드 코드 클라우드 환경의 "API credentials"가 자동으로 붙여준다고 보고 키 없이 요청한다.
"""
import base64
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

ROOT = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
SR = 44100

# ── 레이아웃 (레퍼런스 측정값, 1080x1920 기준) ──────────────────
BG = (30, 20, 20)                           # 제목 판·하단 띠 색 (짙은 밤색 검정)
PANEL_H, PANEL_R = 414, 34                  # 상단 제목 판 높이·아래 모서리 둥글기
TITLE_CENTERS = (252, 342)                  # 제목 두 줄의 세로 중심
TITLE_MAX_W = 990                           # 제목 최대 폭 (화면의 약 92%)
IMG_TOP, IMG_BOTTOM = 380, 1830             # 사진 영역 (판 뒤로 살짝 들어감)
BAND_TOP = 1800                             # 하단 구독 버튼 띠 시작
SUB_CENTER_Y = 1140                         # 자막 중심 (위에서 약 60%)
SUB_MAX_CHARS = 12                          # 자막 한 줄 최대 글자 수 (공백 제외)
WHITE, YELLOW = (255, 255, 255), (255, 222, 60)
ZOOM_END = 1.06                             # 사진마다 천천히 확대

DEFAULT_CONFIG = {
    "voice_id": "",                     # 일레븐랩스 목소리 ID (config.json에서 지정)
    "tts_model": "eleven_multilingual_v2",
    "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.15,
                       "use_speaker_boost": True, "speed": 1.2},
    "max_pause": 0.15,                  # 이보다 긴 쉼은 줄인다 (초)
    "pause_to": 0.10,                   # 줄인 쉼 길이 (초)
    "image_model": "gpt-image-1",
    "image_quality": "medium",
    "image_style": (
        "Realistic documentary-style photograph, warm nostalgic film tones, soft natural light, "
        "vertical portrait composition, no text, no letters, no numbers, no logos, no watermark. "
        "Never depict a real, identifiable person or celebrity likeness: show people only from behind, "
        "in silhouette, at a distance, out of focus, or as hands and details; prefer objects, places and atmosphere."
    ),
    "sub_highlight": False,             # 레퍼런스처럼 자막은 흰색만 (True면 강조 단어 노란색)
    "bgm_volume": 0.12,                 # bgm 폴더 음악 파일 음량
    "bgm_gap_db": 22,                   # 직접 만든 배경음악은 목소리보다 이만큼 작게
    "loudness": -14,                    # 최종 음량 (유튜브 기준 LUFS)
}

FONT_SOURCES = {
    "title": [
        ("GmarketSansBold.woff", "https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_2001@1.1/GmarketSansBold.woff"),
        ("BlackHanSans-Regular.ttf", "https://raw.githubusercontent.com/google/fonts/main/ofl/blackhansans/BlackHanSans-Regular.ttf"),
    ],
    "sub": [
        ("GmarketSansBold.woff", "https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_2001@1.1/GmarketSansBold.woff"),
        ("BlackHanSans-Regular.ttf", "https://raw.githubusercontent.com/google/fonts/main/ofl/blackhansans/BlackHanSans-Regular.ttf"),
    ],
}
SYSTEM_FALLBACK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"


def log(*a):
    print("▶", *a, flush=True)


# ── 공통 ────────────────────────────────────────────────
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
        try:
            urllib.request.urlretrieve(url, p)
            ImageFont.truetype(p, 40)
            log(f"폰트 받음: {name}")
            return p
        except Exception:
            if os.path.exists(p):
                os.remove(p)
    log(f"⚠ {kind} 폰트를 못 받아 기본 폰트 사용")
    return SYSTEM_FALLBACK


# ── 나레이션 (일레븐랩스, 글자 단위 타이밍) ──────────────────
def tts_elevenlabs(text, cfg, out_mp3):
    if not cfg.get("voice_id"):
        raise RuntimeError("fantube/config.json 에 voice_id(일레븐랩스 목소리 ID)를 넣어주세요")
    headers = {}
    if os.environ.get("ELEVENLABS_API_KEY"):
        headers["xi-api-key"] = os.environ["ELEVENLABS_API_KEY"]
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['voice_id']}/with-timestamps"
           f"?output_format=mp3_44100_128")
    res = http_json(url, {"text": text, "model_id": cfg["tts_model"],
                          "voice_settings": cfg["voice_settings"]}, headers)
    with open(out_mp3, "wb") as f:
        f.write(base64.b64decode(res["audio_base64"]))
    al = res.get("alignment") or res.get("normalized_alignment")
    return al["character_start_times_seconds"], al["character_end_times_seconds"]


def mp3_to_array(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def shorten_pauses(voice, starts, ends, max_pause, pause_to):
    """긴 쉼을 줄여 레퍼런스처럼 쉬지 않고 이어 말하게 한다. 글자 타이밍도 같이 옮긴다."""
    hop = int(SR * 0.01)
    n = len(voice) // hop
    rms = np.sqrt((voice[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
    silent = 20 * np.log10(rms / (rms.max() + 1e-9)) < -38
    cuts = []                                   # (시작초, 끝초) 잘라낼 구간
    i = 0
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            a, b = i * hop / SR, j * hop / SR
            if i == 0:
                keep = 0.05                     # 맨 앞 침묵
            elif j == n:
                keep = 0.3                      # 맨 끝 침묵
            else:
                keep = pause_to if b - a > max_pause else b - a
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


# ── 이미지 (OpenAI, 세로) ───────────────────────────────
def gen_image(prompt, cfg, out_png):
    headers = {}
    if os.environ.get("OPENAI_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["OPENAI_API_KEY"]
    res = http_json("https://api.openai.com/v1/images/generations",
                    {"model": cfg["image_model"], "prompt": f"{prompt}\n\nStyle: {cfg['image_style']}",
                     "size": "1024x1536", "quality": cfg["image_quality"], "n": 1}, headers)
    with open(out_png, "wb") as f:
        f.write(base64.b64decode(res["data"][0]["b64_json"]))


def placeholder_image(i, label, out_png):
    rng = np.random.default_rng(i + 7)
    c1, c2 = rng.integers(40, 200, 3), rng.integers(40, 200, 3)
    t = np.linspace(0, 1, 1536)[:, None, None]
    arr = (c1 * (1 - t) + c2 * t).astype(np.uint8).repeat(1024, axis=1)
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(font_path("sub"), 60)
    d.text((512, 500), f"그림{i + 1}", font=f, fill="white", anchor="mm", align="center")
    im.save(out_png)


def cover(img, w, h):
    """비율을 지키며 w x h 를 꽉 채우도록 잘라 맞춘다."""
    s = max(w / img.width, h / img.height)
    im = img.resize((math.ceil(img.width * s), math.ceil(img.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


# ── 소리 (직접 합성) ─────────────────────────────────────
def ding(vol=0.16):
    """장면 전환용 짧고 맑은 '띵' 소리"""
    dur = 0.45
    t = np.arange(int(SR * dur)) / SR
    tone = (np.sin(2 * np.pi * 1568 * t) + 0.5 * np.sin(2 * np.pi * 2352 * t)
            + 0.25 * np.sin(2 * np.pi * 3136 * t)) * np.exp(-t * 9)
    attack = np.minimum(1, t / 0.004)
    out = tone * attack
    return (out / np.abs(out).max() * vol).astype(np.float32)


def make_pad(total, rms_target):
    """저작권 걱정 없는 잔잔한 배경음악(부드러운 화음)을 직접 만든다."""
    n = int(SR * total)
    t = np.arange(n) / SR
    chords = [(261.63, 329.63, 392.00), (220.00, 261.63, 329.63),
              (174.61, 220.00, 261.63), (196.00, 246.94, 293.66)]  # C Am F G
    bar = 4.0
    out = np.zeros(n, dtype=np.float64)
    for k in range(int(total // bar) + 2):
        a = int(k * bar * SR)
        if a >= n:
            break
        seg_n = min(n - a, int((bar + 1.0) * SR))
        tt = np.arange(seg_n) / SR
        env = np.minimum(1, tt / 0.8) * np.clip((bar + 1.0 - tt) / 1.2, 0, 1)
        sig = np.zeros(seg_n)
        for f in chords[k % 4]:
            for mult, amp in ((0.5, 0.6), (1, 1.0), (2, 0.18)):
                sig += amp * np.sin(2 * np.pi * f * mult * tt + k)
        out[a:a + seg_n] += sig * env
    out *= 1 + 0.08 * np.sin(2 * np.pi * 0.25 * t)
    out = out / (np.sqrt((out ** 2).mean()) + 1e-9) * rms_target
    return out.astype(np.float32)


def load_bgm(path, total):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", path, "-t", f"{total:.2f}",
                          "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


# ── 텍스트 그리기 ────────────────────────────────────────
def _runs(parts, font, d):
    """띄어쓰기는 그리지 않고 간격만 둔다 (G마켓 산스 woff 는 공백 글자가 네모로 나옴)."""
    sp = font.size * 0.28
    runs, x = [], 0.0
    for t, col in parts:
        for k, w in enumerate(t.split(" ")):
            if k:
                x += sp
            if w:
                runs.append((x, w, col))
                x += d.textlength(w, font=font)
    return runs, x


def text_width(text, font):
    return _runs([(text, None)], font, ImageDraw.Draw(Image.new("RGB", (10, 10))))[1]


def text_layer(parts, font, cx, cy, stroke, size, shadow=(3, 5), blur=4):
    """parts: [(글자, 색)] 을 (cx, cy) 가운데 정렬로 그린 투명 레이어. 테두리 + 그림자."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    runs, total = _runs(parts, font, d)
    asc, desc = font.getmetrics()
    y = cy - (asc + desc) / 2
    x0 = cx - total / 2
    sh = Image.new("RGBA", size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    for x, w, _ in runs:
        ds.text((x0 + x + shadow[0], y + shadow[1]), w, font=font, fill=(0, 0, 0, 170),
                stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    for x, w, col in runs:
        d.text((x0 + x, y), w, font=font, fill=col, stroke_width=stroke, stroke_fill=(0, 0, 0))
    return Image.alpha_composite(sh, layer)


def fit_font(path, lines, max_w, start, min_size=40):
    size = start
    while size > min_size:
        f = ImageFont.truetype(path, size)
        if all(text_width(l, f) <= max_w for l in lines):
            return f
        size -= 2
    return ImageFont.truetype(path, min_size)


def make_top(title_lines, title_font_path):
    """상단 제목 판 (아래 모서리 둥근 짙은 판 + 흰/노란 2줄 제목)"""
    top = Image.new("RGBA", (W, PANEL_H + 20), (0, 0, 0, 0))
    ImageDraw.Draw(top).rounded_rectangle((0, -PANEL_R, W, PANEL_H), PANEL_R, fill=BG + (255,))
    lines = [l for l in title_lines if l][:2]
    f = fit_font(title_font_path, lines, TITLE_MAX_W, 78, 52)
    colors = [WHITE, YELLOW]
    centers = TITLE_CENTERS if len(lines) == 2 else ((TITLE_CENTERS[0] + TITLE_CENTERS[1]) // 2,)
    for i, l in enumerate(lines):
        top = Image.alpha_composite(top, text_layer([(l, colors[i % 2])], f, W / 2, centers[i], 3,
                                                    top.size, shadow=(2, 4), blur=3))
    return top


# ── 하단 좋아요·구독 버튼 애니메이션 ──────────────────────
def _thumb(d, cx, cy, s, col):
    d.rounded_rectangle((cx - s * 0.55, cy - s * 0.05, cx - s * 0.25, cy + s * 0.6), s * 0.06, fill=col)
    d.rounded_rectangle((cx - s * 0.18, cy - s * 0.1, cx + s * 0.6, cy + s * 0.6), s * 0.14, fill=col)
    d.polygon([(cx - s * 0.18, cy), (cx + s * 0.02, cy - s * 0.62), (cx + s * 0.22, cy - s * 0.55),
               (cx + s * 0.16, cy - s * 0.05)], fill=col)


def _bell(d, cx, cy, s, col):
    d.pieslice((cx - s * 0.42, cy - s * 0.5, cx + s * 0.42, cy + s * 0.4), 180, 360, fill=col)
    d.rectangle((cx - s * 0.42, cy - s * 0.06, cx + s * 0.42, cy + s * 0.3), fill=col)
    d.rounded_rectangle((cx - s * 0.55, cy + s * 0.24, cx + s * 0.55, cy + s * 0.38), s * 0.06, fill=col)
    d.ellipse((cx - s * 0.13, cy + s * 0.38, cx + s * 0.13, cy + s * 0.6), fill=col)


def make_band(font, subscribed):
    band = Image.new("RGBA", (W, H - BAND_TOP), (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    d.rounded_rectangle((0, 0, W, H - BAND_TOP + PANEL_R), PANEL_R, fill=BG + (255,))
    cy = 62
    red, grey, white = (230, 33, 23), (90, 90, 90), (255, 255, 255)
    # 좋아요
    d.ellipse((330 - 34, cy - 34, 330 + 34, cy + 34), fill=red if subscribed else grey)
    _thumb(d, 330, cy + 2, 34, white)
    # 구독 버튼
    label = "SUBSCRIBED" if subscribed else "SUBSCRIBE"
    bw = 250
    d.rounded_rectangle((540 - bw / 2, cy - 30, 540 + bw / 2, cy + 30), 10,
                        fill=(225, 225, 225) if subscribed else red)
    d.text((540, cy), label, font=font, fill=(30, 30, 30) if subscribed else white, anchor="mm")
    # 알림 종
    d.ellipse((750 - 34, cy - 34, 750 + 34, cy + 34), fill=red if subscribed else grey)
    _bell(d, 750, cy - 2, 40, white)
    return band


def make_cursor(scale=1.0):
    s = int(90 * scale)
    cur = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(cur)
    pts = [(0.05, 0.02), (0.05, 0.78), (0.24, 0.6), (0.38, 0.92), (0.5, 0.86), (0.36, 0.55), (0.62, 0.55)]
    d.polygon([(x * s, y * s) for x, y in pts], fill=(255, 255, 255), outline=(0, 0, 0), width=max(2, s // 22))
    return cur


def band_frame(t, bands, cursors, period=4.0):
    """4초마다: 커서가 구독 버튼으로 다가가 누르고 → 구독됨으로 바뀜"""
    p = t % period
    clicked = p >= 1.3
    band = bands[1 if clicked else 0].copy()
    if p < 3.4:
        k = min(1.0, p / 1.1)
        k = 1 - (1 - k) ** 3
        x = int(700 + (560 - 700) * k)
        y = int(140 + (70 - 140) * k)
        cur = cursors[1] if 1.15 <= p < 1.35 else cursors[0]
        band.alpha_composite(cur, (x, min(y, band.height - 10)))
    return band


# ── 자막 ────────────────────────────────────────────────
def split_highlight(text, highlights):
    """강조 단어는 노란색, 나머지는 흰색으로 쪼갠다."""
    hw = {w for h in (highlights or []) for w in h.split()}
    words = text.split(" ")
    return [((" " if i else "") + w, YELLOW if w in hw else WHITE) for i, w in enumerate(words)]


def chunk_text(text, max_chars=SUB_MAX_CHARS):
    """자막 덩어리: 띄어쓰기 기준 한 줄 (공백 제외 max_chars 이하)"""
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
        chunks.append(cur)
    return chunks


SUB_BOX = 220


def make_sub_layer(line, highlights, font_path_):
    f = fit_font(font_path_, [line], W - 80, 66, 48)
    return text_layer(split_highlight(line, highlights), f, W / 2, SUB_BOX / 2, 5, (W, SUB_BOX))


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

    # 1) 나레이션 원고 조립 + 장면별 글자 위치 기록
    full, spans = "", []
    for s in scenes:
        t = re.sub(r"\s+", " ", s["text"]).strip()
        if full:
            full += " "
        spans.append((len(full), len(full) + len(t)))
        full += t
    log(f"나레이션 {len(full)}자, 장면 {len(scenes)}개")

    # 2) 나레이션 생성
    mp3 = os.path.join(work, "voice.mp3")
    if test_mode:
        per = 0.105
        starts = [i * per for i in range(len(full))]
        ends = [(i + 1) * per for i in range(len(full))]
        voice = np.zeros(int(SR * (len(full) * per)), dtype=np.float32)
        log("시험 모드: 무음 나레이션")
    else:
        meta = json.dumps([full, cfg["voice_id"], cfg["voice_settings"]], ensure_ascii=False)
        cached = False
        if os.path.exists(mp3) and os.path.exists(mp3 + ".json"):
            with open(mp3 + ".json") as f:
                saved = json.load(f)
            if isinstance(saved, dict) and saved.get("meta") == meta:
                starts, ends = saved["starts"], saved["ends"]
                cached = True
                log("이전에 만든 나레이션 재사용")
        if not cached:
            log("일레븐랩스 나레이션 만드는 중…")
            starts, ends = tts_elevenlabs(full, cfg, mp3)
            with open(mp3 + ".json", "w") as f:
                json.dump({"meta": meta, "starts": starts, "ends": ends}, f)
        voice = mp3_to_array(mp3)
        voice, starts, ends = shorten_pauses(voice, starts, ends, cfg["max_pause"], cfg["pause_to"])
        log(f"나레이션 {len(voice) / SR:.1f}초 (초당 {len(full.replace(' ', '')) / (len(voice) / SR):.1f}글자)")

    voice_len = len(voice) / SR
    total = voice_len + 0.5

    # 3) 장면·자막 타이밍
    def t_at(ci, use_end=False):
        ci = max(0, min(ci, len(starts) - 1))
        return ends[ci] if use_end else starts[ci]

    scene_times = []
    for i, (a, b) in enumerate(spans):
        st = 0.0 if i == 0 else t_at(a)
        en = total if i == len(spans) - 1 else t_at(spans[i + 1][0])
        scene_times.append((st, en))

    sub_fp = font_path("sub")
    subs = []  # [시작, 끝, 레이어]
    for i, s in enumerate(scenes):
        a, b = spans[i]
        seg = full[a:b]
        hl = s.get("highlight", []) if cfg.get("sub_highlight") else []
        pos = 0
        for ch in chunk_text(seg):
            k = seg.find(ch, pos)
            if k < 0:
                k = pos
            pos = k + len(ch)
            subs.append([t_at(a + k), t_at(a + pos - 1, use_end=True), make_sub_layer(ch, hl, sub_fp)])
    for j in range(len(subs) - 1):          # 자막 사이 빈틈 없애기
        subs[j][1] = subs[j + 1][0]
    if subs:
        subs[-1][1] = total

    # 4) 사진 (장면마다 1~3장, 장면 시간을 나눠 차례로)
    IMG_W, IMG_H = W, IMG_BOTTOM - IMG_TOP
    slots = []  # (시작, 끝, 그림)
    n_img = 0
    for i, s in enumerate(scenes):
        prompts = s.get("images") or [s.get("image", "")]
        st, en = scene_times[i]
        for j, pr in enumerate(prompts):
            n_img += 1
            p = os.path.join(work, f"scene_{i + 1:02d}" + (f"_{j + 1}" if len(prompts) > 1 else "") + ".png")
            if not os.path.exists(p):
                if test_mode:
                    placeholder_image(n_img, s["text"], p)
                else:
                    log(f"사진 {os.path.basename(p)} 만드는 중…")
                    gen_image(pr, cfg, p)
            a = st + (en - st) * j / len(prompts)
            b = st + (en - st) * (j + 1) / len(prompts)
            slots.append((a, b, cover(Image.open(p).convert("RGB"), IMG_W, IMG_H)))

    # 5) 오디오 믹스 (나레이션 + 띵 + 배경음악) → 유튜브 음량으로 맞춤
    mix = np.zeros(int(SR * total), dtype=np.float32)
    mix[:len(voice)] += voice[:len(mix)]
    dg = ding()
    for st, _ in scene_times[1:]:
        k = max(0, int((st - 0.05) * SR))
        mix[k:k + len(dg)] += dg[:len(mix) - k]
    voiced = voice[np.abs(voice) > 0.02]
    vrms = float(np.sqrt((voiced ** 2).mean())) if len(voiced) else 0.1
    bdir = os.path.join(ROOT, "bgm")
    cands = sorted(f for f in os.listdir(bdir) if f.lower().endswith((".mp3", ".wav", ".m4a"))) \
        if os.path.isdir(bdir) else []
    if cands:
        name = job.get("bgm") if job.get("bgm") in cands else cands[0]
        log(f"배경음악: {name}")
        mix += load_bgm(os.path.join(bdir, name), total)[:len(mix)] * cfg["bgm_volume"]
    else:
        log("배경음악: 직접 만든 잔잔한 화음")
        mix += make_pad(total, vrms * 10 ** (-cfg["bgm_gap_db"] / 20))[:len(mix)]
    fade = int(SR * 0.4)
    mix[-fade:] *= np.linspace(1, 0, fade)
    wav_path = os.path.join(work, "mix.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())

    # 6) 프레임 렌더 → ffmpeg
    top = make_top(job["title"], font_path("title"))
    btn_font = ImageFont.truetype(font_path("sub"), 30)
    bands = [make_band(btn_font, False), make_band(btn_font, True)]
    cursors = [make_cursor(1.0), make_cursor(0.85)]
    out_mp4 = os.path.join(out_dir, f"{job_id}.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", wav_path, "-map", "0:v", "-map", "1:a",
           "-af", f"loudnorm=I={cfg['loudness']}:TP=-1.5:LRA=11",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-shortest", "-movflags", "+faststart", out_mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    n_frames = int(total * FPS)
    si, sub_i = 0, 0
    log(f"영상 합성 중… ({total:.1f}초, {n_frames}프레임, 사진 {len(slots)}장)")
    for fi in range(n_frames):
        t = fi / FPS
        while si < len(slots) - 1 and t >= slots[si][1]:
            si += 1
        st, en, src = slots[si]
        prog = min(1.0, max(0.0, (t - st) / max(0.1, en - st)))
        z = 1.0 + (ZOOM_END - 1.0) * prog
        cw, chh = IMG_W / z, IMG_H / z
        x0, y0 = (IMG_W - cw) / 2, (IMG_H - chh) / 2
        img = src.resize((IMG_W, IMG_H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + chh))
        frame = Image.new("RGBA", (W, H), BG + (255,))
        frame.paste(img, (0, IMG_TOP))
        frame.alpha_composite(top, (0, 0))
        frame.alpha_composite(band_frame(t, bands, cursors), (0, BAND_TOP))
        while sub_i < len(subs) - 1 and t >= subs[sub_i][1]:
            sub_i += 1
        if subs and subs[sub_i][0] - 0.05 <= t < subs[sub_i][1]:
            frame.alpha_composite(subs[sub_i][2], (0, SUB_CENTER_Y - SUB_BOX // 2))
        proc.stdin.write(frame.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 실패")
    log(f"완성: {out_mp4}")
    return out_mp4


if __name__ == "__main__":
    main()
