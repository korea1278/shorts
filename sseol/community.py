#!/usr/bin/env python3
"""커뮤니티 인기글 모으기 / 글 본문 읽기

사용법:
    python3 sseol/community.py best            # 3곳 인기글을 댓글·추천 많은 순으로
    python3 sseol/community.py read <글 주소>   # 글 본문을 글자로 (디시·보배드림)

개드립은 글 본문 페이지가 자동 접속 차단(Cloudflare)이라 목록만 가져온다.
에펨코리아는 자동 접속 차단(430)이라 쓰지 않는다. 차단을 우회하지 않는다.
"""
import html
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="ignore")


def clean(s):
    s = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def num(s):
    s = re.sub(r"[^\d]", "", s or "")
    return int(s) if s else 0


def dogdrip():
    s = get("https://www.dogdrip.net/dogdrip")
    out, seen = [], set()
    for m in re.finditer(r'<a href="(?:https://www\.dogdrip\.net)?/(?:dogdrip/)?(\d+)[^"]*" class="ed title-link[^"]*"[^>]*>(.*?)</a>', s, re.S):
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        tail = s[m.end():m.end() + 1500]
        cm = re.match(r'\s*<span class="ed text-primary text-xxsmall">(\d+)</span>', tail)
        likes = re.search(r'fa-thumbs-up"></i></span>\s*<span[^>]*>\s*(\d+)', tail)
        out.append({"site": "개드립", "title": clean(m.group(2)), "url": f"https://www.dogdrip.net/{m.group(1)}",
                    "comments": num(cm.group(1) if cm else ""), "likes": num(likes.group(1) if likes else ""),
                    "views": 0})
    return out


def bobaedream():
    s = get("https://m.bobaedream.co.kr/board/new_writing/best")
    out = []
    for m in re.finditer(r'<a href="(/board/bbs_view/best/[^"]+)">\s*<div class="txt">\s*<span class="cont">(.*?)</span>'
                         r'(.*?)<span class="num">(\d+)</span>', s, re.S):
        rest = m.group(3)
        out.append({"site": "보배드림", "title": clean(m.group(2)), "url": "https://m.bobaedream.co.kr" + m.group(1),
                    "comments": num(m.group(4)),
                    "likes": num((re.search(r"추천 (\d+)", rest) or [None, ""])[1]),
                    "views": num((re.search(r"조회 (\d+)", rest) or [None, ""])[1])})
    return out


def dcinside():
    s = get("https://m.dcinside.com/board/dcbest")
    out = []
    for m in re.finditer(r'<a href="(https://m\.dcinside\.com/board/dcbest/\d+)" class="lt">(.*?)</a>\s*'
                         r'<a href="[^"]*#comment_box" class="rt">\s*<span class="ct ?">(\d+)</span>', s, re.S):
        body = m.group(2)
        title = re.search(r'<span class="subjectin">(.*?)</span>', body, re.S)
        out.append({"site": "디시", "title": clean(title.group(1)) if title else "", "url": m.group(1),
                    "comments": num(m.group(3)),
                    "likes": num((re.search(r"추천 <span>(\d+)</span>", body) or [None, ""])[1]),
                    "views": num((re.search(r"조회 (\d+)", body) or [None, ""])[1])})
    return out


def best():
    posts = []
    for name, fn in (("개드립", dogdrip), ("보배드림", bobaedream), ("디시", dcinside)):
        try:
            got = fn()
            posts += got
            print(f"# {name}: {len(got)}개", file=sys.stderr)
        except Exception as e:
            print(f"# {name}: 못 가져옴 ({e})", file=sys.stderr)
    posts.sort(key=lambda p: p["comments"] * 2 + p["likes"], reverse=True)
    for i, p in enumerate(posts, 1):
        print(f"{i:3d}. [{p['site']}] {p['title']}  (댓글 {p['comments']} · 추천 {p['likes']}"
              f"{' · 조회 ' + str(p['views']) if p['views'] else ''})  {p['url']}")


def read(url):
    s = get(url)
    if "dcinside.com" in url:
        title = re.search(r'<span class="tit">(.*?)</span>', s, re.S)
        body = re.search(r'<div class="thum-txtin">(.*?)</div>\s*</div>\s*<div class="(?:recom|innerbox|outr)', s, re.S) \
            or re.search(r'<div class="thum-txtin">(.*?)<div class="(?:recom|btn)', s, re.S)
    elif "bobaedream" in url:
        title = re.search(r'<div class="title">(.*?)</div>', s, re.S) or re.search(r"<title>(.*?)</title>", s)
        body = re.search(r'<div class="article-body">(.*?)</div>\s*(?:<div class="(?:btn|recommend|bottom))', s, re.S) \
            or re.search(r'<div class="article-body">(.*?)<div class="reply', s, re.S)
    else:
        print("이 사이트는 본문을 자동으로 읽을 수 없습니다. 글 내용을 직접 붙여 넣어 주세요.")
        return
    imgs = len(re.findall(r"<img", body.group(1))) if body else 0
    print("제목:", clean(title.group(1)) if title else "?")
    print(f"(그림 {imgs}개)")
    print(clean(body.group(1)) if body else "(본문을 찾지 못함)")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "best":
        best()
    elif len(sys.argv) >= 3 and sys.argv[1] == "read":
        read(sys.argv[2])
    else:
        print(__doc__)
