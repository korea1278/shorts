#!/usr/bin/env python3
"""커뮤니티 인기글 모으기 / 글 본문 읽기

사용법:
    python3 sseol/community.py best            # 인기글을 댓글·추천 많은 순으로 (못 여는 사이트는 건너뜀)
    python3 sseol/community.py read <글 주소>   # 글 본문을 글자로 (디시·보배드림·더쿠·아카·루리웹·엠팍·인스티즈)

사이트: 디시·개드립·보배드림 + 더쿠·아카라이브·루리웹·엠팍·인스티즈 (2026-10-09 추가)
새 사이트 5곳은 링크 모양으로 글을 찾는 너그러운 방식이라, 사이트 화면이 바뀌어도 대충은 가져온다.

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


def link_list(site, url, link_re, base=""):
    """목록 페이지에서 글 링크(link_re 의 1번 묶음 = 주소)를 찾고, 링크 글자를 제목으로,
    바로 뒤의 [12] 또는 (12) 를 댓글 수로 본다. 추천·조회는 근처에 '추천 N' '조회 N' 이 있을 때만."""
    s = get(url)
    out, seen = [], set()
    ms = list(re.finditer(r'<a[^>]+href="(' + link_re + r')"[^>]*>(.*?)</a>', s, re.S))
    for i, m in enumerate(ms):
        href = html.unescape(m.group(1))
        key = re.sub(r"[?&](page|mode|category|p|m)=[^&]*", "", href)
        title = clean(re.sub(r"<span[^>]*(?:reply|comment|num|cmt|count)[^>]*>.*?</span>", "", m.group(2), flags=re.S))
        title = re.sub(r"\s*[\[(]\d+[\])]\s*$", "", title).strip()
        if key in seen or len(title) < 4:
            continue
        seen.add(key)
        stop = min(m.end() + 600, ms[i + 1].start() if i + 1 < len(ms) else len(s))   # 다음 글 앞까지만
        near = clean(s[m.start():max(stop, m.end())])[:200]
        cm = re.search(r"[\[(](\d{1,5})[\])]", near)
        out.append({"site": site, "title": title.split("\n")[0][:80], "url": href if href.startswith("http") else base + href,
                    "comments": num(cm.group(1) if cm else ""),
                    "likes": num((re.search(r"추천\s*(\d+)", near) or [None, ""])[1]),
                    "views": num((re.search(r"조회\s*(\d+)", near) or [None, ""])[1])})
    return out


def theqoo():
    return link_list("더쿠", "https://theqoo.net/hot", r"/hot/\d{6,}[^\"]*", "https://theqoo.net")


def arca():
    return link_list("아카라이브", "https://arca.live/b/live?mode=best", r"/b/[a-z0-9_]+/\d{6,}[^\"]*", "https://arca.live")


def ruliweb():
    return link_list("루리웹", "https://bbs.ruliweb.com/best/humor_only",
                     r"https://bbs\.ruliweb\.com/best/board/\d+/read/\d+[^\"]*")


def mlbpark():
    return link_list("엠팍", "https://mlbpark.donga.com/mp/best.php?b=bullpen&m=view",
                     r"https://mlbpark\.donga\.com/mp/b\.php\?[^\"]*id=\d+[^\"]*")


def instiz():
    return link_list("인스티즈", "https://www.instiz.net/pt", r"(?:https://www\.instiz\.net)?/pt/\d{6,}[^\"]*",
                     "https://www.instiz.net")


SITES = (("개드립", dogdrip), ("보배드림", bobaedream), ("디시", dcinside), ("더쿠", theqoo), ("아카라이브", arca),
         ("루리웹", ruliweb), ("엠팍", mlbpark), ("인스티즈", instiz))

# 본문 상자 (사이트별로 차례로 찾아본다)
BODY_RE = {
    "theqoo.net": [r'<div class="rd_body[^"]*">(.*?)<div class="(?:rd_ft|document_popup)'],
    "arca.live": [r'<div class="fr-view article-content">(.*?)</div>\s*</div>\s*<div class="(?:article-menu|included)',
                  r'<div class="fr-view article-content">(.*?)<div class="(?:article-menu|vote)'],
    "ruliweb.com": [r'<div class="view_content[^"]*">(.*?)<div class="(?:row|board_bottom|notice_read)'],
    "mlbpark.donga.com": [r'<div class="ar_txt"[^>]*>(.*?)<div class="(?:tool_cont|btn_area|reply)'],
    "instiz.net": [r'<div[^>]+id="memo_content_1"[^>]*>(.*?)<div class="(?:sympathy|comment|ad)',
                   r'<div class="memo_content[^"]*">(.*?)<div class="(?:sympathy|comment)'],
}


def best():
    posts = []
    for name, fn in SITES:
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
    elif any(k in url for k in BODY_RE):
        k = next(k for k in BODY_RE if k in url)
        title = re.search(r'<meta property="og:title" content="([^"]*)"', s) or re.search(r"<title>(.*?)</title>", s, re.S)
        body = next((b for b in (re.search(r, s, re.S) for r in BODY_RE[k]) if b), None)
        if not body:                                      # 화면이 바뀌었으면 요약 글이라도
            body = re.search(r'<meta property="og:description" content="([^"]*)"', s)
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
