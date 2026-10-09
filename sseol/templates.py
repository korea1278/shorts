#!/usr/bin/env python3
"""가짜 화면 템플릿 — 기사 · SNS 글 · 문자 대화 · 지도 (그림 영역 1080x960)

장면 images 항목으로 쓴다 (make_short.py 가 그린다):
  {"news": {"outlet": "썰뉴스", "headline": "제목", "lead": "본문 한두 줄", "date": "2026.10.09", "img": {"ira": ...}}}
  {"sns":  {"name": "익명의 직장인", "handle": "@anon_1234", "text": "글", "likes": 1200, "comments": 85, "time": "3시간 전"}}
  {"chat": {"title": "엄마", "msgs": [["상대", "밥은?"], ["나", "먹었어"]], "reveal": true}}
  {"map":  {"from": "우리 집", "to": "회사", "note": "40분", "seed": 3}}

지켜야 할 것
  - 실제 언론사·방송사·SNS·메신저·지도 서비스 이름과 로고는 쓰지 않는다 (check_names 가 막는다)
  - 실존 인물 이름·얼굴, 실존 인물이 한 것처럼 지어낸 말은 넣지 않는다
  - 화면 구석에 "재구성 화면" 표시가 항상 들어간다 (진짜 기사·캡처로 오해하지 않게)
"""
import random
import re

from PIL import Image, ImageDraw, ImageFont

# 실제 언론사·브랜드 이름 (템플릿 글에 들어가면 멈춘다). 소문자로 비교.
BANNED_NAMES = [
    "조선일보", "중앙일보", "동아일보", "한겨레", "경향신문", "한국일보", "국민일보", "서울신문", "세계일보",
    "문화일보", "매일경제", "매경", "한국경제", "한경", "머니투데이", "이데일리", "헤럴드", "아시아경제",
    "연합뉴스", "뉴시스", "뉴스1", "노컷뉴스", "오마이뉴스", "프레시안", "디스패치", "스포츠조선", "스포츠서울",
    "kbs", "mbc", "sbs", "jtbc", "ytn", "tvn", "mbn", "채널a", "tv조선", "ebs", "cnn", "bbc", "nhk", "fox news",
    "new york times", "뉴욕타임스", "로이터", "reuters", "ap통신", "블룸버그", "bloomberg",
    "카카오", "카톡", "kakao", "네이버", "naver", "다음뉴스", "다음카페", "daum", "구글", "google", "유튜브", "youtube",
    "트위터", "twitter", "인스타", "instagram", "페이스북", "facebook", "틱톡", "tiktok", "스레드", "threads",
    "텔레그램", "telegram", "라인메신저", "왓츠앱", "whatsapp", "디스코드", "discord", "티맵", "tmap", "애플", "apple",
    "아이폰", "iphone", "갤럭시", "galaxy", "삼성", "samsung", "디시", "dcinside", "에펨", "fmkorea", "더쿠",
    "개드립", "보배드림", "네이트", "nate",
]
SHORT_WORD_NAMES = {"한경", "매경", "애플", "디시", "에펨"}   # 흔한 낱말과 겹쳐서 낱말 단위로만 본다

BG_LIGHT = (246, 246, 248)
INK = (25, 25, 30)
GRAY = (120, 120, 130)


def _texts(spec):
    if isinstance(spec, str):
        yield spec
    elif isinstance(spec, dict):
        for k, v in spec.items():
            if k != "img":
                yield from _texts(v)
    elif isinstance(spec, (list, tuple)):
        for v in spec:
            yield from _texts(v)


def check_names(kind, spec):
    """템플릿 글에 실제 언론사·브랜드 이름이 있으면 오류"""
    for t in _texts(spec):
        low = t.lower()
        words = set(re.split(r"[\s.,?!·]+", low))
        for n in BANNED_NAMES:
            if n in SHORT_WORD_NAMES:
                hit = n in words
            elif n.isascii():                                     # 영어는 단어 경계로 (donate 의 nate 같은 오탐 방지)
                hit = re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", low) is not None
            else:
                hit = n in low
            if hit:
                raise RuntimeError(f"{kind} 화면에 실제 언론사·브랜드 이름 '{n}' 이 있습니다. 가상의 이름으로 바꿔 주세요: {t}")


def _wrap(d, text, font, max_w):
    """글자 단위 줄바꿈 (한국어는 어절이 길지 않아 어절 우선, 넘치면 글자로)"""
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for w in para.split(" "):
            cand = (cur + " " + w).strip()
            if d.textlength(cand, font=font) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            cur = ""
            for ch in w:
                if d.textlength(cur + ch, font=font) > max_w and cur:
                    lines.append(cur)
                    cur = ""
                cur += ch
        lines.append(cur)
    return lines


def _badge(im, fonts):
    """'재구성 화면' 표시 (오른쪽 아래)"""
    d = ImageDraw.Draw(im)
    f = fonts(26, "regular")
    t = "재구성 화면"
    tw = d.textlength(t, font=f)
    x1, y1 = im.width - 18, im.height - 16
    d.rounded_rectangle((x1 - tw - 24, y1 - 40, x1, y1), 8, fill=(0, 0, 0, 150) if im.mode == "RGBA" else (60, 60, 66))
    d.text((x1 - 12, y1 - 20), t, font=f, fill=(235, 235, 235), anchor="rm")


def _avatar(size, color, letter, fonts):
    av = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(av)
    d.ellipse((0, 0, size - 1, size - 1), fill=color)
    d.text((size / 2, size / 2), letter[:1], font=fonts(int(size * 0.48), "bold"), fill=(255, 255, 255), anchor="mm")
    return av


def _num(n):
    if isinstance(n, str):
        return n
    return f"{n / 10000:.1f}만".replace(".0만", "만") if n >= 10000 else f"{n:,}"


def render_news(spec, w, h, fonts, pic=None):
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    outlet = spec.get("outlet", "썰뉴스")
    d.rectangle((0, 0, w, 96), fill=(28, 52, 110))
    d.text((40, 48), outlet, font=fonts(46, "black"), fill=(255, 255, 255), anchor="lm")
    d.text((w - 40, 48), spec.get("section", "사회"), font=fonts(32, "regular"), fill=(200, 210, 235), anchor="rm")
    y = 130
    fh = fonts(66, "black")
    for ln in _wrap(d, spec.get("headline", ""), fh, w - 80)[:3]:
        d.text((40, y), ln, font=fh, fill=INK)
        y += 84
    y += 6
    d.text((40, y), f"{spec.get('reporter', '김썰 기자')}  ·  {spec.get('date', '')}".strip(" ·"),
           font=fonts(30, "regular"), fill=GRAY)
    y += 56
    d.line((40, y, w - 40, y), fill=(220, 220, 225), width=2)
    y += 24
    if pic is not None:
        ph = min(440, h - y - 170)
        box = pic.convert("RGB")
        s = min((w - 80) / box.width, ph / box.height)
        box = box.resize((max(1, int(box.width * s)), max(1, int(box.height * s))), Image.LANCZOS)
        d.rectangle((40, y, w - 40, y + ph), fill=(240, 240, 242))
        im.paste(box, ((w - box.width) // 2, y + (ph - box.height) // 2))
        y += ph + 24
    fb = fonts(44, "regular")
    for ln in _wrap(d, spec.get("lead", ""), fb, w - 80):
        if y > h - 100:
            break
        d.text((40, y), ln, font=fb, fill=(55, 55, 60))
        y += 62
    _badge(im, fonts)
    return im


def render_sns(spec, w, h, fonts, pic=None):
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    name = spec.get("name", "익명")
    ft = fonts(60, "bold")
    lines = _wrap(d, spec.get("text", ""), ft, w - 100)[:7]
    ph = 0
    if pic is not None:
        box = pic.convert("RGB")
        s = min((w - 100) / box.width, 340 / box.height)
        box = box.resize((max(1, int(box.width * s)), max(1, int(box.height * s))), Image.LANCZOS)
        ph = box.height + 30
    x0 = 50
    y = max(40, (h - (160 + len(lines) * 82 + ph + 130)) // 2)        # 글 덩어리를 세로 가운데로
    im.paste(av := _avatar(110, tuple(spec.get("avatar_color", (110, 140, 220))), name, fonts), (x0, y), av)
    d.text((x0 + 135, y + 30), name, font=fonts(44, "bold"), fill=INK, anchor="lm")
    d.text((x0 + 135, y + 82), f"{spec.get('handle', '@anonymous')} · {spec.get('time', '방금 전')}",
           font=fonts(32, "regular"), fill=GRAY, anchor="lm")
    y += 160
    for ln in lines:
        d.text((x0, y), ln, font=ft, fill=INK)
        y += 82
    if pic is not None:
        im.paste(box, ((w - box.width) // 2, y + 10))
        y += ph
    yb = y + 70
    d.line((x0, yb - 30, w - x0, yb - 30), fill=(230, 230, 235), width=2)
    f = fonts(36, "regular")
    # 아이콘은 단순 도형 (어느 서비스의 아이콘도 아니게)
    d.ellipse((x0, yb, x0 + 40, yb + 40), outline=(240, 70, 90), width=5)
    d.text((x0 + 60, yb + 20), _num(spec.get("likes", 0)), font=f, fill=GRAY, anchor="lm")
    d.rounded_rectangle((x0 + 300, yb + 2, x0 + 342, yb + 36), 8, outline=GRAY, width=4)
    d.text((x0 + 362, yb + 20), _num(spec.get("comments", 0)), font=f, fill=GRAY, anchor="lm")
    _badge(im, fonts)
    return im


def render_chat(spec, w, h, fonts, visible=None):
    """문자 대화 화면. msgs = [[보낸이, 글], ...] — 보낸이가 '나' 이면 오른쪽 파란 말풍선"""
    im = Image.new("RGB", (w, h), BG_LIGHT)
    d = ImageDraw.Draw(im)
    msgs = spec.get("msgs", [])
    if visible is not None:
        msgs = msgs[:visible]
    me = spec.get("me", "나")
    f = fonts(50, "regular")
    pad, maxw, gap = 30, int(w * 0.7), 26
    blocks = []
    for who, text in msgs:
        lines = _wrap(d, text, f, maxw - 2 * pad)
        bw = max(d.textlength(l, font=f) for l in lines) + 2 * pad
        bh = len(lines) * 64 + 2 * pad - 14
        blocks.append((who == me, lines, int(bw), int(bh)))
    total = sum(b[3] + gap for b in blocks)
    y = min(170, h - 60 - total)                   # 위부터 쌓고, 넘치면 위가 잘린다 (최근 글이 보이게)
    for mine, lines, bw, bh in blocks:
        x = w - 40 - bw if mine else 40
        if y + bh > 120:
            d.rounded_rectangle((x, y, x + bw, y + bh), 30, fill=(60, 130, 245) if mine else (229, 229, 234))
            for k, l in enumerate(lines):
                d.text((x + pad, y + pad - 4 + k * 64), l, font=f, fill=(255, 255, 255) if mine else INK)
        y += bh + gap
    d.rectangle((0, 0, w, 110), fill=(255, 255, 255))      # 머리줄은 말풍선 위에 덮어 그린다
    d.line((0, 110, w, 110), fill=(225, 225, 230), width=2)
    d.text((48, 55), "‹", font=fonts(64, "regular"), fill=(60, 120, 230), anchor="lm")
    d.text((w / 2, 55), spec.get("title", "상대"), font=fonts(42, "bold"), fill=INK, anchor="mm")
    _badge(im, fonts)
    return im


def render_map(spec, w, h, fonts):
    """지어낸 동네 지도 (실제 지도 아님) + 출발·도착 핀과 길"""
    rng = random.Random(spec.get("seed", 1))
    im = Image.new("RGB", (w, h), (236, 234, 226))
    d = ImageDraw.Draw(im)
    # 공원·물
    for _ in range(3):
        x, y = rng.randint(0, w - 200), rng.randint(0, h - 200)
        d.rounded_rectangle((x, y, x + rng.randint(140, 260), y + rng.randint(100, 220)), 30, fill=(200, 228, 190))
    ry = rng.randint(int(h * 0.25), int(h * 0.7))
    d.polygon([(0, ry), (w, ry - 120), (w, ry - 40), (0, ry + 80)], fill=(170, 205, 240))
    # 길
    xs = sorted(rng.sample(range(80, w - 80, 20), 5))
    ys = sorted(rng.sample(range(80, h - 80, 20), 6))
    for x in xs:
        d.line((x, 0, x + rng.randint(-60, 60), h), fill=(255, 255, 255), width=rng.choice((14, 22)))
    for y in ys:
        d.line((0, y, w, y + rng.randint(-50, 50)), fill=(255, 255, 255), width=rng.choice((14, 22)))
    a = (xs[0] + 20, ys[-1] + 10)
    b = (xs[-1] - 10, ys[0] + 20)
    route = [a, (a[0], (a[1] + b[1]) // 2), (b[0], (a[1] + b[1]) // 2), b]
    d.line(route, fill=(255, 255, 255), width=26, joint="curve")
    d.line(route, fill=(50, 120, 240), width=16, joint="curve")

    def pin(p, color, label):
        x, y = p
        d.ellipse((x - 30, y - 90, x + 30, y - 30), fill=color, outline=(255, 255, 255), width=5)
        d.polygon([(x - 22, y - 48), (x + 22, y - 48), (x, y)], fill=color)
        d.ellipse((x - 11, y - 71, x + 11, y - 49), fill=(255, 255, 255))
        f = fonts(40, "bold")
        tw = d.textlength(label, font=f)
        lx = min(max(x - tw / 2 - 18, 10), w - tw - 46)
        d.rounded_rectangle((lx, y + 12, lx + tw + 36, y + 76), 14, fill=(255, 255, 255), outline=color, width=4)
        d.text((lx + 18, y + 44), label, font=f, fill=INK, anchor="lm")

    pin(a, (40, 170, 90), spec.get("from", "출발"))
    pin(b, (235, 60, 60), spec.get("to", "도착"))
    if spec.get("note"):
        f = fonts(44, "black")
        t = spec["note"]
        tw = d.textlength(t, font=f)
        d.rounded_rectangle((w / 2 - tw / 2 - 24, 30, w / 2 + tw / 2 + 24, 110), 20, fill=(30, 30, 36))
        d.text((w / 2, 70), t, font=f, fill=(255, 236, 0), anchor="mm")
    _badge(im, fonts)
    return im


TEMPLATES = ("news", "sns", "chat", "map")
