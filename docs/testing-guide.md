# 로컬 테스트 가이드

Grafana를 **직접 호출하지 않고** 저장된 샘플 파일로 파이프라인 전체를 단계별로 검증하는 가이드입니다. 운영 Loki에 영향 없이, 격리된 상태로 반복 실행할 수 있습니다.

## 샘플 파일

프로젝트 루트에 두 개의 Grafana `/api/ds/query` 응답 JSON이 있습니다:

| 파일                  | 로그 수 | 용도                        |
| --------------------- | ------- | --------------------------- |
| `test.json`           | 100줄   | 가볍게 파이프라인 흐름 확인 |
| `grafana_sample.json` | 173줄   | 더 많은 패턴·분류 결과 확인 |

이하 명령은 `grafana_sample.json` 기준이지만, `test.json`으로 바꿔도 동일하게 동작합니다.

## 공통 전제

- `.env` 파일에 `GRAFANA_*`, `GITHUB_TOKEN`, `GITHUB_REPO` 설정 완료
- 대상 레포에 Level 2 세팅까지 끝낸 상태 (Environment, secrets, workflow 커밋 등 — `setup-target-repo.md` 참고)
- shell에 `.env`를 로드한 상태:
  ```bash
  set -a; source .env; set +a
  ```

> ⚠️ **`--input-file` 사용 시 체크포인트(`checkpoint_ms`)는 저장되지 않습니다.** 즉 샘플 파일로 몇 번 돌려도 다음 실제 실행 구간에 영향을 주지 않습니다. 다만 **fingerprint 테이블은 기록**되므로, 매번 완전 초기화하려면 `--state-db /tmp/triage_test.sqlite` 로 격리하세요.

---

## Test 1 — 환경 변수 / API 접근 확인

**목적**: `.env`가 shell에 제대로 로드되고 GitHub API에 접근 가능한지 확인.

**실행**:

```bash
echo "token=[${GITHUB_TOKEN:0:20}...]"
echo "repo=[$GITHUB_REPO]"

curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
     -H "Authorization: Bearer $GITHUB_TOKEN" \
     -H "Accept: application/vnd.github+json" \
     "https://api.github.com/repos/$GITHUB_REPO"
```

**통과 조건**:

- 토큰이 `github_pat_` 로 시작하는 문자열로 보임
- `repo=[V-MoongCheap/MoongCheap-backend]` 형태로 보임
- `HTTP 200` 반환

**실패 시**:

- `401` → PAT 만료 / Org Owner 미승인
- `403` → PAT에 Issues 권한 미부여
- `404` → `GITHUB_REPO` 오타, 또는 `.env` 미로드 (`$GITHUB_TOKEN` 빈 값)
- 토큰이 빈 값으로 보임 → `set -a; source .env; set +a` 다시 실행

---

## Test 2 — Dry-run 파이프라인 (파싱·분류·그룹핑 확인)

**목적**: 외부 쓰기 없이 샘플 파일로 파싱 → 분류 → 그룹핑이 잘 되는지 확인.

**실행**:

```bash
python3 -m src.main \
  --dry-run \
  --input-file grafana_sample.json \
  --state-db /tmp/triage_test.sqlite
```

**통과 조건** (출력 예시):

```
INFO ... 조회 구간 YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM, 173줄
INFO ... [dry-run] GitHub 이슈 생성: [triage][bug] ...
INFO ... 완료: N종 ({'bug': X, 'review': Y, ...})
```

- "173줄" 로 샘플 전부 조회된 것 확인
- 분류 결과(`{'bug': ..., 'review': ..., 'external': ..., 'minor': ..., 'expected': ...}`)가 비어있지 않음
- `[dry-run]` 로그가 실제로는 생성하지 않는다는 뜻 — Issues 탭에는 아무것도 안 만들어짐

**실패 시**:

- `파싱 실패 N줄` 경고 → 로그 포맷이 Classifier 규칙과 안 맞음, `resources/rules.yaml` 조정 필요
- `0줄` → JSON 파싱 자체는 됐으나 라인이 비어있음, 샘플 파일 손상 확인

---

## Test 3 — 실제 이슈 생성 (격리 state DB)

**목적**: 실제로 대상 레포에 이슈가 만들어지는지 + 중복 방지(fingerprint)가 동작하는지 확인.

**사전**: `.env`에서 `AI_MODE=issue` (AI 라벨 안 붙여서 workflow 트리거 안 함 — 가장 안전).

**실행 (첫 번째)**:

```bash
rm -f /tmp/triage_test.sqlite
python3 -m src.main \
  --input-file grafana_sample.json \
  --state-db /tmp/triage_test.sqlite
```

**통과 조건**:

- 대상 레포 **Issues 탭에 `[triage][...]` 이슈가 N개 생성**됨
- 각 이슈에 라벨 부착:
  - `triage-bot`
  - `fp-<hash>` (16자 fingerprint)
  - `triage:bug` / `triage:review` / `triage:external` / `triage:minor` / `triage:expected` 중 하나
- `ai-analyze` / `ai-fix` 라벨은 **안 붙음** (`AI_MODE=issue` 이므로)

**실행 (두 번째 — 중복 방지 확인)**:

```bash
python3 -m src.main \
  --input-file grafana_sample.json \
  --state-db /tmp/triage_test.sqlite
```

**통과 조건**:

- 새 이슈가 **추가로 생기지 않음**
- 기존 이슈에 `📈 최근 구간에 N회 추가 발생 ...` 코멘트가 달릴 수 있음 (설정된 간격 지난 경우)

**실패 시**:

- `401 / 403` → PAT 권한 / Owner 승인 재확인
- `422 Validation Failed` → 레포에 `triage:xxx` 라벨이 미리 없을 수 있음 (GitHub은 자동 생성해주지만, 보호 레포는 예외)
- 중복 이슈가 생기면 state DB가 제대로 저장되지 않은 것 → `/tmp/triage_test.sqlite` 파일 존재 확인

**정리**:

```bash
# 생성된 테스트 이슈 close (수동으로 Issues 탭에서)
# 또는 라벨로 일괄 조회 후 close:
gh issue list --repo "$GITHUB_REPO" --label "triage-bot" --limit 50
```

---

## Test 4 — AI 분석 모드 (`analyze`)

**목적**: 이슈 생성 → `ai-analyze` 라벨 → GitHub Actions workflow 트리거 → 승인 게이트 → Claude 분석 코멘트까지 end-to-end 확인.

**사전 조건**:

- `setup-target-repo.md` Level 2가 모두 끝난 상태
- 대상 레포에 `develop` 브랜치 + `.github/workflows/ai-fix.yml` 존재
- `ai-fix` environment에 `TRIAGE_BOT_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN` secret 등록
- Required reviewers 지정, Prevent self-review 해제

**사전**: `.env`에서 `AI_MODE=analyze`로 변경.

**실행**:

```bash
rm -f /tmp/triage_test.sqlite
python3 -m src.main \
  --input-file grafana_sample.json \
  --state-db /tmp/triage_test.sqlite
```

**통과 조건** (순서대로 확인):

1. **이슈 생성·라벨 부착**
   - Issues 탭에 신규 이슈
   - 라벨에 `ai-analyze` 추가됨 (`bug` 뿐 아니라 `review`도 analyze로)

2. **Workflow 트리거**
   - 대상 레포 **Actions 탭 → "AI fix from triage issue"** workflow run 생성
   - 상태: **"Waiting for review"**

3. **승인 게이트 동작**
   - run 클릭 → **"Review deployments"** 버튼 클릭
   - 이슈 번호·내용 확인 후 **"Approve and deploy"**
   - 실행 시작

4. **Claude 분석 코멘트**
   - 몇 분 후 workflow 성공
   - 해당 이슈에 Claude가 작성한 **분석 코멘트** (원인 가설·근거·수정 방향·확신도) 달림
   - 코드/브랜치/PR은 **아무것도 생성 안 됨** (analyze 모드이므로)

**실패 시**:

| 증상                                 | 원인                                                                              |
| ------------------------------------ | --------------------------------------------------------------------------------- |
| Actions 탭에 workflow run 없음       | yaml이 `.github/workflows/` 경로에 없음, 라벨명 오타, `triage-bot` 라벨 함께 없음 |
| "Waiting for review" 안 걸림         | Environment의 Required reviewers 미설정                                           |
| Approve 후 바로 실패 (checkout 단계) | 대상 레포에 `develop` 브랜치 없음                                                 |
| Claude step 실패 (`authentication`)  | `CLAUDE_CODE_OAUTH_TOKEN` secret 누락·오타·만료                                   |
| `gh issue comment` 실패 (`403`)      | `TRIAGE_BOT_TOKEN`의 Issues 권한 R/W 없음                                         |
| AI 쿼터 초과 메시지                  | `MAX_AI_DISPATCH_PER_DAY=5` 소진, 또는 Claude 구독 사용량 한도                    |

---

## Test 5 — AI 수정 모드 (`fix`, Draft PR 생성)

**목적**: `ai-fix` 라벨 → Claude가 `develop`에서 분기 → 실패 테스트 작성 → 코드 수정 → `./gradlew test` 통과 → Draft PR 생성까지 확인.

**⚠️ 주의**: 이 모드부터는 대상 레포에 **실제 브랜치·PR**이 만들어집니다. 꼭 analyze 모드로 몇 번 돌려 Claude 분석 품질을 확인한 뒤 올리세요.

**사전**: `.env`에서 `AI_MODE=fix`로 변경.

**실행**:

```bash
rm -f /tmp/triage_test.sqlite
python3 -m src.main \
  --input-file grafana_sample.json \
  --state-db /tmp/triage_test.sqlite
```

**통과 조건**:

1. **라벨 분기**
   - `category=bug` 이슈 → `ai-fix` 라벨
   - `category=review` 이슈 → `ai-analyze` 라벨 (수정 대상 아님, 분석만)

2. **Workflow 트리거 + 승인 → Claude 실행**
   - `ai-fix` 라벨 이슈의 workflow run을 **Approve**

3. **AI 수정 작업**
   - 몇 분~20분 소요 (실패 테스트 작성 + 수정 + `./gradlew test`)
   - 수정 금지 경로(`.github/`, `build.gradle*`, `application*.yml` 등) 건드리지 않아야 함

4. **Draft PR 생성**
   - 대상 레포 **Pull requests 탭**에 **Draft PR**
   - Head: `ai-fix/issue-N`, **Base: `develop`**
   - 본문에 원인 / 수정 내용 / 추가 테스트 / 확인 사항 / `Fixes #N` 포함

5. **Guard 단계**
   - Guard 로그에서 "수정 금지 경로 변경 없음" 확인
   - 변경 라인 300+ 이면 ⚠️ 코멘트 자동 추가됨

**실패 시**:

| 증상                                  | 원인                                                        |
| ------------------------------------- | ----------------------------------------------------------- |
| PR 생성 실패 (`gh pr create` 에러)    | `TRIAGE_BOT_TOKEN`의 Pull requests / Contents 권한 미부여   |
| `git push` 실패 (`permission denied`) | 위와 동일 (`Contents: Write` 필요)                          |
| `./gradlew test` 실패                 | Java 버전 불일치, 실제 코드가 테스트 통과 못 함 — 로그 확인 |
| Guard 가 ❌ 실패 처리                 | AI 가 수정 금지 경로 변경 — PR 머지하지 말 것               |
| PR 수정 라인 300+ ⚠️ 경고             | 범위 과도, 수동 리뷰 집중 필요                              |

**정리**:

- 테스트 Draft PR을 수동 리뷰 → 쓸 만하면 Ready for review → 머지, 아니면 Close
- 테스트 브랜치 삭제: `git push origin --delete ai-fix/issue-N`

---

## Test 6 — PR 배관만 검증 (Claude 호출 없이)

**목적**: Claude의 분석/수정 품질이 아니라 **배관**(Environment 승인 게이트 / `TRIAGE_BOT_TOKEN` 권한 / checkout·branch·push·PR 생성 체인)이 올바로 설정됐는지만 반복 검증.

**언제 쓰나**:

- Test 5(fix 모드) 돌리기 전에 PAT·Environment 설정이 맞는지 먼저 확인하고 싶을 때
- 실제 수정 가능한 버그가 로그에 없어서 Test 5를 돌릴 수 없을 때
- 가짜 버그 로그를 심어도 Claude가 "코드 확인 → 멀쩡함"으로 판단해 PR을 안 만드는 문제 회피
- Claude 사용량 소비 없이 반복 테스트하고 싶을 때

**원리**: 별도 라벨(`ai-pr-test`)로 트리거되는 전용 workflow를 하나 더 두고, Claude 호출 없이 README에 공백 한 줄만 추가하는 Draft PR을 생성. 승인 게이트와 PR 생성 권한을 **그대로** 재사용하므로 Test 5와 같은 경로를 검증.

### 사전 — 대상 레포에 전용 workflow 추가

`resources/pr_plumbing_test.yaml` 내용을 **대상 레포**에 커밋:

```
MoongCheap-backend/.github/workflows/pr-plumbing-test.yml
```

**중요 포인트**:

- `environment: ai-fix` → 기존 승인 게이트 그대로 통과 검증
- `GH_TOKEN: TRIAGE_BOT_TOKEN` → org Workflow permissions Read-only 정책 우회 (`ai-fix.yml`과 동일 패턴)
- checkout에 `token: TRIAGE_BOT_TOKEN` 지정 — 기본 `GITHUB_TOKEN`은 org 정책에 막혀 push 실패
- `if`에 `triage-bot` 라벨 조건 없음 → 라벨 하나만으로 바로 트리거
- **반드시 기본 브랜치(main)에 머지** — `labeled` 이벤트는 기본 브랜치의 yaml만 읽음

### 실행

로컬 triage 레포에서:

```bash
set -a; source .env; set +a

# ① 테스트 이슈 생성
ISSUE_URL=$(gh issue create \
  --repo "$GITHUB_REPO" \
  --title "test: PR plumbing dry-run" \
  --body "Workflow 배관(승인 게이트/PAT 권한/PR 생성) 검증용. 완료 후 닫음.")
echo "Issue: $ISSUE_URL"
ISSUE_NUM=$(echo "$ISSUE_URL" | grep -oE '[0-9]+$')

# ② 라벨 부착 → workflow 트리거
gh issue edit "$ISSUE_NUM" --repo "$GITHUB_REPO" --add-label "ai-pr-test"

# ③ Actions 탭에서 "Waiting for review" 상태 확인
gh run list --repo "$GITHUB_REPO" --workflow "PR plumbing test" --limit 1
```

**승인**: GitHub 웹 Actions 탭에서 run 클릭 → **"Review deployments"** → **"Approve and deploy"**.

### 통과 조건

1. **Workflow 트리거** — Actions 탭에 "PR plumbing test" run이 "Waiting for review" 상태
2. **승인 후 성공** — 2분 이내 녹색 체크
3. **브랜치 생성** — 대상 레포에 `pr-test/issue-{N}` 브랜치
4. **Draft PR** — Pull requests 탭에 Draft 상태, base `develop`
5. **이슈 코멘트** — "✅ 배관 테스트 PR 생성 완료" 자동 부착
6. **PR 미머지** — Draft 상태 유지 (자동 머지 안 됨)

### 실패 시

| 걸림 지점                              | 원인                                                                              |
| -------------------------------------- | --------------------------------------------------------------------------------- |
| workflow가 아예 안 뜸                  | yaml이 **main에 머지 안 됨**, 라벨명 오타(`ai-pr-test`)                           |
| "Waiting for review"에서 멈춤          | Environment `ai-fix` Required reviewers 미지정, Prevent self-review 켜짐          |
| checkout 실패 (`could not find ref`)   | 대상 레포에 `develop` 브랜치 없음                                                 |
| `git push` 403 / permission denied     | `TRIAGE_BOT_TOKEN`의 `Contents: Write` 누락, org owner 승인 안 됨                 |
| `gh pr create` 403                     | `TRIAGE_BOT_TOKEN`의 `Pull requests: Write` 누락                                  |
| `gh issue comment` 403                 | `Issues: Write` 누락                                                              |

### 정리

```bash
set -a; source .env; set +a
PR_NUM=$(gh pr list --repo "$GITHUB_REPO" --head "pr-test/issue-${ISSUE_NUM}" --json number -q '.[0].number')

gh pr close "$PR_NUM" --repo "$GITHUB_REPO" --delete-branch
gh issue close "$ISSUE_NUM" --repo "$GITHUB_REPO"
```

workflow 파일(`pr-plumbing-test.yml`)은 **그대로 두어도 무해** — `ai-pr-test` 라벨 안 붙이면 트리거 안 됨. 완전히 제거하려면 대상 레포에서 삭제 커밋 → main 머지.

---

## 전체 테스트 종료 후 정리

```bash
# 격리 state DB 제거
rm -f /tmp/triage_test.sqlite

# .env 원복 (운영 모드로)
#   AI_MODE=issue  (안전 모드로 복귀)
#   또는 운영 설정에 맞게
```

- 생성된 **테스트 이슈 close** (수동 또는 `gh issue close`)
- 생성된 **테스트 PR close + 브랜치 삭제**
- 운영 state DB(`.env`의 `STATE_DB` 또는 기본 경로)에는 **테스트 흔적이 전혀 남지 않습니다** — `--state-db /tmp/triage_test.sqlite` 로 격리했기 때문

---

## 자주 하는 실수

- **`.env` 미로드로 토큰이 빈 값** → private 레포에 대해 404로 나와서 "레포 못 찾음"으로 오해. 반드시 `set -a; source .env; set +a` 선행
- **`python` vs `python3`** → 이 시스템엔 `python` 심볼릭 링크 없음. 항상 `python3 -m src.main` 사용
- **격리 없이 테스트** → 운영 state DB에 테스트 fingerprint가 기록되어 다음 실제 실행 시 "이미 처리됨"으로 스킵됨. 꼭 `--state-db /tmp/...` 사용
- **`AI_MODE=fix` 로 바로 시작** → 품질 검증 없이 PR 쏟아짐. 반드시 `issue → analyze → fix` 순서
- **대상 레포에 `develop` 미생성** → analyze/fix 모드에서 workflow 가 checkout 단계부터 실패
