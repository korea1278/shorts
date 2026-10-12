#!/usr/bin/env python3
"""실제 사진 찾기 — 위키미디어 공용(Wikimedia Commons)의 자유 이용 사진만

사용법:
    python3 sseol/photos.py search 경복궁               # 사진 목록 (제목·라이선스·작가·크기)
    python3 sseol/photos.py search "Hwaseong Fortress" --sheet out.png   # 후보를 한 장에 모아 보기
    python3 sseol/photos.py info "File:Gyeongbokgung.jpg"

쓸 수 있는 라이선스: 퍼블릭 도메인 · CC0 · CC BY · CC BY-SA (작가·라이선스 표시 필수 → 엔진이 화면 구석과
credits.txt 에 자동으로 넣는다). NC(비영리)·ND(변경 금지)·저작권 사진은 목록에서 뺀다.
초상권 경고가 붙은 사진(Personality rights)도 뺀다.
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = "sseol-shorts/1.0 (https://github.com/korea1278/shorts)"   # 위키미디어는 봇 이름을 밝혀야 한다


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def api(**params):
    params.update(action="query", format="json", formatversion=2)
    return json.loads(get(API + "?" + urllib.parse.urlencode(params)))


def plain(s):
    """extmetadata 의 HTML 을 글자만"""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def license_ok(short):
    s = (short or "").lower()
    if re.search(r"\bnc\b|\bnd\b|-nc|-nd|fair use|copyrighted", s):
        return False
    return bool(re.search(r"public domain|^pd|cc0|cc[ -]by", s))


def title_of(ref):
    """'File:이름.jpg' / 공용 주소 / 이름.jpg → 'File:이름.jpg'"""
    ref = urllib.parse.unquote(ref.split("#")[0])
    m = re.search(r"(?:File|파일):(.+)$", ref)
    name = m.group(1) if m else ref.rsplit("/", 1)[-1]
    return "File:" + name.replace("_", " ").strip()


def _pages_info(pages, width):
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        v = lambda k: plain((meta.get(k) or {}).get("value", ""))  # noqa: E731
        info = {
            "title": p["title"],
            "page": ii.get("descriptionurl", ""),
            "url": ii.get("thumburl") or ii.get("url", ""),
            "w": ii.get("width", 0), "h": ii.get("height", 0),
            "license": v("LicenseShortName") or v("License"),
            "artist": v("Artist")[:60] or "작가 미상",
            "desc": v("ImageDescription")[:80],
            "restrict": v("Restrictions"),
        }
        info["ok"] = license_ok(info["license"]) and "personality" not in info["restrict"].lower()
        out.append(info)
    return out


def search(q, n=12, width=1600):
    r = api(generator="search", gsrsearch=f"{q} filetype:bitmap", gsrnamespace=6, gsrlimit=n * 2,
            prop="imageinfo", iiprop="url|size|extmetadata", iiurlwidth=width)
    pages = sorted((r.get("query") or {}).get("pages", []), key=lambda p: p.get("index", 0))
    return [i for i in _pages_info(pages, width) if i["ok"]][:n]


def info(ref, width=1600):
    r = api(titles=title_of(ref), prop="imageinfo", iiprop="url|size|extmetadata", iiurlwidth=width)
    pages = (r.get("query") or {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        raise RuntimeError(f"위키미디어 공용에 없는 사진: {ref}")
    return _pages_info(pages, width)[0]


def credit_line(i):
    return f"{i['artist']} / {i['license']} / Wikimedia Commons"


def sheet(items, out_png):
    """후보 사진을 번호와 함께 한 장에 (고를 때 이 그림 한 장만 본다)"""
    import io
    from PIL import Image, ImageDraw
    cols, cw, chh = 4, 300, 220
    rows = (len(items) + cols - 1) // cols
    im = Image.new("RGB", (cols * cw, rows * chh), (30, 30, 30))
    d = ImageDraw.Draw(im)
    for k, i in enumerate(items):
        try:
            th = Image.open(io.BytesIO(get(i["url"].replace("/1600px-", "/300px-")))).convert("RGB")
            th.thumbnail((cw - 8, chh - 30))
            im.paste(th, ((k % cols) * cw + 4, (k // cols) * chh + 4))
        except Exception:
            pass
        d.text(((k % cols) * cw + 6, (k // cols) * chh + chh - 22), f"{k + 1}. {i['license'][:22]}",
               fill=(255, 255, 0))
    im.save(out_png)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == "search":
        items = search(arg)
        if not items:
            print("자유 이용 사진을 못 찾음 (영어 검색어로도 해 보세요)")
        for k, i in enumerate(items, 1):
            print(f"{k:2d}. {i['title']}  [{i['license']}]  {i['w']}x{i['h']}  작가: {i['artist']}")
            if i["desc"]:
                print(f"      {i['desc']}")
        if "--sheet" in sys.argv and items:
            out = sys.argv[sys.argv.index("--sheet") + 1]
            sheet(items, out)
            print(f"모아 보기: {out}")
    elif cmd == "info":
        i = info(arg)
        print(json.dumps(i, ensure_ascii=False, indent=1))
        if not i["ok"]:
            print("⚠ 쓸 수 없는 사진 (라이선스 또는 초상권 경고)")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
