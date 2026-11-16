# Render 무료 + Supabase 무료 배포 안내

현재 단계: PostgreSQL용 서버와 Render 설정 준비 완료. 로컬 PostgreSQL에서 8개 테스트 통과. 실제 계정 연결/공개 HTTPS 배포 전입니다. 이전 OPERATIONS.md의 SQLite 배포 안내보다 이 문서가 우선합니다.

## 1. 가입 (현재 할 일)

- Render: https://dashboard.render.com/register
- Supabase: https://supabase.com/dashboard/sign-up
- 두 곳 모두 무료로 시작합니다. 유료 업그레이드나 카드 입력이 나오면 진행하지 않고 화면 내용을 확인합니다.
- GitHub로 가입하면 추후 소스 저장소 연결이 편리합니다. 배포용 소스를 본인 GitHub 저장소에 올리고 Render가 읽을 수 있게 연결해야 합니다. 아직 저장소는 생성/연결하지 않았습니다.

비밀번호, 카드 정보, DATABASE_URL을 채팅이나 공개 저장소에 붙이지 마세요.

## 2. Supabase 무료 프로젝트

1. New project에서 무료 조직/프로젝트를 만듭니다. 행사 프로젝트임을 알 수 있는 이름을 사용합니다.
2. 데이터베이스 비밀번호를 비밀번호 관리자에 저장합니다. 가능한 가까운 지역을 고르되 실제 지원 목록에서 선택합니다.
3. SQL Editor에서 `supabase-schema.sql` 전체를 실행합니다. 데이터가 없는 접수 마감 상태로 생성됩니다. 가짜 접수는 넣지 않습니다.
4. Connect에서 PostgreSQL **Transaction pooler** URI를 선택합니다. IPv4 연결을 지원하는 `pooler.supabase.com:6543` 주소를 사용합니다.
5. URI의 비밀번호 자리만 실제 비밀번호로 바꿉니다. 특수 문자는 URI percent encoding이 필요합니다. 이 값은 Render의 DATABASE_URL 환경변수에만 입력합니다.

`raffle` 스키마는 공개 Data API에 추가하지 않습니다. 모든 테이블에 RLS가 켜져 있고 브라우저용 접근 정책은 없습니다. 브라우저에는 Supabase 키/DB 주소/전화번호 중복 확인값을 전달하지 않습니다. 서버는 데이터베이스 소유자 연결로 접근합니다.

## 3. Render 무료 서버

1. 이 소스를 본인 GitHub 저장소에 올립니다. `.env`, 접속 정보, 운영 DB, `.venv`는 올리지 않습니다. ZIP을 저장소 루트에 풀어 `server.py`, `render.yaml`이 루트에 오도록 합니다.
2. Render에서 저장소 연결 후 Blueprint를 선택하면 `render.yaml`을 사용합니다. 또는 Web Service → Python → Free를 선택합니다.
3. Build: `pip install -r requirements.txt`, Start: `python server.py`, Health check: `/health`.
4. 비밀 환경변수에 DATABASE_URL과 ADMIN_PASSWORD(16자 이상)를 넣습니다. PHONE_HMAC_KEY는 Blueprint가 무작위로 생성합니다. 수동 설정이라면 충분히 무작위인 32자 이상의 값으로 생성합니다.
5. Render가 지정한 **실제** `https://…onrender.com` 주소를 PUBLIC_ORIGIN에 경로와 끝 슬래시 없이 입력합니다. 주소를 확인하기 전 임의 주소를 QR에 쓰지 않습니다.
6. 배포하고 상태가 정상인지 확인합니다. DB 연결이 실패하면 서버는 실행을 거절합니다. 데이터를 잃을 수 있는 임시 SQLite로 자동 대체하지 않습니다.
7. 행사 중 자동 배포를 끕니다. Render Blueprint의 autoDeployTrigger는 off로 준비했습니다.

프로젝트 생성/계정 인증/결제가 필요한 화면은 사용자가 직접 처리합니다. 현재 자동으로 Render나 Supabase 계정을 조작하는 연결은 없습니다.

## 4. 실제 사이트 검증

- Supabase 무료 프로젝트가 paused 상태가 아닌지 확인합니다. 무료 한도/절전 조건은 각 대시보드의 현재 안내를 따릅니다.
- 휴대폰에서 실제 HTTPS 주소 접속 → 접수 안내와 동의 체크 확인.
- 리허설은 별도 Supabase 프로젝트나 분리된 데이터베이스와 별도 Render 서비스에서 합니다. 본 행사 DB와 섞지 않습니다.
- 실제 모바일 2~3대에서 중복 번호와 마감 확인, 빔 화면 인원 갱신 확인.
- 운영자 로그인이 없으면 `/display`, `/api/admin/state`, `/qr.png` 접근 차단 확인.
- 서버 재시작 후 접수/당첨 결과 복원 확인. 이 검증은 실제 배포 후 수행해야 합니다.
- 본 행사 DB가 0명인지 확인한 후 `/admin`에서 로그인 → 상품 설정 → `/display` 열기 → QR PNG 저장.
- 4등→3등→2등→1등 순으로 접수 마감 후 추첨. 같은 등수 결과는 유지됩니다.

Render 무료 서버는 15분간 요청이 없으면 절전될 수 있으므로 행사 전에 직접 접속해 정상 상태를 확인합니다. 무료 서비스에는 응답 지연이나 가용성 제한이 있을 수 있습니다. 행사 중에는 빔 화면을 연결하고, 접속 경고가 나오면 실행을 멈추고 복구합니다.

## 개인정보 및 종료

전체 휴대폰 번호는 DB에 저장하지 않습니다. 표준화 후 HMAC 중복 확인값·끝 4자리·별명·응모번호·접수증 토큰 해시를 저장합니다. 접수증을 받은 휴대폰은 접수 상태 폴링을 중지하도록 수정했습니다. 관리자/빔 화면만 최신 인원을 확인합니다.

운영자 암호는 Render의 서버 환경변수에만 저장하며 클라이언트로 전송하지 않습니다. 필요하면 ADMIN_PASSWORD 대신 미리 계산한 ADMIN_PASSWORD_HASH를 사용할 수 있습니다. DB 비밀번호나 HMAC 키를 행사 도중 바꾸지 마세요.

행사 종료 후 당첨자 확인이 끝나면 Supabase 프로젝트와 Render 서비스를 삭제할 수 있습니다. 무료 DB는 한 시간이 지나면 자동 삭제되는 방식이 아니므로 직접 삭제해야 합니다.

## 검증 근거

- SQLite 회귀 테스트 7개
- 로컬 PostgreSQL 17에서 테스트 8개: 동시 접수 150건, 중복 경쟁 40건, 마감 경쟁, 4등수 총 12명 중복 방지, 동일 등수 12개 동시 실행 결과 유지, 접수증 복구, HTTP 인증/CSRF/QR 접근, 공개 역할 권한 차단
- 테스트는 localhost의 별도 임시 DB를 매번 만들고 제거합니다. 운영 URL을 테스트에 사용하지 않습니다.
- 실제 Supabase/Render TLS 연결, 공개 URL, 외부 휴대폰·빔·브라우저 애니메이션, 로고 원본 파일 반영은 아직 미검증입니다.

공식 참고: https://render.com/docs/free , https://render.com/docs/blueprint-spec , https://supabase.com/docs/guides/database/connecting-to-postgres
