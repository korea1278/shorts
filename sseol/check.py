#!/usr/bin/env python3
"""완성 영상 자동 검수 — 결과는 짧은 요약 글 + 모아 보기 그림 1장

사용법:
    python3 sseol/check.py <id>        # 예: python3 sseol/check.py 20261008-housecar

검사 항목
  1. 받아쓰기(OpenAI Whisper)와 대본 비교 → 다르게 들린 부분만 보여줌 (뭉개진 발음 찾기)
  2. 영상 중간의 빈 구간 (0.3초 넘는 침묵)
  3. 음량 (유튜브 기준 -14 LUFS 근처인지)
  4. 길이·말 빠르기, 이라스토야 장수
  5. 모아 보기 그림 sseol/output/<id>/check.png (약 2.4초 간격 화면) — 이것 한 장만 열어 보면 된다
"""
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def transcribe(path):
    """Whisper 받아쓰기 (키는 환경변수 또는 클라우드 환경이 자동으로 붙여 준다)"""
    audio = run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", "16000", "-b:a", "48k",
                 "/tmp/_check.mp3"])
    if audio.returncode:
        return None
    b = uuid.uuid4().hex
    with open("/tmp/_check.mp3", "rb") as f:
        data = f.read()
    body = b"".join([
        f"--{b}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-1\r\n".encode(),
        f"--{b}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\nko\r\n".encode(),
        f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.mp3\"\r\n"
        f"Content-Type: audio/mpeg\r\n\r\n".encode(), data, f"\r\n--{b}--\r\n".encode()])
    req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={b}")
    if os.environ.get("OPENAI_API_KEY"):
        req.add_header("Authorization", "Bearer " + os.environ["OPENAI_API_KEY"])
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode())["text"]


def norm(s):
    return re.sub(r"[\s.,?!…'\"“”]", "", s)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    jid = sys.argv[1]
    job = json.load(open(os.path.join(ROOT, "jobs", f"{jid}.json"), encoding="utf-8"))
    out = os.path.join(ROOT, "output", jid)
    mp4 = os.path.join(out, f"{jid}.mp4")
    script = " ".join(s["text"] for s in job["scenes"])
    report, problems = [], 0

    # 길이·빠르기
    dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4]).stdout)
    n = len(norm(script))
    report.append(f"길이 {dur:.1f}초 · 글자 {n}자 · 1초에 {n / dur:.1f}글자")
    if not 25 <= dur <= 59:
        report.append("  ⚠ 길이가 25~59초를 벗어남")
        problems += 1

    # 받아쓰기 비교
    try:
        heard = transcribe(mp4)
    except Exception as e:
        heard = None
        report.append(f"  ⚠ 받아쓰기 실패: {e}")
    if heard:
        a, b = norm(script), norm(heard)
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        diffs = [(a[i1:i2], b[j1:j2]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
        report.append(f"받아쓰기 일치율 {sm.ratio() * 100:.1f}%")
        for x, y in diffs:
            # 앞뒤 글자를 붙여서 어디인지 알 수 있게
            k = a.find(x) if x else -1
            ctx = a[max(0, k - 4):k + len(x) + 4] if k >= 0 else x
            report.append(f"  · 대본 '{x or '(없음)'}' → 들린 것 '{y or '(없음)'}'   (근처: {ctx})")
        if len(diffs) > 3:
            problems += 1

    # 빈 구간
    sd = run(["ffmpeg", "-v", "info", "-i", mp4, "-af", "silencedetect=n=-40dB:d=0.3", "-f", "null", "-"]).stderr
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", sd)]
    ln = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", sd)]
    mid = [(s, d) for s, d in zip(st, ln) if s + d < dur - 0.3]
    report.append(f"중간 빈 구간(0.3초 넘음) {len(mid)}곳" + (": " + ", ".join(f"{s:.1f}초({d:.1f})" for s, d in mid)
                                                     if mid else ""))
    if mid:
        problems += 1

    # 음량
    eb = run(["ffmpeg", "-v", "info", "-i", mp4, "-af", "ebur128", "-f", "null", "-"]).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", eb)
    if m:
        lufs = float(m[-1])
        report.append(f"음량 {lufs:.1f} LUFS (기준 -14)")
        if not -17 <= lufs <= -12:
            problems += 1

    # 이라스토야 장수
    cr = os.path.join(out, "credits.txt")
    if os.path.exists(cr):
        report.append(open(cr, encoding="utf-8").readline().strip())

    # 모아 보기 그림
    sheet = os.path.join(out, "check.png")
    run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vf",
         "fps=1/2.4,crop=1080:1500:0:0,scale=180:-1,tile=8x3", "-frames:v", "1", "-update", "1", sheet])
    report.append(f"모아 보기 그림: {sheet}")

    print("\n".join(report))
    print("결과:", "✅ 문제 없음" if problems == 0 else f"⚠ 확인할 것 {problems}가지")


if __name__ == "__main__":
    main()
