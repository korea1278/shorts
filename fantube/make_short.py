#!/usr/bin/env python3
"""팬튜브 쇼츠 자동 제작 엔진

사용법:
    python3 fantube/make_short.py fantube/jobs/<작업이름>.json
    python3 fantube/make_short.py fantube/jobs/<작업이름>.json --test   # API 없이 시험 렌더

작업 파일(JSON) 하나로 9:16 쇼츠를 만든다.
  상단 2줄 제목(오스퀘어) · 가운데 정사각형 이미지(천천히 확대) · 하단 색 강조 자막(G마켓 산스)
  · 장면 전환 효과음 · 일레븐랩스 나레이션(글자 단위 싱크)

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
import tempfile
import urllib.request
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
SR = 44100

# ── 레이아웃 ─────────────────────────────────────────────
BG = (12, 12, 14)
TITLE_TOP, TITLE_BOTTOM = 150, 470          # 제목 영역
IMG_Y, IMG_SIZE = 500, 1080                 # 이미지 영역 (정사각형)
SUB_CENTER_Y = 1735                         # 자막 중심
WHITE, YELLOW = (255, 255, 255), (255, 222, 60)
ZOOM_END = 1.07                             # 장면마다 천천히 확대 (축소 없음)

DEFAULT_CONFIG = {
    "voice_id": "",                     # 일레븐랩스 목소리 ID (config.json에서 지정)
    "tts_model": "eleven_multilingual_v2",
    "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True},
    "image_model": "gpt-image-1",
    "image_quality": "medium",
    "image_style": (
        "Warm, cinematic Korean webtoon-style digital illustration, soft lighting, rich colors, "
        "square composition, no text, no letters, no logos, no watermark. "
        "Never depict a real, identifiable person or celebrity likeness: show people only from behind, "
        "in silhouette, at a distance, or as generic unnamed characters; prefer objects, places and atmosphere."
    ),
    "bgm_volume": 0.12,
}

FONT_SOURCES = {
    "title": [
        ("Cafe24Ohsquare.woff", "https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_2001@1.1/Cafe24Ohsquare.woff"),
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


# ── 이미지 (OpenAI) ─────────────────────────────────────
def gen_image(prompt, cfg, out_png):
    headers = {}
    if os.environ.get("OPENAI_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["OPENAI_API_KEY"]
    res = http_json("https://api.openai.com/v1/images/generations",
                    {"model": cfg["image_model"], "prompt": f"{prompt}\n\nStyle: {cfg['image_style']}",
                     "size": "1024x1024", "quality": cfg["image_quality"], "n": 1}, headers)
    with open(out_png, "wb") as f:
        f.write(base64.b64decode(res["data"][0]["b64_json"]))


def placeholder_image(i, label, out_png):
    rng = np.random.default_rng(i + 7)
    c1, c2 = rng.integers(40, 200, 3), rng.integers(40, 200, 3)
    t = np.linspace(0, 1, 1024)[:, None, None]
    arr = (c1 * (1 - t) + c2 * t).astype(np.uint8).repeat(1024, axis=1)
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(SYSTEM_FALLBACK, 60)
    d.text((512, 512), f"장면 {i + 1}\n{label[:14]}", font=f, fill="white", anchor="mm", align="center")
    im.save(out_png)


# ── 효과음 (직접 합성: 휙 소리) ─────────────────────────────
def whoosh(dur=0.38, vol=0.22):
    n = int(SR * dur)
    rng = np.random.default_rng(1)
    noise = rng.standard_normal(n)
    # 점점 높아지는 대역 통과 느낌: 이동 평균 길이를 줄여가며 필터
    out = np.zeros(n)
    k_start, k_end = 40, 4
    acc = np.cumsum(np.insert(noise, 0, 0))
    for i in range(n):
        k = int(k_start + (k_end - k_start) * i / n)
        j0 = max(0, i - k)
        out[i] = (acc[i + 1] - acc[j0]) / (i + 1 - j0)
    env = np.sin(np.linspace(0, math.pi, n)) ** 2
    out = out * env
    return (out / (np.abs(out).max() + 1e-9) * vol).astype(np.float32)


# ── 텍스트 그리기 ────────────────────────────────────────
def draw_text_line(draw, parts, font, cx, y, stroke):
    """parts: [(글자, 색)] 을 가운데 정렬로 한 줄에 그린다."""
    total = sum(draw.textlength(t, font=font) for t, _ in parts)
    x = cx - total / 2
    for t, col in parts:
        draw.text((x, y), t, font=font, fill=col, stroke_width=stroke, stroke_fill=(0, 0, 0))
        x += draw.textlength(t, font=font)


def fit_font(path, lines, max_w, start, min_size=40):
    size = start
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    while size > min_size:
        f = ImageFont.truetype(path, size)
        if all(tmp.textlength(l, font=f) <= max_w for l in lines):
            return f
        size -= 4
    return ImageFont.truetype(path, min_size)


def make_base(title_lines, title_font_path):
    base = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(base)
    lines = [l for l in title_lines if l][:2]
    f = fit_font(title_font_path, lines, W - 90, 104)
    asc, desc = f.getmetrics()
    lh = asc + desc + 18
    y0 = (TITLE_TOP + TITLE_BOTTOM) / 2 - lh * len(lines) / 2
    colors = [WHITE, YELLOW]
    for i, l in enumerate(lines):
        draw_text_line(d, [(l, colors[i % 2])], f, W / 2, y0 + i * lh, 7)
    return base


def split_highlight(text, highlights):
    """강조 단어는 노란색, 나머지는 흰색으로 쪼갠다."""
    # 강조 문구를 단어 단위로 풀어서, 줄이 바뀌어도 색이 유지되게 한다
    hw = {w for h in (highlights or []) for w in h.split()}
    words = text.split(" ")
    return [((" " if i else "") + w, YELLOW if w in hw else WHITE) for i, w in enumerate(words)]


def make_sub_layer(lines, highlights, font):
    layer = Image.new("RGBA", (W, 330), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    asc, desc = font.getmetrics()
    lh = asc + desc + 12
    y0 = 165 - lh * len(lines) / 2
    for i, l in enumerate(lines):
        draw_text_line(d, split_highlight(l, highlights), font, W / 2, y0 + i * lh, 9)
    return layer


def chunk_text(text, max_chars=13):
    """자막 덩어리: 띄어쓰기 기준으로 한 덩어리 최대 2줄(줄당 max_chars)"""
    words = text.split()
    chunks, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand.replace(" ", "")) > max_chars * 2 - 4 and cur:
            chunks.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks


def wrap_two(chunk, max_chars=13):
    words = chunk.split()
    if len(chunk.replace(" ", "")) <= max_chars or len(words) == 1:
        return [chunk]
    best, best_diff = None, 1e9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        diff = abs(len(a) - len(b))
        if diff < best_diff:
            best, best_diff = [a, b], diff
    return best


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
        per = 0.14
        starts = [i * per for i in range(len(full))]
        ends = [(i + 1) * per for i in range(len(full))]
        voice = np.zeros(int(SR * (len(full) * per)), dtype=np.float32)
        log("시험 모드: 무음 나레이션")
    else:
        if not os.path.exists(mp3) or not os.path.exists(mp3 + ".json"):
            log("일레븐랩스 나레이션 만드는 중…")
            starts, ends = tts_elevenlabs(full, cfg, mp3)
            with open(mp3 + ".json", "w") as f:
                json.dump([starts, ends], f)
        else:
            with open(mp3 + ".json") as f:
                starts, ends = json.load(f)
            log("이전에 만든 나레이션 재사용")
        voice = mp3_to_array(mp3)

    voice_len = len(voice) / SR
    total = voice_len + 0.6

    # 3) 장면·자막 타이밍
    def t_at(ci, use_end=False):
        ci = max(0, min(ci, len(starts) - 1))
        return ends[ci] if use_end else starts[ci]

    scene_times = []
    for i, (a, b) in enumerate(spans):
        st = 0.0 if i == 0 else t_at(a)
        en = total if i == len(spans) - 1 else t_at(spans[i + 1][0])
        scene_times.append((st, en))

    sub_font = ImageFont.truetype(font_path("sub"), 70)
    subs = []  # (시작, 끝, 레이어)
    for i, s in enumerate(scenes):
        a, b = spans[i]
        seg = full[a:b]
        pos = 0
        for ch in chunk_text(seg):
            k = seg.find(ch, pos)
            if k < 0:
                k = pos
            pos = k + len(ch)
            cs = t_at(a + k)
            ce = t_at(a + pos - 1, use_end=True)
            subs.append([cs, ce, make_sub_layer(wrap_two(ch), s.get("highlight", []), sub_font)])
    for j in range(len(subs) - 1):          # 자막 사이 빈틈 없애기
        subs[j][1] = subs[j + 1][0]
    if subs:
        subs[-1][1] = total

    # 4) 이미지
    imgs = []
    for i, s in enumerate(scenes):
        p = os.path.join(work, f"scene_{i + 1:02d}.png")
        if not os.path.exists(p):
            if test_mode:
                placeholder_image(i, s["text"], p)
            else:
                log(f"이미지 {i + 1}/{len(scenes)} 만드는 중…")
                gen_image(s["image"], cfg, p)
        imgs.append(Image.open(p).convert("RGB"))

    # 5) 오디오 믹스 (나레이션 + 효과음 + 배경음악)
    mix = np.zeros(int(SR * total) + SR, dtype=np.float32)
    mix[:len(voice)] += voice
    wh = whoosh()
    for st, _ in scene_times[1:]:
        k = max(0, int((st - 0.12) * SR))
        mix[k:k + len(wh)] += wh[:len(mix) - k]
    mix = mix[:int(SR * total)]
    wav_path = os.path.join(work, "mix.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())

    bgm = None
    bdir = os.path.join(ROOT, "bgm")
    if os.path.isdir(bdir):
        cands = sorted(f for f in os.listdir(bdir) if f.lower().endswith((".mp3", ".wav", ".m4a")))
        if job.get("bgm") in cands:
            bgm = os.path.join(bdir, job["bgm"])
        elif cands:
            bgm = os.path.join(bdir, cands[0])

    # 6) 프레임 렌더 → ffmpeg
    base = make_base(job["title"], font_path("title"))
    out_mp4 = os.path.join(out_dir, f"{job_id}.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", wav_path]
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", bgm,
                "-filter_complex",
                f"[2:a]volume={cfg['bgm_volume']}[b];[1:a][b]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    n_frames = int(total * FPS)
    si, sub_i = 0, 0
    big_cache = {}
    log(f"영상 합성 중… ({total:.1f}초, {n_frames}프레임)")
    for fi in range(n_frames):
        t = fi / FPS
        while si < len(scene_times) - 1 and t >= scene_times[si][1]:
            si += 1
        st, en = scene_times[si]
        prog = min(1.0, max(0.0, (t - st) / max(0.1, en - st)))
        z = 1.0 + (ZOOM_END - 1.0) * (0.5 - 0.5 * math.cos(math.pi * prog))
        src = imgs[si]
        size = int(IMG_SIZE * z)
        key = (si, size)
        if key not in big_cache:
            big_cache.clear()
            big_cache[key] = src.resize((size, size), Image.BILINEAR)
        big = big_cache[key]
        off = (size - IMG_SIZE) // 2
        frame = base.copy()
        frame.paste(big.crop((off, off, off + IMG_SIZE, off + IMG_SIZE)), (0, IMG_Y))
        while sub_i < len(subs) - 1 and t >= subs[sub_i][1]:
            sub_i += 1
        if subs and subs[sub_i][0] - 0.05 <= t < subs[sub_i][1]:
            layer = subs[sub_i][2]
            frame.paste(layer, (0, SUB_CENTER_Y - 165), layer)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 실패")
    log(f"완성: {out_mp4}")
    return out_mp4


if __name__ == "__main__":
    main()
