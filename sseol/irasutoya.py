#!/usr/bin/env python3
"""이라스토야(いらすとや) 그림 찾기

사용법:
    python3 sseol/irasutoya.py search 警察        # 일본어 검색어로 그림 글 목록
    python3 sseol/irasutoya.py images <글 주소>    # 그 글에 있는 그림 파일 주소들

이용 조건: 수익 영상에도 무료지만 영상 1편에 20장까지. 그림 판매·재배포 금지.
"""
import html
import re
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
IMG_RE = r"https://(?:blogger\.googleusercontent\.com/img/[^\"'\s<>]+|\d\.bp\.blogspot\.com/[^\"'\s<>]+)"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def search(q):
    s = get("https://www.irasutoya.com/search?q=" + urllib.parse.quote(q)).decode("utf-8", "ignore")
    out = []
    for m in re.finditer(r"bp_thumbnail_resize\(\"([^\"]+)\",\"([^\"]+)\"\)\);\s*</script></a>.*?"
                         r"<h2>\s*<a href='([^']+)'", s, re.S):
        out.append((html.unescape(m.group(2)), m.group(3).replace("?m=1", ""), m.group(1)))
    return out


def images(post_url):
    s = get(post_url).decode("utf-8", "ignore")
    i = s.find("class='entry'")
    seg = s[i:i + 20000] if i >= 0 else s
    for stop in ("twitterbtn", "post-footer", "button_random"):
        k = seg.find(stop)
        if k > 0:
            seg = seg[:k]
    seen, out = set(), []
    for u in re.findall(IMG_RE, seg):
        if "thumbnail_" in u or not re.search(r"\.(png|jpg|jpeg|gif)$", u, re.I):
            continue
        key = u.rsplit("/", 1)[-1]
        if key in seen:
            continue
        seen.add(key)
        out.append(re.sub(r"/s\d+(-c)?/", "/s800/", u))
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "search":
        for i, (t, u, _) in enumerate(search(sys.argv[2]), 1):
            print(f"{i:2d}. {t}  {u}")
    elif len(sys.argv) >= 3 and sys.argv[1] == "images":
        for u in images(sys.argv[2]):
            print(u)
    else:
        print(__doc__)
