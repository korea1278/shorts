#!/usr/bin/env python3
"""등장인물 표정 라이브러리 (sseol/assets/characters/)

사용법:
    python3 sseol/characters.py list                          # 인물과 표정 목록
    python3 sseol/characters.py make <이름> "<English 인물 설명>"   # AI 가상 인물 만들기 (표정 9개)
    python3 sseol/characters.py make <이름> "<설명>" 화남 놀람        # 일부 표정만 (다시) 만들기

AI 인물은 처음에 '기본' 얼굴을 만들고, 그 그림을 바탕으로 표정만 바꿔 같은 사람처럼 보이게 한다.
실존 인물·연예인을 닮게 만들지 않는다 (설명에 실존 인물 이름을 쓰지 않는다).
장면에서 쓰기: {"char": "이름", "face": "화남"}  또는 cast 에 "char" 를 정해 두면 표정(mood)에 맞춰 자동.
"""
import base64
import json
import os
import sys
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
CHAR_DIR = os.path.join(ROOT, "assets", "characters")
INDEX = os.path.join(CHAR_DIR, "index.json")

FACE_PROMPTS = {
    "기본": "a calm, friendly neutral expression with a slight smile",
    "웃음": "laughing happily with mouth open and eyes squeezed",
    "화남": "very angry, frowning eyebrows, red cheeks, shouting",
    "억울": "feeling wronged and teary-eyed, pouting, about to cry",
    "놀람": "shocked and surprised, wide eyes, mouth open",
    "당황": "flustered and panicking, sweat drops, awkward smile",
    "고민": "thinking hard, hand on chin, looking up",
    "깨달음": "eureka moment, eyes bright, one finger raised",
    "의문": "confused, tilting head, one eyebrow raised",
}
STYLE = ("Simple, cute Japanese-style flat clip-art illustration with soft colors and thin outlines, "
         "upper body, facing the viewer, transparent background, no text, no logos. "
         "A fictional person who does not resemble any real person or celebrity; not an existing cartoon character.")


def load_index():
    with open(INDEX, encoding="utf-8") as f:
        return json.load(f)


def save_index(idx):
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _auth(req):
    if os.environ.get("OPENAI_API_KEY"):
        req.add_header("Authorization", "Bearer " + os.environ["OPENAI_API_KEY"])


def generate(prompt, out_png, quality="medium"):
    req = urllib.request.Request("https://api.openai.com/v1/images/generations", method="POST", data=json.dumps(
        {"model": "gpt-image-1", "prompt": prompt, "size": "1024x1024", "quality": quality,
         "background": "transparent", "n": 1}).encode())
    req.add_header("Content-Type", "application/json")
    _auth(req)
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())["data"][0]["b64_json"]
    with open(out_png, "wb") as f:
        f.write(base64.b64decode(data))


def edit(base_png, prompt, out_png, quality="medium"):
    """기본 얼굴 그림을 바탕으로 표정만 바꾼다 (같은 인물 유지)"""
    b = uuid.uuid4().hex
    fields = {"model": "gpt-image-1", "prompt": prompt, "size": "1024x1024", "quality": quality,
              "background": "transparent", "n": "1"}
    body = b"".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                    for k, v in fields.items())
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.open(base_png).convert("RGBA").save(buf, "PNG")       # 줄여 둔 256색 그림도 RGBA 로 보낸다
    body += (f"--{b}\r\nContent-Disposition: form-data; name=\"image[]\"; filename=\"base.png\"\r\n"
             f"Content-Type: image/png\r\n\r\n").encode() + buf.getvalue() + b"\r\n"
    body += f"--{b}--\r\n".encode()
    req = urllib.request.Request("https://api.openai.com/v1/images/edits", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={b}")
    _auth(req)
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())["data"][0]["b64_json"]
    with open(out_png, "wb") as f:
        f.write(base64.b64decode(data))


def shrink(png):
    """투명 여백을 자르고 720px·256색으로 줄여 저장소에 가볍게 넣는다 (한 장 약 30KB)"""
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    im = im.crop(im.getbbox())
    im.thumbnail((720, 720), Image.LANCZOS)
    im.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(png, optimize=True)


def make(name, desc, faces=None):
    idx = load_index()
    faces = faces or list(FACE_PROMPTS)
    d = os.path.join(CHAR_DIR, name)
    os.makedirs(d, exist_ok=True)
    base = os.path.join(d, "기본.png")
    if not os.path.exists(base):
        print("▶ 기본 얼굴 만드는 중…", flush=True)
        generate(f"{desc}, {FACE_PROMPTS['기본']}.\n\nStyle: {STYLE}", base)
        shrink(base)
    for face in faces:
        if face == "기본" and os.path.exists(base):
            continue
        out = os.path.join(d, f"{face}.png")
        print(f"▶ 표정 '{face}' 만드는 중…", flush=True)
        edit(base, f"Keep exactly the same person, hairstyle, clothes and drawing style. "
                   f"Change only the facial expression and pose to: {FACE_PROMPTS[face]}.\n\nStyle: {STYLE}", out)
        shrink(out)
    ch = idx["characters"].setdefault(name, {"desc": desc, "source": "ai", "faces": {}})
    ch["desc"], ch["source"] = desc, "ai"
    for face in FACE_PROMPTS:
        if os.path.exists(os.path.join(d, f"{face}.png")):
            ch["faces"][face] = f"{name}/{face}.png"
    save_index(idx)
    print(f"완료: {d}")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        idx = load_index()
        for name, ch in idx["characters"].items():
            print(f"{name:8s} [{ch['source']}] {ch.get('desc', '')}\n         표정: {' '.join(ch['faces'])}")
    elif len(sys.argv) >= 4 and sys.argv[1] == "make":
        make(sys.argv[2], sys.argv[3], sys.argv[4:] or None)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
