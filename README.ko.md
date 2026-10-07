# Remorsearch UX QA

[English](README.md) | 한국어

Remorsearch UX QA는 Claude Code와 Codex용 에이전트 스킬입니다. 이미 있는 제품의 UX를 개선할 때 씁니다.

URL이나 저장소를 주고 개선을 요청하세요. 에이전트는 다음 순서로 작업합니다.

1. 제품과 개발자의 결정을 살펴봅니다.
2. 기본 QA로 질문을 찾습니다.
3. 관련 사용자의 경험을 조사합니다.
4. 되돌릴 수 있는 범위 안에서 수정합니다.
5. 영향을 받은 작업을 다시 실행해 수정을 확인합니다.

문제 목록, 페르소나, 리서치 브리프는 없어도 됩니다.

## 구성 요소

에이전트가 요청마다 필요한 구성 요소를 고릅니다. 모드는 직접 고르지 않습니다. 리서치나 리뷰만 요청하면 제품을 바꾸지 않습니다.

| 구성 요소 | 하는 일 | 필요한 것 |
| --- | --- | --- |
| **research** | 커뮤니티, 리뷰, 공식 출처에서 사용자 경험, 우회 방법, 반례를 찾습니다. 출처 맥락과 빈 곳을 함께 남깁니다. | 허용된 출처. YouTube 댓글은 본인의 YouTube Data API 키. |
| **persona-qa** | 실제 제품에서 작업 완료, 입력 보존, 오류 복구, 키보드 사용, 접근성을 시험합니다. 합성 시험 조건을 씁니다. | 제품 접근 권한과 안전한 시험 데이터. 웹 드라이버에는 Node.js 22와 Playwright가 필요합니다. |
| **ergonomics** (실험) | 가상 프로필로 도달, 터치, 지각, 시간, 레이아웃을 선별 점검합니다. | 해당 시나리오. |
| **loop** | 수정 내역을 기록합니다. 현재 빌드를 다시 실행해 회귀와 의도 변경을 확인합니다. | 호스트 에이전트의 브라우저와 Figma 도구. |

## 설치

Python 도구는 macOS, Linux, WSL의 Python 3.10 이상에서 표준 라이브러리만 씁니다.

1. 저장소를 내려받습니다.

   ```sh
   git clone https://github.com/remorser58/remorsearch.git
   ```

2. 스킬 폴더를 에이전트의 스킬 디렉터리에 복사합니다.

   Claude Code(개인용):

   ```sh
   mkdir -p ~/.claude/skills
   cp -R remorsearch/skills/remorsearch-ux-qa ~/.claude/skills/
   ```

   팀과 함께 쓰려면 프로젝트의 `.claude/skills/`에 복사합니다.

   Codex:

   ```sh
   mkdir -p ~/.codex/skills
   cp -R remorsearch/skills/remorsearch-ux-qa ~/.codex/skills/
   ```

3. 선택: 실제 웹 페이지를 시험하는 웹 드라이버를 설치합니다. persona-qa와 ergonomics가 씁니다. Node.js 22를 쓰세요.

   ```sh
   cd ~/.claude/skills/remorsearch-ux-qa/drivers/web
   npm ci && npx playwright install chromium
   ```

   Codex에서는 `~/.codex/skills/remorsearch-ux-qa/drivers/web`을 씁니다.

## 사용법

평소 말로 요청하거나 스킬 이름으로 부릅니다.

```
/remorsearch-ux-qa Improve our app UX. URL: https://app.example.test or repository: /path/to/product
/remorsearch-ux-qa 우리 앱 UX 개선해줘. URL 또는 저장소는 여기야.
/remorsearch-ux-qa Find out why people abandon our checkout, from reviews and community posts.
/remorsearch-ux-qa 결제 화면을 처음 쓰는 사용자 페르소나로 QA해 줘. Figma 파일은 이거야.
/remorsearch-ux-qa Check one-handed and colour-blind usability of the signup flow on a Galaxy S24.
```

에이전트는 제품과 프로젝트 문서에서 작업, 질문, 시나리오를 찾습니다. 없는 접근 권한과 정해지지 않은 결정만 묻습니다. 기다리는 동안 다른 작업을 계속합니다.

## 근거 규칙

- 모든 진술에 `observed`, `inferred`, `unknown` 중 하나를 붙입니다. 반복해도 추론은 사실이 되지 않습니다.
- 합성 페르소나와 가상 프로필은 시험 조건만 만듭니다. 실제 사용자의 선호나 불편을 보여 주지 않습니다.
- 커뮤니티 신호는 실제 제품에서 확인하기 전까지 가설입니다.
- 리서치와 리뷰 요청은 읽기 전용입니다. 개선 요청은 그 범위 안의 일반적이고 되돌릴 수 있는 수정을 허용합니다. 배포, 게시, 실제 계정 변경은 따로 허락을 받아야 합니다.
- 화면과 UX 변경은 Figma에서 먼저 만듭니다. 파일, 노드, 버전을 기록합니다.
- 개선은 현재 빌드 재실행, 인접 회귀 확인, 의도 확인을 마쳐야 완료됩니다.

리서치와 QA 실행은 기계가 읽는 근거 번들(`schemas/ux-evidence-bundle.v1.schema.json`)을 주고받습니다. 오프라인 검증기는 ID, 상호 참조, 권한 기록, 합성 페르소나 오용을 검사합니다. 예시 번들로 시험하려면 다음을 실행합니다.

```sh
python3 ~/.claude/skills/remorsearch-ux-qa/scripts/validate_bundle.py ~/.claude/skills/remorsearch-ux-qa/examples/bundle/minimal.json
```

## 공개 출처

리서치 단계는 계정 없이 볼 수 있는 페이지만 읽습니다.

- 호스트에 있는 가장 좋은 브라우저 도구를 씁니다. 순서는 에이전트형 브라우저(Aside, Claude in Chrome, Claude 앱 내장 브라우저), 자동화 브라우저, 스킬에 든 리더입니다. 일반 웹 검색 결과는 단서로만 씁니다.
- 리더는 로그인, 유료 장벽, CAPTCHA, 봇 차단, robots.txt, AI·TDM 거부, 속도 제한에서 멈춥니다. 각각을 수집 공백으로 기록합니다.
- 리더는 신분을 숨기지 않습니다. 호스트마다 한 번에 한 페이지를, 8초 이상 간격으로 읽습니다.
- 에이전트가 읽기 전에 전화번호, 이메일 주소, 식별번호, 카드·계좌번호, IP 주소를 지웁니다. 인용은 짧게 합니다. 작성자 이름은 솔트 키로 바꿉니다.
- 약관이 자동 수집이나 AI 이용을 제한하는 호스트에서는 멈춥니다. 그런 호스트를 읽으려면 본인의 약관 확인과 필요한 서면 허락을 기록해야 합니다.

자세한 내용은 [`public-page-access.md`](skills/remorsearch-ux-qa/references/research/public-page-access.md)를 보세요.

## 한국어 리서치

한국 제품, 한국어 사용자, 한국어 보고서에는 한국어 팩을 함께 씁니다. 시작점은 [`overview.md`](skills/remorsearch-ux-qa/references/research/korea/overview.md)입니다. 팩에는 다음이 있습니다.

- 한국 채널 27곳의 접근 경로, 예상 중단 지점, 약관 상태
- 한국어 검색어 작성법과 사용자 언어(초성체, 반어, 말투)
- 협찬·리뷰 보상 표시와 그 등급 규칙
- 법률 체크리스트(법률 자문 아님)와 한국어 보고서 양식
- persona-qa용 KWCAG 2.2·WCAG 2.2 노트: [`kwcag-2.2.md`](skills/remorsearch-ux-qa/references/persona-qa/kwcag-2.2.md)

YouTube 댓글은 YouTube Data API로만 가져옵니다. 키는 환경 변수 `REMORSEARCH_YOUTUBE_API_KEY`에 넣습니다. 키 소유자는 YouTube API 약관을 지켜야 합니다.

## 한계

- 실시간 브라우저, Figma, 빌드는 호스트 에이전트가 제공합니다. loop CLI는 그 기록을 가져올 뿐 직접 실행하지 않습니다.
- 웹 드라이버는 Chromium 기기 에뮬레이션을 씁니다. iOS Safari, 네이티브 앱, 실제 기기는 시험하지 않습니다.
- ergonomics 모드는 실험 기능입니다. 결과는 인증이 아니라 선별용으로 쓰세요.
- 일부 사이트는 리더를 막습니다. 그런 사이트는 수집 공백으로 남습니다.

## 저장소 구성

```
.claude-plugin/                플러그인 매니페스트
skills/remorsearch-ux-qa/      스킬 본체(이 폴더를 복사합니다)
  SKILL.md                     진입점: 모드, 공통 규칙, 도구
  references/                  작업 절차와 참조 자료
  scripts/                     CLI: validate_bundle, ux_loop, ux_research, ergo_qa
  uxloop/ uxresearch/ ergoqa/  CLI용 Python 패키지
  schemas/                     CLI용 JSON 스키마
  drivers/web/                 실시간 Playwright 드라이버(Node.js)
  examples/                    합성 예제
README.md, README.ko.md        영어·한국어 안내
```

## 라이선스

MIT. [`LICENSE`](LICENSE)를 보세요. 제3자 자료는 [`THIRD_PARTY_NOTICES.md`](skills/remorsearch-ux-qa/THIRD_PARTY_NOTICES.md)에 있습니다.

## 출처

공개 페이지 리더와 리서치 게이트는 fivetaku의 [insane-search](https://github.com/fivetaku/insane-search)와 [insane-research](https://github.com/fivetaku/insane-research)(둘 다 MIT)에서 아이디어를 얻었습니다. 스킬에는 insane-search 원본 도구가 참조 자료로 들어 있습니다. 원본 바이트, 출처 기록, 원 라이선스는 그대로 둡니다. 리서치 게이트에는 insane-research의 코드나 문장이 들어 있지 않습니다.

한국어 팩과 이 README의 이중 언어 구성은 [K-skill](https://github.com/NomaDamas/k-skill)(MIT), DaleSeo의 [korean-skills](https://github.com/DaleSeo/korean-skills)(MIT), [SoDam-Persona-Codex](https://github.com/sodam-ai/SoDam-Persona-Codex)(Apache-2.0), fivetaku의 [gptaku_plugins](https://github.com/fivetaku/gptaku_plugins)(MIT)에서 아이디어를 얻었습니다. 아이디어만 참고했습니다.

플랫폼 이름은 설명용입니다. 해당 플랫폼과 제휴 관계는 없습니다.
