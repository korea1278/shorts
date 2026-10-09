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
- 이라스토야 3줄: 그림 찾기와 그림 파일

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
영상 1편 기준: 나레이션 300자 정도(일레븐랩스 크레딧) + 이라스토야에 없는 장면만 AI 그림(OpenAI 중간 화질)
