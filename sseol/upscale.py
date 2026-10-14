#!/usr/bin/env python3
"""저화질 짤·사진 2배 업스케일 (쇼츠에 넣기 전 전처리)

사용법:
    python3 sseol/upscale.py                 # assets/memes 와 photos 의 작은 그림을 미리 전부 처리
    python3 sseol/upscale.py <파일> [<파일>…]  # 특정 그림만 (결과 경로를 보여줌)
    python3 sseol/upscale.py --check         # 크기만 보고 무엇이 업스케일될지 알려줌

make_short.py 가 밈·사진을 쓸 때 자동으로 부른다 (prepare). 따로 실행하지 않아도 된다.

처리 순서 (작은 변이 MIN_SIDE 보다 작을 때만, 큰 그림은 그대로)
  1. JPG 깍두기(압축 노이즈)를 살짝 지운다 — 키우면 노이즈도 같이 커지기 때문
  2. FSRCNN 슈퍼레졸루션으로 2배 (선과 글자 가장자리를 계단 없이). 모델 파일은 assets/models (39KB, 저장소에 들어 있음)
     OpenCV 가 없으면 Lanczos 2배로 대신한다
  3. 가장자리만 살짝 선명하게 (언샤프 마스크)
  4. 2배로도 MIN_SIDE 에 못 미치면 한 번 더 2배 (최대 4배)
  PNG 투명 부분은 따로 키워서 다시 붙인다. 움짤(GIF)은 첫 장만 쓴다.

결과는 sseol/assets/.upscaled/ 에 저장해 두고 다시 쓴다 (원본은 건드리지 않음, 원본이 바뀌면 새로 만듦).
"""
import hashlib
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "assets", ".upscaled")
MODEL = os.path.join(ROOT, "assets", "models", "FSRCNN_x2.pb")
MIN_SIDE = 800          # 작은 변이 이보다 작으면 2배씩 키움 (쇼츠 그림 영역 1080x960 에서 늘어나 깨지지 않게)
MAX_PASSES = 2          # 2배씩 최대 두 번 (= 4배)
FOLDERS = ("assets/memes", "photos")
EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

_sr = None              # 슈퍼레졸루션 모델 (처음 한 번만 읽음). False = 쓸 수 없음


def _ensure_cv2():
    """클라우드 세션은 매번 새로 시작하니, OpenCV(슈퍼레졸루션 포함)가 없으면 한 번 설치해 본다"""
    try:
        import cv2  # noqa: F401
        return
    except ImportError:
        pass
    import subprocess
    print("▶ 업스케일용 OpenCV 설치 중… (세션마다 처음 한 번, 약 30초)", flush=True)
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages",
                        "opencv-contrib-python-headless"], check=False, timeout=300, capture_output=True)
    except Exception:
        pass


def _model():
    global _sr
    if _sr is None:
        _sr = False
        _ensure_cv2()
        try:
            import cv2
            if os.path.exists(MODEL) and hasattr(cv2, "dnn_superres"):
                sr = cv2.dnn_superres.DnnSuperResImpl_create()
                sr.readModel(MODEL)
                sr.setModel("fsrcnn", 2)
                _sr = sr
        except Exception:
            _sr = False
        if _sr is False:
            print("▶ (업스케일: OpenCV 슈퍼레졸루션이 없어 Lanczos 로 키웁니다. "
                  "더 선명하게: pip install --break-system-packages opencv-contrib-python-headless)", flush=True)
    return _sr


def _denoise(rgb):
    """JPG 압축 노이즈만 살짝 (선은 살림)"""
    try:
        import cv2
        return cv2.fastNlMeansDenoisingColored(rgb, None, 3, 3, 5, 15)
    except Exception:
        return np.asarray(Image.fromarray(rgb).filter(ImageFilter.SMOOTH))


def _x2(rgb):
    """RGB 배열 2배"""
    sr = _model()
    if sr:
        import cv2
        return cv2.cvtColor(sr.upsample(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)), cv2.COLOR_BGR2RGB)
    im = Image.fromarray(rgb)
    return np.asarray(im.resize((im.width * 2, im.height * 2), Image.LANCZOS))


def upscale_image(img, min_side=MIN_SIDE):
    """PIL 그림 → (키운 그림, 배율). 이미 충분히 크면 그대로 (배율 1)."""
    img.seek(0) if hasattr(img, "seek") else None
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    im = img.convert("RGBA" if has_alpha else "RGB")
    scale, passes = 1, 0
    if min(im.size) >= min_side:
        return im, 1
    _model()                                       # OpenCV 준비 (노이즈 지우기에도 씀)
    rgb = np.asarray(im.convert("RGB"))
    if (img.format or "").upper() in ("JPEG", "WEBP") or not has_alpha:
        rgb = _denoise(np.ascontiguousarray(rgb))
    while min(rgb.shape[:2]) < min_side and passes < MAX_PASSES:
        rgb = _x2(np.ascontiguousarray(rgb))
        scale, passes = scale * 2, passes + 1
    out = Image.fromarray(rgb).filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))
    if has_alpha:
        a = im.getchannel("A").resize(out.size, Image.LANCZOS)
        out = out.convert("RGBA")
        out.putalpha(a)
    return out, scale


def prepare(path, min_side=MIN_SIDE, quiet=False):
    """작은 그림이면 업스케일한 파일 경로를, 아니면 원래 경로를 돌려준다 (결과는 저장해 두고 다시 씀)."""
    try:
        with Image.open(path) as im:
            if min(im.size) >= min_side:
                return path
            size = im.size
    except Exception:
        return path
    with open(path, "rb") as f:
        key = hashlib.sha1(f.read() + f"{min_side}|{os.path.exists(MODEL)}".encode()).hexdigest()[:12]
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f"{os.path.splitext(os.path.basename(path))[0]}_{key}.png")
    if not os.path.exists(out):
        with Image.open(path) as im:
            big, s = upscale_image(im, min_side)
        big.save(out)
        if not quiet:
            print(f"▶ 업스케일 {os.path.basename(path)}: {size[0]}x{size[1]} → {big.width}x{big.height} ({s}배)",
                  flush=True)
    return out


def _files(args):
    if args:
        return args
    out = []
    for d in FOLDERS:
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            out += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.lower().endswith(EXTS)]
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    files = _files(args)
    if not files:
        print("처리할 그림이 없습니다 (sseol/assets/memes, sseol/photos)")
        return
    for f in files:
        with Image.open(f) as im:
            w, h = im.size
        if min(w, h) >= MIN_SIDE:
            print(f"  그대로   {w}x{h}  {os.path.relpath(f, ROOT)}")
        elif check:
            print(f"  키울 것  {w}x{h}  {os.path.relpath(f, ROOT)}")
        else:
            out = prepare(f, quiet=True)
            with Image.open(out) as im:
                print(f"  키움     {w}x{h} → {im.width}x{im.height}  {os.path.relpath(f, ROOT)}")


if __name__ == "__main__":
    main()
