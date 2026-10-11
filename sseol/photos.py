"""위키미디어 공용에서 쓸 수 있는 사진 찾기·받기 (출처·라이선스 확인)

  python3 sseol/photos.py search <영어 검색어>      → 쓸 수 있는 라이선스만 목록으로
  python3 sseol/photos.py get <File:이름> <저장 경로> → 사진 받고, job 에 넣을 "credit" 한 줄을 알려 줌

커뮤니티 글에 올라온 사진·밈은 쓰지 않는다 (퍼온 보도사진·남의 밈이 대부분). 여기서 받은 사진만
그림 항목 {"photo": "경로", "credit": "..."} 로 넣는다. 필요한 허용 도메인: commons.wikimedia.org, upload.wikimedia.org
"""
import json
import re
import sys
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "sseol-shorts/1.0 (personal video tool)"}
OK_LICENSES = ("CC0", "Public domain", "PD", "CC BY", "CC-BY")   # CC BY-SA 도 "CC BY" 로 시작한다. NC·ND 는 못 쓴다


def api(**params):
    params.update(format="json")
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def info(titles):
    d = api(action="query", titles="|".join(titles), prop="imageinfo", iiprop="url|extmetadata|size",
            iiurlwidth=1600)
    out = []
    for p in d.get("query", {}).get("pages", {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip() or "작자 미상"
        usable = lic.startswith(OK_LICENSES) and not re.search(r"\b(NC|ND)\b", lic)
        out.append({"title": p["title"], "license": lic, "artist": artist, "usable": usable,
                    "url": ii.get("thumburl") or ii.get("url"), "size": (ii.get("width"), ii.get("height"))})
    return out


def credit(x):
    return f"{x['artist']}, {x['license']}, 위키미디어 공용"


def search(q):
    d = api(action="query", list="search", srsearch=q + " filetype:bitmap", srnamespace=6, srlimit=20)
    titles = [h["title"] for h in d.get("query", {}).get("search", [])]
    for i, x in enumerate(info(titles) if titles else [], 1):
        if x["usable"]:
            print(f"{i:2}. {x['title']}  [{x['license']} · {x['artist'][:30]}]  {x['size'][0]}x{x['size'][1]}")


def get(title, out):
    x = info([title if title.startswith("File:") else "File:" + title])[0]
    if not x["usable"]:
        sys.exit(f"쓸 수 없는 라이선스입니다: {x['license']}")
    req = urllib.request.Request(x["url"], headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(out, "wb") as f:
        f.write(r.read())
    print(json.dumps({"photo": out, "credit": credit(x)}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "search":
        search(" ".join(sys.argv[2:]))
    elif len(sys.argv) == 4 and sys.argv[1] == "get":
        get(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
