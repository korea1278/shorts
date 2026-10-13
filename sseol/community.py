#!/usr/bin/env python3
"""커뮤니티 인기글 모으기 / 글 본문 읽기

사용법:
    python3 sseol/community.py best            # 인기글을 댓글·추천 많은 순으로 (못 여는 사이트는 건너뜀)
    python3 sseol/community.py read <글 주소>   # 글 본문을 글자로 (디시·보배드림·더쿠·아카·루리웹·엠팍·인스티즈)
    python3 sseol/community.py seen <주소> ...  # 사용자에게 추천한 글을 기록 (다음 "오늘 썰"에서 빠짐)

"best"는 (1) 전에 추천했거나 영상으로 만든 글을 빼고 (2) 본문을 미리 읽어 보고
영상으로 만들 수 없는 글(본문을 못 읽음·글이 너무 짧음 = 사진 위주)도 뺀 뒤 보여준다.
추천 기록은 세션이 바뀌어도 남도록 저장소의 `sseol-history` 브랜치(seen.txt)에 올린다.

사이트: 디시·개드립·보배드림 + 더쿠·아카라이브·루리웹·엠팍·인스티즈 (2026-10-09 추가)
루리웹은 PC 화면으로 읽고(휴대폰 화면은 허용 목록 밖 주소로 넘어감), 엠팍은 불펜 베스트 목록을 읽는다 (2026-10-13 고침).
사이트마다 PER_SITE개씩 본문을 확인해서 댓글 수가 안 보이는 사이트도 빠지지 않는다.
새 사이트 5곳은 링크 모양으로 글을 찾는 너그러운 방식이라, 사이트 화면이 바뀌어도 대충은 가져온다.

개드립은 글 본문 페이지가 자동 접속 차단(Cloudflare)이라 목록만 가져온다.
에펨코리아는 자동 접속 차단(430)이라 쓰지 않는다. 차단을 우회하지 않는다.
"""
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")


PC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PC_SITES = ("ruliweb.com",)   # 휴대폰 UA면 허용 목록 밖 모바일 주소(m.ruliweb.com)로 넘어가는 곳


def get(url):
    ua = PC_UA if any(d in url for d in PC_SITES) else UA
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "ko-KR,ko"})
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
    ms = list(re.finditer(r'<a[^>]+href=["\'](' + link_re + r')["\'][^>]*>(.*?)</a>', s, re.S))
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
    s = get("https://bbs.ruliweb.com/best/humor_only")
    out = []
    for row in s.split('<tr class="table_body')[1:]:            # 한 줄 = 글 하나
        a = re.search(r'href="(/best/board/\d+/read/\d+)', row)
        t = re.search(r'<(strong|span) class="text_over">(.*?)</\1>', row, re.S)
        if not (a and t):
            continue
        out.append({"site": "루리웹", "title": clean(t.group(2)), "url": "https://bbs.ruliweb.com" + a.group(1),
                    "comments": num((re.search(r'num_reply[^>]*>\s*\((\d+)\)', row) or [None, ""])[1]),
                    "likes": num((re.search(r'<td class="recomd">\s*(\d+)', row) or [None, ""])[1]),
                    "views": num((re.search(r'<td class="hit">\s*(\d+)', row) or [None, ""])[1])})
    return out


def mlbpark():
    s = get("https://mlbpark.donga.com/mp/best.php?b=bullpen&m=reply")      # 불펜 베스트
    out, seen = [], set()
    for m in re.finditer(r"href='(https://mlbpark\.donga\.com/mp/b\.php\?[^']*id=(\d+)[^']*)'[^>]*class='txt'>(.*?)</a>", s, re.S):
        if m.group(2) in seen:
            continue
        seen.add(m.group(2))
        out.append({"site": "엠팍", "title": " ".join(clean(m.group(3)).split()), "url": html.unescape(m.group(1)),
                    "comments": 0, "likes": 0, "views": 0})
    return out


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
    "ruliweb.com": [r'<div class="view_content[^"]*"[^>]*>(.*?)<div class="(?:row|board_bottom|notice_read)'],
    "mlbpark.donga.com": [r'<div class=["\']ar_txt["\'][^>]*>(.*?)<div class=["\'](?:tool_cont|btn_area|reply)'],
    "instiz.net": [r'<div[^>]+id="memo_content_1"[^>]*>(.*?)<div class="(?:sympathy|comment|ad)',
                   r'<div class="memo_content[^"]*">(.*?)<div class="(?:sympathy|comment)'],
}


HERE = os.path.dirname(os.path.abspath(__file__))
HIST_BRANCH = "sseol-history"
MIN_BODY = 150          # 본문 글자 수가 이보다 적으면 사진 위주 글로 보고 뺀다
PER_SITE = 15           # 사이트마다 본문을 미리 읽어 볼 글 수 (점수 높은 순)
# 고르는 기준에서 빼는 주제 (정치·사건사고·범죄). 제목에 있으면 본문을 읽기 전에 뺀다
BAN = re.compile(r"대통령|국회|의원|정당|민주당|국민의힘|정의당|탄핵|선거|李|尹|성폭력|성범죄|성추행|살인|폭행|사망|숨져|"
                 r"체포|구속|혐의|기소|불법체류|마약|사기범|흉기|참사|사고 현장|칼부림|속보|^공지$")


def git(*args, inp=None):
    return subprocess.run(["git", "-C", HERE, *args], input=inp, capture_output=True, text=True)


def norm(url):
    """같은 글이면 같은 키 (주소 꼬리의 쪽수·검색 조건 무시)"""
    url = url.split("#")[0].replace("://www.", "://").replace("://m.", "://")
    m = re.search(r"[?&](?:id|no)=(\d+)", url)
    if m:
        return url.split("?")[0] + "?" + m.group(1)
    url = url.split("?")[0]
    m = re.search(r"^(.*/\d{5,})", url)
    return m.group(1) if m else url


def load_seen():
    """전에 추천한 글(sseol-history 브랜치) + 영상으로 만든 글(jobs 의 source)"""
    seen = set()
    if git("fetch", "-q", "origin", HIST_BRANCH).returncode == 0:
        seen |= {norm(l.strip()) for l in git("show", f"origin/{HIST_BRANCH}:seen.txt").stdout.splitlines() if l.strip()}
    jobs = os.path.join(HERE, "jobs")
    for f in os.listdir(jobs):
        try:
            src = json.load(open(os.path.join(jobs, f))).get("source", "")
        except Exception:
            continue
        if src.startswith("http"):
            seen.add(norm(src))
    return seen


def save_seen(urls):
    """추천한 글 주소를 sseol-history 브랜치의 seen.txt 에 덧붙여 올린다 (작업 중인 파일은 건드리지 않음)"""
    git("fetch", "-q", "origin", HIST_BRANCH)
    parent = git("rev-parse", "-q", "--verify", f"origin/{HIST_BRANCH}").stdout.strip()
    old = git("show", f"origin/{HIST_BRANCH}:seen.txt").stdout if parent else ""
    have = {norm(l) for l in old.splitlines() if l.strip()}
    add = []
    for u in urls:
        if norm(u) not in have:
            have.add(norm(u))
            add.append(u)
    if not add:
        print("이미 기록된 글입니다.")
        return
    blob = git("hash-object", "-w", "--stdin", inp=old + "".join(u + "\n" for u in add)).stdout.strip()
    tree = git("mktree", inp=f"100644 blob {blob}\tseen.txt\n").stdout.strip()
    commit = git("commit-tree", tree, *(["-p", parent] if parent else []), "-m", f"추천 기록 {len(add)}개").stdout.strip()
    for wait in (0, 2, 4, 8, 16):
        if wait:
            subprocess.run(["sleep", str(wait)])
        r = git("push", "-q", "origin", f"{commit}:refs/heads/{HIST_BRANCH}")
        if r.returncode == 0:
            print(f"추천 기록 {len(add)}개 저장 (전체 {len(have)}개)")
            return
    print("추천 기록을 올리지 못함:", r.stderr.strip(), file=sys.stderr)


def fetch_body(url):
    """(제목, 본문, 그림 수, 본문 상자를 찾았는지). 읽을 수 없는 사이트면 None"""
    if "dogdrip.net" in url:
        return None
    s = get(url)
    found = True
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
            found = False
            body = re.search(r'<meta property="og:description" content="([^"]*)"', s)
    else:
        return None
    imgs = len(re.findall(r"<img", body.group(1))) if body else 0
    return (clean(title.group(1)) if title else "?", clean(body.group(1)) if body else "", imgs, found and bool(body))


def makeable(p):
    """영상으로 만들 수 있는 글인지: 본문을 읽을 수 있고, 글이 충분히 길다 (사진 한 장짜리가 아님)"""
    try:
        got = fetch_body(p["url"])
    except Exception:
        return False, "본문 못 읽음"
    if not got:
        return False, "본문 자동으로 못 읽는 사이트"
    _, text, imgs, found = got
    letters = len(re.sub(r"\s", "", text))
    if not found:
        return False, "본문 상자 못 찾음"
    if letters < MIN_BODY:
        return False, f"글이 짧음 ({letters}자, 그림 {imgs}개)"
    if letters < 400 and letters < imgs * 20:
        return False, f"사진 위주 ({letters}자, 그림 {imgs}개)"
    p["body_len"], p["imgs"] = letters, imgs
    return True, ""


def best(show_all=False):
    posts = []
    for name, fn in SITES:
        try:
            got = fn()
            posts += got
            print(f"# {name}: {len(got)}개", file=sys.stderr)
        except Exception as e:
            print(f"# {name}: 못 가져옴 ({e})", file=sys.stderr)
    posts.sort(key=lambda p: p["comments"] * 2 + p["likes"], reverse=True)

    seen = set() if show_all else load_seen()
    fresh, dup, ban = [], 0, 0
    for p in posts:
        k = norm(p["url"])
        if k in seen:
            dup += 1
            continue
        seen.add(k)                                       # 목록 안의 겹친 글도 하나만
        if BAN.search(p["title"]):
            ban += 1
            continue
        fresh.append(p)
    print(f"# 전에 추천·제작한 글 {dup}개 뺌, 정치·사건사고 제목 {ban}개 뺌", file=sys.stderr)

    by_site = {}                                          # 사이트마다 골고루 (숫자가 없는 사이트도 빠지지 않게)
    for p in fresh:
        by_site.setdefault(p["site"], []).append(p)
    top = [p for ps in by_site.values() for p in ps[:PER_SITE]]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(makeable, top))
    out, why = [], {}
    for p, (ok, reason) in zip(top, res):
        if ok:
            out.append(p)
        else:
            why[reason.split(" (")[0]] = why.get(reason.split(" (")[0], 0) + 1
    print("# 영상으로 못 만들 글 뺌: " + (", ".join(f"{k} {v}개" for k, v in why.items()) or "없음"), file=sys.stderr)
    for i, p in enumerate(out, 1):
        print(f"{i:3d}. [{p['site']}] {p['title']}  (댓글 {p['comments']} · 추천 {p['likes']}"
              f"{' · 조회 ' + str(p['views']) if p['views'] else ''} · 본문 {p['body_len']}자 · 그림 {p['imgs']}개)  {p['url']}")


def read(url):
    got = fetch_body(url)
    if not got:
        print("이 사이트는 본문을 자동으로 읽을 수 없습니다. 글 내용을 직접 붙여 넣어 주세요.")
        return
    title, text, imgs, _ = got
    print("제목:", title)
    print(f"(그림 {imgs}개)")
    print(text or "(본문을 찾지 못함)")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "best":
        best(show_all="--all" in sys.argv)
    elif len(sys.argv) >= 3 and sys.argv[1] == "seen":
        save_seen(sys.argv[2:])
    elif len(sys.argv) >= 3 and sys.argv[1] == "read":
        read(sys.argv[2])
    else:
        print(__doc__)
