# 대상 레포 & 로컬 환경 설정 가이드

이 문서는 log-triage 파이썬이 로컬에서 돌면서 **대상(백엔드) 레포에 이슈를 생성**하고, 선택적으로 **AI 워크플로우로 Draft PR까지 자동 생성**하도록 만드는 전체 설정 절차입니다.

## 전체 구조

```
[로컬 노트북]                          [대상 백엔드 레포 (V-MoongCheap/MoongCheap-backend)]
─────────────                          ───────────────────────────────────────────
log-triage 파이썬                      .github/workflows/ai-fix.yml
    │                                        │
    │ GITHUB_TOKEN (local PAT, .env)         │ Environment 'ai-fix' secrets:
    │                                        │  - TRIAGE_BOT_TOKEN (Actions PAT)
    │                                        │  - CLAUDE_CODE_OAUTH_TOKEN
    │                                        │
    │ ① 이슈 생성 + ai-fix/ai-analyze 라벨   │ ② 라벨 이벤트 → 승인 게이트 → Claude 실행
    ▼                                        ▼
POST /issues, /issues/{n}/labels        Draft PR 생성 (base: develop)
```

두 단계로 나뉩니다:
- **Level 1** — 로컬 파이썬이 이슈를 생성하기 위한 최소 준비 (PAT + .env)
- **Level 2** — AI 워크플로우까지 활성화 (yaml 배치 + Environment + Actions용 PAT + Claude OAuth 토큰)

Level 1만 해도 이슈 자동화는 완성됩니다. Level 2는 이후 언제든 추가 가능.

### 왜 PAT 2개 + OAuth 토큰인가

- **로컬 PAT (`GITHUB_TOKEN` in `.env`)**: Python이 이슈 생성용. Issues R/W만 있으면 됨
- **Actions PAT (`TRIAGE_BOT_TOKEN` as env secret)**: workflow 안에서 코드 push·PR 생성·코멘트. **V-MoongCheap org의 Actions permissions가 Read-only로 잠겨있어** 기본 `GITHUB_TOKEN`으로는 PR 생성 불가. PAT를 주입해서 org 제약을 우회함
- **Claude OAuth 토큰 (`CLAUDE_CODE_OAUTH_TOKEN`)**: Anthropic API 유료 결제가 아니라 **Claude Pro/Max 구독 사용량**에서 AI 호출 비용을 깎기 위해 사용

---

## Level 1 — 이슈 생성 (필수)

### 1) 로컬용 Fine-grained PAT 발급

직행 링크: https://github.com/settings/personal-access-tokens/new

| 항목 | 값 |
|---|---|
| Token name | `log-triage-local` (임의) |
| Description | (선택) `Loki 로그 트리아지 봇 - 이슈 생성용` |
| Resource owner | 대상 레포 소유자 (`V-MoongCheap`) |
| Expiration | 90일 권장 (최대 1년까지 커스텀 가능) |

**Repository access**
- `Only select repositories` 선택 (필수)
- 드롭다운에서 **`MoongCheap-backend` 1개만** 선택
- ⚠️ `All repositories`는 절대 선택 금지

**Repository permissions**
| Permission | Access |
|---|---|
| **Issues** | **Read and write** ← 필수 |
| Metadata | Read-only (자동 부여됨) |
| (선택) Pull requests | Read — 이슈에 링크된 PR 상태 조회 시 |
| 나머지 | No access |

**절대 부여하지 말 것**
- `Contents: Write` — 로컬 토큰에는 코드 수정 권한 필요 없음
- `Actions: Write` — 워크플로우 조작 권한
- `Administration: *` — 레포 설정 변경, 위험

**Account permissions**: 전부 No access

`Generate token` 클릭 → 화면에 뜨는 `github_pat_...` 문자열을 **즉시 복사** (한 번만 표시됨).

### 2) Org 소유 레포라면 Owner 승인 대기

Org 레포를 선택했다면 토큰은 발급되지만 **Owner 승인 전까지 401**이 발생합니다.

- Owner에게 자동 이메일 발송
- Owner 승인 페이지: `https://github.com/organizations/V-MoongCheap/settings/personal-access-token-requests`
- 승인 후 별도 알림 없이 즉시 동작

개인 소유 레포는 이 단계 불필요.

### 3) `.env` 업데이트

프로젝트 루트에 `.env` 파일 생성/편집:

```bash
# Grafana (basic auth)
GRAFANA_URL=https://grafana.moongcheap.shop
GRAFANA_USER=triage-viewer
GRAFANA_PASSWORD=***
GRAFANA_DS_UID=P8E80F9AEF21F6940

# Discord (현재 비활성화됨 — src/cli.py 와 workflow 양쪽에서 주석 처리)
# DISCORD_WEBHOOK_URL=

# GitHub (Level 1: 로컬에서 이슈 생성용)
GITHUB_TOKEN=github_pat_생성한값전체
GITHUB_REPO=V-MoongCheap/MoongCheap-backend

# 동작 모드
AI_MODE=issue           # off | issue | analyze | fix
MAX_AI_DISPATCH_PER_DAY=5
```

### 4) 로컬 검증

**API 접근 확인**:
```bash
set -a; source .env; set +a   # .env 를 shell env 로 로드
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
     -H "Accept: application/vnd.github+json" \
     "https://api.github.com/repos/$GITHUB_REPO"
```

정상 응답 = 레포 JSON. 오류별 원인:
- `401`: 토큰이 틀렸거나 org owner 승인 대기 중
- `403`: 권한 부족 (Issues 미부여, 잘못된 레포)
- `404`: `GITHUB_REPO` 경로가 틀렸거나 access에 미포함 **또는 .env 미로드로 변수가 빈 값**

**파이프라인 dry-run**:
```bash
python3 -m src.main --dry-run
```
Grafana 조회 → 파싱 → 분류 → 이슈 생성 dry-run 로그 확인 (실제 이슈 안 만들어짐).

> 참고: dry-run이어도 Grafana 조회(HTTP)와 GitHub GET(이슈 조회)은 실제로 발생합니다. 쓰기 호출(이슈 생성·코멘트·라벨·체크포인트 저장)만 스킵.

### 5) 실제 이슈 생성

```bash
python3 -m src.main
```

대상 레포 Issues 탭에 `[triage][...]` 이슈 생성 + 라벨(`triage-bot`, `fp-...`, `triage:...`) 부착 확인.

**Level 1 완료.** 여기서 멈춰도 로그 트리아지 자동화는 완성됩니다.

---

## Level 2 — AI 워크플로우 (선택)

이 단계는 이슈에 `ai-analyze` / `ai-fix` 라벨이 붙었을 때 Claude가 자동 실행되도록 하는 것입니다. **Claude Pro/Max 구독**을 사용하므로 승인 게이트가 핵심.

### 6) 대상 레포에 `develop` 브랜치 확보

현재 workflow는 **`develop` 브랜치를 기준**으로 동작합니다 (`actions/checkout`의 `ref: develop`, PR의 `--base develop`). 대상 레포에 `develop` 브랜치가 없으면 workflow 첫 단계부터 실패하므로 반드시 먼저 생성:

```bash
# 대상 레포에서
git checkout -b develop
git push -u origin develop
```

### 7) Workflow 파일 배치

`resources/ai_fix.yaml`의 내용을 **대상 레포**에 커밋:

```
MoongCheap-backend/.github/workflows/ai-fix.yml
```

⚠️ 파일명은 반드시 `.github/workflows/` 안에 있어야 GitHub이 워크플로우로 인식합니다. `resources/`, `docs/` 등의 위치에 두면 실행 안 됨.

> 현재 yaml 상태: Discord 알림 블록은 전체 주석 처리됨. Claude 호출은 OAuth 토큰 방식. develop 브랜치 기준.

### 8) Environment 생성 (승인 게이트)

대상 레포 → `Settings` → `Environments` → `New environment`

- **Name**: `ai-fix` (반드시 이 이름 — yaml의 `environment: ai-fix`와 일치해야 함)

**Deployment protection rules**
- ☑ `Required reviewers` → **본인 GitHub 계정** 추가
- `Prevent self-review`는 **끄기** (혼자 승인해야 하므로)
- (선택) `Wait timer` 5분 — 실수 라벨링 시 취소 시간 확보

`Save protection rules` 클릭.

### 9) Actions용 Fine-grained PAT 발급

로컬용 PAT와 **분리해서 발급**합니다 (권한 범위가 다르므로).

https://github.com/settings/personal-access-tokens/new

| 항목 | 값 |
|---|---|
| Token name | `triage-bot-actions` |
| Expiration | 90일~1년 |
| Resource owner | `V-MoongCheap` |
| Repository access | `Only select repositories` → `MoongCheap-backend` |

**Repository permissions** — 다음 3개 모두 **Read and write**:

| Permission | Access | 용도 |
|---|---|---|
| **Contents** | Read and write | AI가 브랜치 push |
| **Pull requests** | Read and write | Draft PR 생성 |
| **Issues** | Read and write | 코멘트, 라벨 조작 |
| Metadata | Read-only (자동) | — |

> 나머지 permission(Actions, Administration 등)은 전부 **No access**.

`Generate token` → `github_pat_...` 즉시 복사.

Org 레포이므로 Owner 승인 필요 (Level 1과 동일).

### 10) Claude Code OAuth 토큰 발급

로컬 터미널에서 Claude Code CLI가 **Pro/Max 구독 계정**으로 로그인된 상태인지 확인:

```bash
claude /status
```

로그인 안 돼 있으면 `claude /login`으로 구독 계정 로그인.

OAuth 토큰 발급:

```bash
claude setup-token
```

- 브라우저 인증 흐름 안내
- 완료되면 터미널에 `sk-ant-oat01-...` 형태의 긴 문자열 출력
- **한 번만 표시되므로 즉시 복사**

### 11) Environment Secrets 등록

대상 레포 `ai-fix` environment → `Environment secrets` → `Add secret`

| Name | Value | 출처 |
|---|---|---|
| `TRIAGE_BOT_TOKEN` | 9에서 발급받은 Actions용 PAT | fine-grained PAT |
| `CLAUDE_CODE_OAUTH_TOKEN` | 10에서 발급받은 OAuth 토큰 | `claude setup-token` |

> ⚠️ **반드시 Environment secrets에 넣을 것** (Repository secrets 아님). Environment에 넣어야 승인 게이트와 함께 묶입니다.

### 12) Actions permissions 설정

대상 레포 → `Settings` → `Actions` → `General`

**Actions permissions**
- `Allow V-MoongCheap, and select non-V-MoongCheap, actions and reusable workflows` 선택
- ☑ `Allow actions created by GitHub`
- ☑ `Allow actions by Marketplace verified creators`
- `Allow specified actions and reusable workflows` 입력란에 **한 줄에 하나씩** 추가:
  ```
  anthropics/claude-code-action@*
  actions/checkout@*
  actions/setup-java@*
  ```

**Workflow permissions**
- **Org 정책이 Read-only로 걸려있어 이 설정은 바꿀 수 없을 수 있음** — 그래도 됩니다. PAT 주입 방식(`TRIAGE_BOT_TOKEN`)이 이 제약을 우회하므로 Org 설정은 Read-only 그대로여도 workflow가 동작합니다.
- 바꿀 수 있다면 `Read and write permissions` + `Allow GitHub Actions to create and approve pull requests` 체크하면 됩니다 (최적).

**Fork pull request workflows from outside collaborators**
- `Require approval for all external contributors` 선택

`Save` 클릭.

### 13) Branch protection (권장)

대상 레포 → `Settings` → `Branches` → `Add branch protection rule`

- Branch name pattern: **`develop`** (workflow가 이 브랜치로 PR 생성하므로)
- ☑ `Require a pull request before merging`
  - `Require approvals`: 1 이상
- ☑ `Do not allow bypassing the above settings`
- `Save changes`

Draft PR이 실수로 머지되지 않도록 최소 방어.

### 14) CODEOWNERS (선택, 워크플로우 파일 보호)

대상 레포 루트에 `CODEOWNERS` 또는 `.github/CODEOWNERS`:

```
.github/workflows/ai-fix.yml  @본인GitHubID
.github/                       @본인GitHubID
```

Branch protection의 `Require review from Code Owners` 옵션도 함께 체크하면, 다른 협업자가 workflow를 몰래 수정 못 함.

### 15) `.env`의 AI_MODE 설정

```bash
# 처음 시작 (분석만, 코드 수정 없음, PR 없음)
AI_MODE=analyze

# 익숙해진 후 (Draft PR 자동 생성까지)
# AI_MODE=fix
```

**반드시 `analyze`로 시작할 것.** Claude가 이슈 원인 분석 코멘트만 남기고, 코드/브랜치/PR 아무것도 안 만듦. 몇 번 돌려보고 결과가 신뢰할 만하면 `fix`로 올림.

### 16) Level 2 검증

**A. 라벨 부착 테스트**
- 대상 레포에서 아무 이슈나 열고 `triage-bot` + `ai-analyze` 라벨 수동 부착
  - (또는 log-triage 실행으로 자동 부착)
- yaml의 `if` 조건이 `triage-bot` 라벨을 요구하므로 반드시 함께 있어야 함
- Actions 탭에서 워크플로우가 **"Waiting for review"** 상태로 대기하는지 확인

**B. 승인 게이트 동작 확인**
- Actions 탭 → 해당 워크플로우 → `Review deployments` 버튼 클릭
- 이슈 내용/라벨 확인 → **Reject**로 취소 테스트
- 워크플로우가 실패로 종료되고 Claude 호출 없이 끝나는지 확인

**C. 실제 실행 확인**
- 다시 라벨 부착 → **Approve** 클릭
- Claude 실행 로그 확인
- 이슈에 코멘트가 달렸는지 확인 (`ai-analyze`인 경우)

**D. AI_MODE=fix로 올릴 때**
- `.env`에서 `AI_MODE=fix` 변경
- `ai-fix` 라벨이 붙은 이슈 → 승인 → Claude가 develop에서 분기 + Draft PR 오픈
- Draft PR을 확인만 하고 절대 자동 머지하지 말 것

---

## 최종 체크리스트

### Level 1 (이슈 생성)
- [ ] 로컬용 Fine-grained PAT 발급 (Issues R/W, `MoongCheap-backend`만)
- [ ] Org owner 승인 (org 레포이므로 필수)
- [ ] `.env`에 `GITHUB_TOKEN` / `GITHUB_REPO` 설정
- [ ] `curl`로 GitHub API 접근 확인
- [ ] `python3 -m src.main --dry-run`으로 파이프라인 검증
- [ ] `python3 -m src.main`으로 실제 이슈 생성 확인

### Level 2 (AI 워크플로우) — 선택
- [ ] 대상 레포에 `develop` 브랜치 생성·push
- [ ] `resources/ai_fix.yaml`을 대상 레포 `.github/workflows/ai-fix.yml`로 커밋
- [ ] Environment `ai-fix` 생성
- [ ] Required reviewers에 본인 지정 (Prevent self-review 해제)
- [ ] Actions용 Fine-grained PAT 발급 (Contents/PR/Issues R/W)
- [ ] Org owner 승인 (Actions용 PAT도 승인 필요)
- [ ] `claude setup-token`으로 OAuth 토큰 발급
- [ ] Environment secrets 등록:
  - [ ] `TRIAGE_BOT_TOKEN` (Actions용 PAT)
  - [ ] `CLAUDE_CODE_OAUTH_TOKEN` (OAuth 토큰)
- [ ] Actions permissions에서 `anthropics/claude-code-action@*` 등 허용
- [ ] Branch protection 규칙 추가 (`develop` 브랜치)
- [ ] (선택) CODEOWNERS로 워크플로우 파일 보호
- [ ] `.env`의 `AI_MODE=analyze`로 시작
- [ ] 라벨 부착 → 승인 게이트 → Reject/Approve 테스트
- [ ] 안정되면 `AI_MODE=fix`로 승격

---

## 트러블슈팅

**401 Unauthorized (로컬 curl / python)**
- PAT 토큰 문자열이 잘렸거나 오타 (반드시 `github_pat_` 접두사 포함)
- Org 레포인데 owner 승인 대기 중
- 토큰 만료
- `.env`를 shell에 로드 안 했음 → `echo "$GITHUB_TOKEN"` 으로 빈 값 확인

**403 Forbidden (로컬 curl / python)**
- Repository permissions에서 `Issues: Read and write` 안 준 상태
- 잘못된 레포에 대해 토큰 발급

**404 Not Found (로컬 curl / python)**
- `GITHUB_REPO` 경로가 틀림 (오타)
- 토큰의 Repository access에 해당 레포가 포함 안 됨
- Private 레포인데 토큰이 빈 값으로 전송(= `.env` 미로드) → 존재 숨김으로 404

**Actions 워크플로우가 트리거 안 됨**
- yaml 파일이 `.github/workflows/` 아래에 있는지 확인
- 이슈에 부착된 라벨명이 정확한지 (`ai-analyze` / `ai-fix`, 대소문자 구분)
- yaml의 `if` 조건에 `triage-bot` 라벨도 함께 있는지 확인
- `develop` 브랜치에 workflow 파일이 머지되어 있는지 (브랜치 분기 되어있다면 각 브랜치별로 존재)

**Environment 승인 게이트가 걸리지 않음**
- yaml의 `jobs.ai` 아래에 `environment: ai-fix` 있는지
- Environment 이름 대소문자/오타 확인
- Required reviewers가 지정됐는지, 지정된 사용자가 본인인지

**Checkout 단계에서 "could not find ref develop" 실패**
- 대상 레포에 `develop` 브랜치가 아직 생성 안 됨
- `git push origin develop` 재확인

**Claude 호출이 "authentication failed" 등으로 실패**
- `CLAUDE_CODE_OAUTH_TOKEN` secret 값이 비어있거나 잘림
- OAuth 토큰이 만료됨 (1년) → `claude setup-token` 재발급 후 secret 갱신
- 발급 시 사용한 Claude 계정이 Pro/Max 구독이 아니거나 비활성 상태

**Claude가 PR 생성에서 "GitHub API 403" 실패**
- `TRIAGE_BOT_TOKEN`에 `Contents: Write` 또는 `Pull requests: Write` 안 줬음
- Org owner가 Actions용 PAT를 승인 안 함
- yaml의 `github_token` 입력이 `${{ secrets.TRIAGE_BOT_TOKEN }}` 으로 올바르게 연결됐는지 확인

**AI 호출 횟수 관련**
- `MAX_AI_DISPATCH_PER_DAY` 값 확인 (`.env` 또는 기본 5)
- log-triage의 `state.dispatches_last_24h()` 카운트가 상한 도달했는지
- Claude Pro/Max 구독의 사용량 한도도 함께 확인 (`claude.ai/settings/usage`)

---

## 참고 링크

- Fine-grained PAT 발급: https://github.com/settings/personal-access-tokens/new
- 발급된 PAT 관리: https://github.com/settings/tokens?type=beta
- Org PAT 승인 요청: https://github.com/organizations/V-MoongCheap/settings/personal-access-token-requests
- Org Actions 설정: https://github.com/organizations/V-MoongCheap/settings/actions
- Environment 문서: https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment
- Actions permissions 문서: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository
- Claude Code OAuth 토큰 발급: `claude setup-token` (CLI 명령)
