# 팬튜브 자동화 처음 설정 (한 번만)

## 1. 파일 올리기
GitHub의 korea1278/shorts 저장소에 이 묶음의 `fantube` 폴더와 `.claude` 폴더를 그대로 올립니다.
(저장소 화면 → Add file → Upload files → 두 폴더를 끌어다 놓기 → Commit changes)

## 2. 클로드 코드 웹 열기
1. 브라우저에서 claude.ai/code 접속
2. 처음이면 GitHub 연결 안내가 나옵니다 → korea1278 계정으로 승인
3. 저장소 선택에서 korea1278/shorts 고르기

## 3. 환경 설정 (환경 이름 옆 톱니바퀴 → 편집)
**네트워크 접근**: `Custom` 선택 → 기본 허용 목록 포함에 체크 → Allowed domains 칸에
```
cdn.jsdelivr.net
```
(제목 폰트 카페24 오스퀘어, 자막 폰트 G마켓 산스를 받는 주소)

**API credentials** → Add credential 두 번:

| 이름 | Allowed websites | 헤더 Name | Prefix | Value |
|---|---|---|---|---|
| ElevenLabs | api.elevenlabs.io | xi-api-key | (비움) | 일레븐랩스 API 키 |
| OpenAI | api.openai.com | Authorization | Bearer | OpenAI API 키 |

키는 클로드에게도 보이지 않고 안전하게 붙여집니다.
(API credentials 칸이 안 보이면 대신 Environment variables 칸에
`ELEVENLABS_API_KEY=키`, `OPENAI_API_KEY=키` 두 줄을 넣어도 됩니다)

## 4. 매일 쓰는 법
claude.ai/code → korea1278/shorts 새 세션 → **"오늘 팬튜브"** 입력
→ 인물 번호 리스트 → 번호 입력 → 대본 확인 → "진행" → 다운로드 링크로 MP4 받기

## 비용 감
영상 1편(장면 8개) 기준: 이미지 8장(OpenAI 중간 화질) + 나레이션 300자 정도(일레븐랩스 크레딧)
