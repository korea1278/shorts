# 썰 쇼츠 자동화 처음 설정 (한 번만)

## 1. 클로드 코드 웹 열기
1. 브라우저에서 claude.ai/code 접속
2. 처음이면 GitHub 연결 안내가 나옵니다 → korea1278 계정으로 승인
3. 저장소 선택에서 korea1278/shorts 고르기

## 2. 환경 설정 (환경 이름 옆 톱니바퀴 → 편집)
**네트워크 접근** → Allowed domains 칸에
```
cdn.jsdelivr.net
*.dcinside.com
*.fmkorea.com
*.dogdrip.net
*.bobaedream.co.kr
theqoo.net
arca.live
bbs.ruliweb.com
mlbpark.donga.com
www.instiz.net
*.irasutoya.com
*.bp.blogspot.com
blogger.googleusercontent.com
```
- `cdn.jsdelivr.net`: 제목·자막 폰트(프리텐다드)
- 커뮤니티: 인기글 찾기 (에펨코리아는 자동 접속을 막아서 지금은 못 씀). 더쿠·아카라이브·루리웹·엠팍·인스티즈는 2026-10-09 추가
- 이라스토야 3줄: 그림 찾기와 그림 파일 (예전 방식, 지금은 기본으로 안 씀)

**원본 사진 받기 (2026-10-14 추가)** — 커뮤니티 본문 사진·뉴스 사진 서버. 위 목록에 아래 줄도 넣어 주세요
```
*.dcinside.co.kr
*.ruliweb.com
*.namu.la
*.theqoo.net
*.donga.com
*.instiz.net
*.pstatic.net
```
- 디시 사진(dcimg*.dcinside.com·.co.kr), 루리웹(i*.ruliweb.com), 아카라이브(*.namu.la), 더쿠, 엠팍, 인스티즈
- `*.pstatic.net`: 네이버 뉴스 사진 (imgnews.pstatic.net)
- 다른 서버 사진이 막히면 클로드가 "못 받음"이라고 알려 줍니다. 그 사진은 `sseol/photos/`에 직접 넣으면 됩니다

**뉴스 사진 서버 (2026-10-22 추가)** — 뉴스 화제 쇼츠(예: 부캉이)용. 위 목록에 아래 줄도 넣어 주세요
```
menu.sidae.com
file2.nocutnews.co.kr
*.edge.naverncp.com
cdnweb01.wikitree.co.kr
pressian.com
img.sbs.co.kr
i3n.news1.kr
```

**(선택) 사이트 더 늘리기** — 아래 줄도 Allowed domains에 넣고 새 세션에서 "새 사이트 연결해줘"라고 하면
클로드가 실제로 열어 보고, 본문까지 읽혀서 영상으로 만들 수 있는 곳만 `community.py`에 추가합니다.
```
waffleboard.io
www.clien.net
*.ppomppu.co.kr
pann.nate.com
www.82cook.com
*.humoruniv.com
www.todayhumor.co.kr
*.inven.co.kr
www.slrclub.com
damoang.net
```
- `waffleboard.io`: 커뮤니티 순위 사이트 (어떤 커뮤니티를 더 붙일지 고를 때)
- 더쿠·인스티즈·아카라이브는 사이트가 자동 접속을 막아서(403) 지금은 안 나옵니다. 우회하지 않습니다.

**API credentials** → Add credential 두 번:

| 이름 | Allowed websites | 헤더 Name | Prefix | Value |
|---|---|---|---|---|
| ElevenLabs | api.elevenlabs.io | xi-api-key | (비움) | 일레븐랩스 API 키 |
| OpenAI | api.openai.com | Authorization | Bearer | OpenAI API 키 |

설정을 바꾼 뒤에는 **새 세션**에서 시작해야 확실히 적용됩니다.

## 3. 매일 쓰는 법
claude.ai/code → korea1278/shorts 새 세션 → **"오늘 썰"** 입력
→ 인기글 번호 리스트 → 번호 입력 → 대본 확인 → "진행" → 다운로드 링크로 MP4 받기

## 비용 감
영상 1편 기준: 나레이션 300자 정도(일레븐랩스 크레딧) + 원본 사진·밈이 없는 장면만 AI 그림(OpenAI 저화질)
