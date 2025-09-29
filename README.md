# 🤖 Travel Assistant Bot

한국 교통정보 조회 및 알림 서비스

## 🚀 Render.com 배포 가이드

### 1. GitHub 리포지토리 생성
1. GitHub에서 새 리포지토리 생성
2. 이 프로젝트를 GitHub에 업로드

### 2. Render.com 계정 생성
1. **[Render.com](https://render.com)** 접속
2. GitHub 계정으로 로그인

### 3. 새 Web Service 생성
1. Render 대시보드에서 "New +" → "Web Service" 선택
2. GitHub 리포지토리 연결
3. 설정:
   - **Name**: `autoreserve-bot`
   - **Environment**: `Docker`
   - **Plan**: `Free`
   - **Build Command**: 비워두기
   - **Start Command**: `python main2.py`

### 4. 보안 크리덴셜 설정

**⚠️ 중요**: GitHub에는 절대 실제 비밀번호를 올리지 마세요!

#### 🔐 보안 원칙
- **GitHub**: 코드만 업로드 (비밀번호 ❌)
- **Render.com**: 웹 대시보드에서 환경변수 직접 입력

#### 옵션 1: 암호화된 환경변수 (높은 보안)
1. **로컬에서만** 암호화 도구 실행:
   ```bash
   python encrypt_credentials.py --env
   ```
2. 실제 크리덴셜 정보 입력 (로컬에서만!)
3. **출력된 암호화된 값들**을 Render 대시보드에 입력:

   **Render.com Environment 설정**:
   ```
   MASTER_PASSWORD=your_master_password
   USE_ENCRYPTED_ENV=true
   TELEGRAM_BOT_TOKEN_ENC=gAAAAABh...암호화된값
   KORAIL_USER_ENC=gAAAAABh...암호화된값
   KORAIL_PASS_ENC=gAAAAABh...암호화된값
   # ... 기타 모든 암호화된 변수들
   RENDER=true
   ```

#### 옵션 2: 일반 환경변수 (간단한 방법)
**Render.com Environment** 탭에서 직접 입력:
```
TELEGRAM_BOT_TOKEN=실제_봇_토큰
KORAIL_USER=실제_회원번호
KORAIL_PASS=실제_비밀번호
KORAIL_PASS_BANK=실제_카드비밀번호
Card_Num1_korail=실제_카드번호1
Card_Num2_korail=실제_카드번호2
Card_Num3_korail=실제_카드번호3
Card_Num4_korail=실제_카드번호4
Card_Num5_korail=실제_카드비밀번호앞2자리
CARD_MONTH=실제_카드유효월
Id_Num1_korail=실제_주민번호앞6자리
SRT_ID=실제_SRT아이디
SRT_PWD=실제_SRT비밀번호
RENDER=true
```

#### ⚠️ 절대 하지 말 것
- ❌ GitHub에 .env 파일 업로드
- ❌ 코드에 실제 비밀번호 하드코딩
- ❌ credentials.enc 파일을 GitHub에 업로드

### 5. 안전한 배포 프로세스

#### 5-1. GitHub 업로드 (코드만)
```bash
# 민감한 파일이 제외되었는지 확인
git status

# .gitignore 확인 (.env, *.enc 파일이 제외되는지)
cat .gitignore

# GitHub에 코드 업로드
git add .
git commit -m "Add auto-reserve bot with security features"
git push origin main
```

#### 5-2. Render.com에서 환경변수 설정

**📍 Render.com 접속**: https://render.com

1. **Render 대시보드** 접속 → 배포한 서비스 클릭
2. 왼쪽 메뉴에서 **"Environment"** 탭 클릭
3. **"Add Environment Variable"** 버튼 클릭
4. 하나씩 환경변수 추가:

   | Key (변수명) | Value (값) |
   |-------------|------------|
   | `TELEGRAM_BOT_TOKEN` | `1234567890:ABCdef...` (실제 봇 토큰) |
   | `KORAIL_USER` | `01012345678` (실제 코레일 아이디) |
   | `KORAIL_PASS` | `password123` (실제 코레일 비밀번호) |
   | `KORAIL_PASS_BANK` | `123456` (카드 비밀번호 6자리) |
   | `Card_Num1_korail` | `1234` (카드번호 첫4자리) |
   | `Card_Num2_korail` | `5678` (카드번호 둘째4자리) |
   | `Card_Num3_korail` | `9012` (카드번호 셋째4자리) |
   | `Card_Num4_korail` | `3456` (카드번호 넷째4자리) |
   | `Card_Num5_korail` | `12` (카드 비밀번호 앞2자리) |
   | `CARD_MONTH` | `12` (카드 유효월) |
   | `Id_Num1_korail` | `123456` (주민번호 앞6자리) |
   | `SRT_ID` | `srt_userid` (실제 SRT 아이디) |
   | `SRT_PWD` | `srt_password` (실제 SRT 비밀번호) |
   | `RENDER` | `true` |

5. 모든 변수 추가 후 **"Save Changes"** 클릭

⚠️ **주의**: 위 값들은 예시이며, 실제 개인정보를 입력해야 합니다!

#### 5-3. 배포 실행
- "Deploy Latest Commit" 클릭
- 빌드 로그에서 진행상황 확인
- 크리덴셜 로딩 성공 메시지 확인:
  ```
  ✅ 모든 필수 크리덴셜이 설정되었습니다.
  ✓ Korail 로그인 성공
  ✓ SRT 로그인 성공
  ```

## 🔐 보안 설정 (선택사항)

민감한 정보 보호를 위해 암호화 기능을 제공합니다.

### 로컬 개발용 암호화 파일
```bash
python encrypt_credentials.py --file
```
- `credentials.enc` 파일 생성
- 마스터 패스워드만 환경변수에 설정하면 됨
- `.gitignore`에 추가 필수

### 서버 배포용 암호화 환경변수
```bash
python encrypt_credentials.py --env
```
- 각 크리덴셜을 개별 암호화
- 서버에 암호화된 값들을 환경변수로 설정
- `USE_ENCRYPTED_ENV=true` 설정

### 크리덴셜 검증
```bash
python secure_config.py
```
- 현재 설정된 크리덴셜 상태 확인
- 마스킹 처리되어 안전하게 표시

## 📱 사용법

### 기본 명령어
- `/start` - 예매 시작
- `/multi_status` - 다중 모니터링 상태 확인
- `/stop_multi` - 다중 모니터링 중단
- `/add_multi_course` - 다중 코스 사용법 안내

### 다중 모니터링
1. `/start`로 예매 시작
2. 열차 검색 후 "🎯 다중 모니터링" 선택
3. 여러 열차 체크박스로 선택
4. "✅ 선택완료" 클릭

## ⚠️ 주의사항

### Render.com 무료 플랜 제한
- **15분 비활성 시 Sleep**: 요청이 없으면 서비스가 잠들어요
- **750시간/월**: 한 달에 750시간까지 실행 가능
- **빌드 시간**: 매달 500분 제한

### Sleep 방지 방법
1. **UptimeRobot** 등으로 5분마다 핑 전송
2. **Google Apps Script**로 주기적 요청
3. **GitHub Actions**로 자동 핑

## 🔧 트러블슈팅

### 일반적인 문제
1. **Chrome 관련 오류**: Dockerfile의 Chrome 설치 확인
2. **환경변수 오류**: Render 대시보드에서 환경변수 재확인
3. **빌드 실패**: 로그에서 오류 메시지 확인

### 로그 확인
Render 대시보드 → Logs에서 실시간 로그 확인 가능

## 📞 지원

문제가 있으면 이슈를 생성해주세요.