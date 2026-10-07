# 한국어 검색어와 사용자 언어 읽기

항목 조회용 문서입니다. 전체 읽기는 기본 경로에 포함하지 않습니다. 스킬 폴더에서 `python3 scripts/ref.py references/research/korea/query-craft.md 4`로 필요한 ID만 조회합니다.

이 문서는 한국 채널에서 검색어를 짜는 방법과 한국 사용자가 쓴 글을 읽는 규칙을 적습니다. 영문 기본 규칙은
`references/research/research-protocol.md`의 Query expansion, Capture record, What not to infer 절과
`references/research/evidence-classification.md`, `references/research/source-grading.md`를 따릅니다. 발견과 읽기
계약은 `references/research/public-page-access.md` 5절(중단 유형), 7절(금지), 11절(발견)을 따릅니다. 한국 리서치 팩의
흐름은 `references/research/korea/overview.md`에서 시작합니다.

이 문서의 어떤 규칙도 중단을 넘는 방법이 아닙니다. 검색어를 바꿔 멈춘 페이지를 다른 곳에서 찾지 않습니다. 멈춘
페이지는 수집 공백으로 보고서에 남깁니다.

## 확인일과 확인 표시

확인일은 2026-09-29입니다. 사실에는 아래 표시와 출처 번호([Q01] 등, 11절)를 붙입니다. 표시는
`references/research/korea/promotion.md`, `references/research/korea/platform-map.md`,
`references/research/korea/statistics.md`와 같습니다.

| 표시 | 뜻 |
| --- | --- |
| 관찰됨 | 1차 출처를 직접 열어 읽거나 직접 계산해 확인함 |
| 미확인(요약) | 검색 결과 요약이나 보도로만 봄. 원문을 열지 못함 |
| 추론 | 위 사실에서 이 스킬이 끌어낸 판단. 검증되지 않은 설계 규칙 포함 |
| 규칙 | 이 스킬의 규칙 |

이번에 쓰면서 국립국어원, 우리말샘, 위키백과, 학술 논문 누리집, 네이버 도움말은 네트워크 정책 때문에 열리지
않았습니다. 그래서 말뜻과 유래는 대부분 미확인(요약)입니다. 이 문서의 말뜻을 근거로 쓰지 말고, 이번 실행의 글에서
예문을 찾아 용어집에 적습니다(4절).

## 1. 언어 원칙

- 한국 제품은 한국어로 먼저 검색하고, 사용자가 실제로 쓰는 영어 표현을 그다음에 씀. 영어 검색어를 한국어로
  직역하지 않음. — 규칙
- 브랜드는 한글, 영문, 줄임말(예: 카톡, 카뱅, 당근)로 검색하고, 이번 실행의 글에서 본 오타와 변형 표기를 더함.
  줄임말과 변형 표기는 글에서 본 것만 씀. — 규칙
- 축마다 서로 다른 검색어를 8개 이상 돌리고, 모든 검색을 실행의 검색 예산(기본 120)에서 셈
  (`references/research/research-protocol.md`, `references/research/audience-pipeline.md`). — 규칙
- 이 문서의 씨앗 단어와 예시는 후보일 뿐임. 이번 실행에서 읽은 글에 나온 말만 용어집에 남김. — 규칙

## 2. 검색 도구와 연산자

- 발견은 에이전트 자신의 검색 도구(호스트가 주는 웹 검색 등)로 함. 검색 결과의 제목과 요약은 단서(D)이며,
  페이지를 reader(`scripts/ux_research.py read`)로 읽어야 근거가 됨(`references/research/public-page-access.md`
  11절). — 규칙
- 검색 결과 페이지(포털 통합검색, 웹 검색 결과)는 읽지 않음. `read`, `robots`, `ingest`는 이런 URL을 exit 2로
  거절하고, 리디렉션 중에 만나면 범위 밖 중단으로 기록함(`uxresearch/data/routes.json`의 `search_pages`). — 규칙
- 네이버 검색 API, NAVER API HUB, 네이버 데이터랩, 카카오 다음 검색 API는 소유자가 현행 약관을 읽기 전까지 꺼 둠.
  유튜브 검색 API 경로도 이번 판에는 쓰지 않음. 이 문서의 검색어 규칙은 이 경로들을 켜는 근거가 아님
  (`uxresearch/data/routes.json`의 `discovery`). — 규칙
- 연산자는 검색 도구마다 다름. 쓰기 전에 그 도구의 문서나 작은 시험 검색으로 확인함. — 규칙
  - 네이버 통합검색의 연산자는 사용자 안내 글에 따르면 공백(모두 포함), |(하나 이상 포함), 큰따옴표(정확히 일치),
    +(반드시 포함), -(제외)임. site:가 된다는 안내 글도 있으나 네이버 문서로 확인하지 못했고, before:와 after:는
    확인하지 못함. — 미확인(요약) [Q01]
  - 이 스킬은 네이버 검색 결과 페이지를 열지 않으므로, 위 연산자는 쓰는 검색 도구가 같은 문법을 받을 때만 참고함.
    — 규칙
  - 날짜는 연산자 대신 검색어 안에 넣음: 연도, 버전, "업데이트 후", "개편 후". — 규칙
- 전역 웹 검색 도구는 네이버 블로그와 카페 글을 적게 잡을 수 있음. 결과가 없다고 논의가 없다는 뜻이 아님. —
  미확인(출처 없는 설계 가정). 네이버가 robots.txt로 AI 학습·검색 크롤러를 막는다는 보도는
  `references/research/korea/platform-map.md`에 있음. 2026-09-30 직접 읽은 robots 관찰도 그 문서에 적었으며 현재 실행의 판정은 별도로 함 — 관찰됨, 과거 보도는 미확인(요약)
- 검색 결과가 약관 제한 호스트(`uxresearch/data/routes.json`의 `terms_restricted`)를 가리키면 reader는 요청 전에
  멈춤. `lift_requires`가 해제를 허용하는 항목은 사용자가 그 항목의 약관 문서를 직접 읽고 `access_policy.terms_checked`에
  `result: permits_this_reading`으로 적은 실행에서만 풀림. `lift_requires: written_permission`이면 운영사의 사전
  서면 허락을 `permission {granted_by, granted_on, reference}`에 함께 적어야 함. `host`는 항목의 호스트이거나 더
  좁고 읽을 URL을 포함해야 함. `checked_on`은 `effective_from`이 있으면 그날 이후이며 오늘 기준 365일 이내여야 하고
  미래 날짜는 무효임. 한 URL에 걸린 항목은 각각 별도 확인으로 모두 풀어야 함. 풀린 항목은 모든 호스트를 합쳐
  실행당 문서 10건까지 읽음. `status`는 근거 상태임. `lift_requires: never`는 풀 수 없고 `terms_check`는 사용자 확인이 필요함. 에이전트는 확인 항목을 쓰지 않음. — 규칙
- X 페이지와 oEmbed는 `x-terms`에 걸리며 서면 허락을 포함한 확인으로 풀리기 전에는 모두 멈춤. `official_route`는
  null임. naver.me, me2.do, coupa.ng, t.co 같은 짧은 주소도 요청 전에 멈춤. 네이버 카페 공지 원문 주소는 기록되어 있으며 공지와 네이버 이용약관은 각각 별도 확인과 사전 서면 허락이 필요함. 해제 조건은 `references/research/public-page-access.md` 17.1절을 따름(2026-10-01). — 규칙
- 봇 차단(`bot_filter`)과 브라우저 확인 화면(`js_check`)은 `opted_out`이며 등록 도메인 전체를 이번 실행에서 멈춤.
  robots.txt 자리에 확인 화면이 와도 같음. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를
  기다리지 않음. 확인 화면 표지가 있거나 `waited_ms`가 0보다 큰 캡처는 `ingest`가 받지 않음. — 규칙
- 유튜브 영상 주소는 사용자 본인 키로 부르는 Data API로만 읽음. 키 보유자는 YouTube API 약관과 개발자 정책을 따름.
  승인 없이 API Data로 새 데이터·파생 데이터·지표를 만드는 제한은 미확인(요약)이며 적용은 법률가 판단임. 그동안
  API 항목은 정성 근거(풀어 쓰기, 짧은 인용의 존재 근거)로만 쓰고 감정·분류·개수 지표를 계산하지 않음. 이 자료를
  용어집의 극성 분류나 집계에 넣지 않음(`references/research/korea/legal-checklist.md` L17). — 규칙
- 비공개 채널이나 약관 제한으로 멈춘 호스트의 글은 검색 결과의 요약문으로 대신하지 않음. 요약문은 단서로만 남기고
  그 호스트를 수집 공백으로 적음. 같은 글을 다른 호스트, 미러, 캐시, 보관소, 앱에서 찾지 않음
  (`references/research/public-page-access.md` 7절). — 규칙
- 아카이브, 번역·리더 프록시, AMP 캐시, 대체 프런트엔드 같은 제3자 사본은 `third_party_copy`로 거절함.
  브리프가 허용한 제품 공식 페이지의 과거 웨이백 사본만 예외임. — 규칙

## 3. 씨앗 단어(후보)

아래 목록은 검색어를 넓히는 후보입니다. 첫 검색을 돌린 뒤, 읽은 글에 실제로 나온 말만 용어집(4절)에 남기고 나오지
않은 씨앗은 버립니다. 씨앗 단어가 글에 나왔다고 작성자가 그 집단에 속한다는 뜻은 아닙니다(5.6절).

| 계열 | 씨앗 단어(후보) | 쓰는 곳 |
| --- | --- | --- |
| 불편·실패 | 불편, 오류, 안 됨, 먹통, 튕김, 렉, 무한 로딩, 버벅, 안 눌려요, 씹혀요 | 불편 지점 찾기 |
| 결과 | 포기, 결국, 다시, 해지, 탈퇴, 환불, 갈아탐, 고객센터, 상담원 연결 | 불편이 낳은 행동 |
| 버전 | 업데이트 후, 개편, 예전 UI | 시간 구간 나누기(6절) |
| 사용 맥락 | 부모님, 어르신, 엄마, 아빠, 보호자, 육아, 아이 키우는, 아이랑, 직장인, 출퇴근, 대학생, 수험생, 자영업, 사장님, 초보, 처음, 노안, 큰 글씨, 색약, 한 손, 운전 중, 지하철 | 누가 어떤 상황에서 말하는지 보는 단서 |
| 한국형 흐름 | 본인인증 안 됨, 휴대폰 인증, 공동인증서, 간편인증, 카톡으로 열면, 인앱 브라우저, 앱 설치 강요 | 한국 서비스에 흔한 단계 |
| 반대 근거 검색 | 편해요, 만족, 문제없음, 잘 돼요, 괜찮아요, 추천해요 | 반대 경험 찾기 |

- 사용 맥락 씨앗은 누가 말하는지 보여 줄 수 있는 단서일 뿐, 세그먼트 비율을 재지 않음
  (`references/research/source-grading.md` 4절). — 규칙
- 돌봄에 관한 검색은 엄마, 아빠, 보호자, 육아, 아이 키우는을 함께 넣음. 돌보는 사람을 한쪽 성별로 가정하지 않음.
  — 규칙
- 노안, 색약처럼 건강·장애에 닿는 말은 세그먼트 수준 주장에만 쓰고, 작성자 키에 붙이지 않음
  (`references/research/workflow.md`의 Non-negotiable operating rules). 스스로 밝힌 상태는 상태의 비율이 아님. — 규칙
- 반대 근거 검색어는 같은 제품, 기능, 기간으로 좁혀 씀(`references/research/source-grading.md` 6절). — 규칙
- 조합 예: "[제품] 본인인증 안 됨", "[제품] 업데이트 후 튕김 2026", "[제품] 부모님 큰 글씨", "[제품] 육아 중 한 손",
  "[제품] 편해요". — 규칙

## 4. 실행 용어집

실행마다 런 폴더에 용어집 파일 `lexicon.json`을 새로 만듭니다(런 폴더는
`references/research/public-page-access.md` 13절). 말뜻은 시간과 커뮤니티에 따라 바뀌므로 다른 실행의 용어집을
그대로 믿지 않습니다. 용어집은 에이전트가 직접 쓰며, 이를 검사하는 명령은 없습니다.

```json
{
  "run_id": "2026-09-29-example",
  "created_on": "2026-09-29",
  "entries": [
    {
      "term": "먹통",
      "variants": ["먹통됨", "먹통이에요"],
      "meaning": "앱이나 기능이 반응하지 않음",
      "example_source_id": "SRC-1a2b3c4d",
      "first_seen": "2026-09-29",
      "channel": "google-play-kr",
      "dictionary_check": "found",
      "polarity": "negative"
    }
  ]
}
```

| 필드 | 뜻 |
| --- | --- |
| `term` | 글에 나온 말. NFC로 적음(5.8절) |
| `variants` | 이번 실행에서 본 변형 표기. 원래 표기 그대로 적음 |
| `meaning` | 이번 실행의 예문으로 뒷받침되는 뜻. 예문이 없으면 "모름" |
| `example_source_id` | 뜻을 뒷받침하는 예문의 출처 ID. 예문 원문, URL, 닉네임은 적지 않음 |
| `first_seen` | 이번 실행에서 처음 본 날(ISO 날짜) |
| `channel` | 그 말을 본 채널의 id(`references/research/korea/platform-map.md`의 id) |
| `dictionary_check` | 우리말샘 확인 결과: `found`, `not_found`, `not_checked` |
| `polarity` | 말의 극성: `positive`, `negative`, `neutral`, `unknown`(5.1절, 5.5절) |

- 문맥으로 뜻을 확인한 뒤 모호할 때 우리말샘(https://opendict.korean.go.kr/main)을 선택적으로 조회함. 조회하지 않으면 dictionary_check는 not_checked로 적음. 우리말샘은 국립국어원의 개방형
  사전으로, 사용자가 올린 표제어를 전문가가 감수하며, 신어·방언·생활어가 많이 실림. 표제어는 약 120만 개로 소개됨. —
  미확인(요약) [Q02]
- 사전에 올라 있어도 표준어 인정이나 사용 빈도를 뜻하지 않음. 국립국어원은 신어 자료집에 실린 말이라고 표준어로
  인정하거나 사용을 권장한다는 뜻은 아니라고 밝힘. — 미확인(요약) [Q03]
- 모델은 이번 실행의 글에 예문이 없는 은어의 뜻을 단정하지 않음. 예문이 없으면 뜻을 "모름"으로 두고, 그 말에 기댄
  주장은 미확인으로 둠. — 규칙
- 용어집에는 말만 적음. 이름, 닉네임, 연락처, URL을 적지 않음. — 규칙

## 5. 사용자 언어 읽기

### 5.1 초성체

- 초성체는 낱말의 첫 자음만 적는 표기임(예: ㅇㅈ, ㄱㅅ, ㅊㅅㅊ). 웃음소리 표기에서 시작해 PC 통신 채팅과 함께
  퍼졌고, 한 문자열이 여러 말로 읽힐 수 있다고 설명됨. — 미확인(요약) [Q04]
- 초성체는 원문 그대로 둠. 같은 스레드에 뜻을 뒷받침하는 말이 있을 때만 풀어 씀. — 규칙
- 초성 토큰이 칭찬이나 불만, 또는 주장 자체를 싣고 있으면 극성을 `unknown`으로 적고, 그 글 하나로 주장을
  뒷받침하지 않음. — 규칙
- 검색어에 초성 형태를 더하면 찾는 범위는 넓어지지만 엉뚱한 결과가 많아짐. — 추론

### 5.2 야민정음과 비슷한 글자 표기

- 모양이 비슷한 글자로 바꿔 쓰는 표기(예: 멍멍이→댕댕이, 귀여워→커여워, 명곡→띵곡)를 야민정음이라고 부름. 한
  커뮤니티 게시판에서 발전해 널리 퍼졌다고 알려짐. — 미확인(요약) [Q05]
- 독립된 목소리를 셀 때 변형 표기를 다른 말이나 다른 사람으로 세지 않음. 같은 말로 합침. — 규칙
- 발췌에는 원래 표기를 그대로 둠. — 규칙
- 변형 표기는 글에서 본 것만 검색어에 더함. 기계적으로 만들어 넣지 않음. — 규칙

### 5.3 가격·품질 은어

- 혜자(값에 비해 양이나 품질이 좋음)와 창렬(값에 비해 부실함)은 연예인 이름을 내건 상품에서 나온 말로, 2015년
  무렵 언론에 소개됨. 사전으로 확인하지 못한 말은 용어집에 `dictionary_check: not_checked`로 적음. —
  미확인(요약) [Q06]
- 상타치·하타치(상타취·하타취, ㅅㅌㅊ·ㅎㅌㅊ), 평타 같은 평가 말은 비공식 평가로만 읽음. 이런 말이나 그 유래로
  작성자의 커뮤니티, 나이, 정치 성향을 짐작하지 않음. — 규칙
- 내돈내산, 광고 아님, 협찬 아님은 자기 선언일 뿐 근거가 아님(`references/research/korea/promotion.md` 4c). — 규칙

### 5.4 익명 작성자와 신원

- 익명 게시판에는 로그인하지 않고 쓰는 작성자(유동닉), 로그인했고 닉네임 중복 확인을 거친 작성자(고정닉),
  로그인했지만 중복 확인을 거치지 않은 작성자(반고정닉)가 있다고 설명됨. 유동닉 다수가 기본 닉네임 "ㅇㅇ"을 쓰고,
  로그인하지 않은 작성자는 닉네임 옆에 IP 일부가 보인다고 함. — 미확인(요약) [Q07]
- "ㅇㅇ"은 신원이 아님. 같은 "ㅇㅇ"이 여러 스레드에 나와도 한 사람으로 보지 않음. — 규칙
- `scripts/ux_research.py author-key`는 닉네임의 앞뒤 공백을 지우고 NFKC로 맞춘 뒤, 끝에 붙은 IP 일부(예:
  `ㅇㅇ(203.0)`)를 떼어 냄. 기본 익명 닉네임(`uxresearch/data/markers.json`의 `anonymous_handles`)과 IP 일부가
  붙어 있던 닉네임은 거절함(exit 2). 이런 글은 `author-key --thread-url`로 만든 스레드 키로 셈. — 규칙
- 익명 게시판은 스레드 단위로 셈(`references/research/source-grading.md` 4절). — 규칙
- IP 일부는 reader가 지움. 발췌에 남기거나 되살리지 않음. — 규칙
- 익명 1인칭 사연은 어느 게시판에서든 사실 확인이 안 된 진술로 다루고 `narrative_unverified` 주의 표시를 붙임.
  존재 근거로만 씀(`references/research/korea/platform-map.md` 4절). — 규칙

### 5.5 비꼼과 극성이 불확실한 글

- 글로 쓴 비꼼은 억양이 없어 읽기 어려움. 부모 글과 앞뒤 댓글을 함께 읽음. — 규칙
- 한국어 비꼼 탐지 데이터셋 KoCoSa(LREC-COLING 2024)는 비꼼을 가리려면 대화 맥락이 필요하다는 전제로 만들어졌음.
  일상 대화 12,824개로 이루어지고, 원본 대화에서 대형 언어 모델로 새 대화를 만들어 거른 뒤 사람이 표시했으며, 이
  데이터로 학습한 기준 모델이 GPT-3.5보다 나았다고 요약됨. 합성 대화이므로 "맥락이 중요하다"는 방향만
  뒷받침하고, 아래 단서 목록의 정확도는 뒷받침하지 않음. — 제목, 저자, 학회는 관찰됨 [Q09], 나머지는
  미확인(요약) [Q08]
- 다음이 칭찬과 함께 나오면 극성을 `unknown`(극성 불확실)으로 적음. — 추론(검증되지 않은 설계 규칙)
  - ㅋㅋ, ㅎㅎ 같은 웃음 표기
  - 물결표(~)나 말줄임표
  - 따옴표로 감싼 칭찬
  - 존댓말과 반말 사이의 갑작스러운 전환
  - 칭찬과 어긋나는 결과(예: "최고네요, 결제 세 번째 실패")
- 극성이 불확실한 글은 만족·선호 주장이나 반대 근거 검색의 결과로 쓰지 않음. 판단이 어려우면 검증자에게 넘김. —
  규칙

### 5.6 말투는 인구 특성이 아님

- 상대 높임법은 격식체(하십시오체, 하오체, 하게체, 해라체)와 비격식체(해요체, 해체)로 나뉨. — 미확인(요약) [Q10]
- 말투는 글이 놓인 자리와 쓴 사람의 태도를 보여 줄 뿐, 나이나 성별을 보여 주지 않음. — 규칙
- 말투, 호칭(형, 언니, 님 등), 반말, 은어로 나이, 성별, 정치 성향을 짐작하지 않음. 나이·성별 비율에는 측정
  출처가 필요함(`references/research/source-grading.md` 1절, 4절). — 규칙
- 커뮤니티의 성별·연령·정치 성향 추정치는 작성자, 주장, 페르소나에 붙이지 않음. 커뮤니티 사이의 차이는 코퍼스
  수준의 콘텐츠 규범으로만 적음(`references/research/korea/platform-map.md` 4절,
  `references/research/korea/legal-checklist.md` L10). — 규칙
- 후기 안에 공식 안내문 같은 합쇼체 광고 문장이 이어지면 약한 홍보 단서임
  (`references/research/korea/promotion.md` 6절). — 추론
- 스레드 안에서 말투가 갑자기 바뀌면 짜증이나 비꼼의 단서일 수 있음(5.5절). — 추론

### 5.7 전해 들은 말

- "~대", "~래", "~라더라", "들었는데", "지인이 그러는데", "카더라"는 전해 들은 말의 단서임. 이런 글은 검증자에게
  넘기고, 단서만으로 등급을 낮추지는 않음. 검증자가 직접 경험이 아니라고 보면 등급 규칙에 따라 한 단계 낮춤
  (`references/research/source-grading.md` 3절). — 규칙
- "~더라"는 말하는 이가 겪거나 본 일을 떠올리는 어미로 연구되지만, 일상 글에서는 느슨하게 쓰이므로 직접 사용의
  증거로 보지 않음. — 미확인(요약) [Q11], 판단은 추론

### 5.8 유니코드

- reader는 페이지 글을 NFC로 정규화함(`uxresearch/extract.py`). 검색어, 표지 목록, 용어집도 NFC로 맞춤. — 규칙
- 현대 한글 음절은 U+AC00부터 U+D7A3까지 11,172자임. ㅋㅋ, ㅠㅠ, ㅇㅇ 같은 낱자는 호환용 자모(U+3130–U+318F)로
  적히며, 이런 낱자 연속은 잡음이 아니라 토큰으로 다룸. — 관찰됨 [Q12]
- NFD는 음절을 조합용 자모(U+1100대)로 풀고, NFKC와 NFKD는 호환용 자모를 조합용 자모로 바꿈. NFKC는 따로 적힌
  낱자를 음절로 합치기도 함(예: "ㅇㅏ"가 "아"가 됨). 그래서 초성은 NFC 글에서만 뽑고, 초성체 문자열을 NFKC로 바꿔
  비교하지 않음. 코드에서 NFKC는 닉네임 비교에만 쓰임(`uxresearch/privacy.py`, `uxresearch/verdict.py`). —
  관찰됨 [Q12], 비교 규칙은 규칙

## 6. 시간 구간

- 개편, 큰 업데이트, 리뷰 폭주 앞뒤로 구간을 나눠 검색하고 읽음. 예: 카카오톡 2025-09-23 개편 직후 두 스토어 평점이
  급락했다는 보도(`references/research/korea/platform-map.md` 7절 불연속 날짜표, 미확인(요약)). — 규칙
- 검색어에 연도와 버전을 넣고, 구간마다 반대 근거 검색을 따로 함. — 규칙
- 광고 표시 규칙이 바뀐 날짜 앞뒤의 글은 그때의 기준으로 봄(`references/research/korea/promotion.md` 3절). — 규칙

## 7. 하지 않는 일

- 영어 검색어를 한국어로 직역해 쓰지 않음.
- 모델이 지어낸 은어 뜻을 쓰지 않음.
- 변형 표기를 다른 사람으로 세지 않음.
- 비꼼을 칭찬으로 읽지 않음.
- 말투, 호칭, 은어로 나이, 성별, 정치 성향을 짐작하지 않음.
- 커뮤니티의 성별·연령·정치 성향 추정치를 작성자, 주장, 페르소나에 붙이지 않음.
- 돌보는 사람을 한쪽 성별로 가정하지 않음.
- "ㅇㅇ"이나 IP 일부로 사람을 구별하지 않음.
- 검색 결과 페이지를 열지 않고, 검색 요약문을 멈춘 페이지 대신 쓰지 않음.
- 회원 전용이거나 닫힌 커뮤니티를 사용자 단서로 이름 대지 않음.

## 8. 완료 기준(Done when)

- 축마다 한국어 검색어를 8개 이상 돌렸고, 반대 근거 검색어를 따로 돌렸음.
- 런 폴더에 이번 실행의 용어집이 있고, 항목마다 예문 출처 ID나 "모름"이 있음.
- 씨앗 단어 가운데 글에 나오지 않은 말은 용어집에 없음.
- 극성이 불확실한 글과 전해 들은 말의 단서가 있는 글에 표시를 달고 검증자에게 넘겼음.
- 익명 게시판의 글을 스레드 키로 셌음.
- 약관 제한과 비공개 채널로 읽지 못한 호스트를 수집 공백이나 범위 밖으로 적었음.

## 9. 실패 유형(Failure modes)

- 직역한 검색어: 사용자가 실제로 쓰는 말로 다시 검색함.
- 모델이 지어낸 은어 뜻: 예문이 없으면 "모름"으로 되돌림.
- 변형 표기를 추가 인원으로 셈: 같은 말로 합치고 다시 셈.
- 비꼼을 칭찬으로 읽음: 스레드를 다시 읽고 극성을 `unknown`으로 바꿈.
- 말투나 호칭으로 세그먼트를 정함: 측정 출처가 없으면 세그먼트 비율은 "모름".
- 돌봄 검색을 "엄마"로만 돌림: 아빠, 보호자, 육아, 아이 키우는을 더해 다시 돌림.
- 같은 "ㅇㅇ"을 한 사람으로 셈: 스레드 키로 다시 셈.
- 검색 요약문을 멈춘 페이지의 내용처럼 씀: 단서로만 남기고 수집 공백으로 적음.
- NFKC로 바꾼 초성체를 비교해 맞추지 못하거나 엉뚱한 음절과 맞춤: NFC로 다시 비교함.
- 한 번의 결과 없음을 논의 없음으로 읽음: 검색 도구의 한계를 적고 다른 채널 계열을 봄.

## 10. 연결 문서

`references/research/korea/overview.md`(팩 개요), `references/research/korea/platform-map.md`(채널 id, 콘텐츠 규범,
불연속 날짜), `references/research/korea/promotion.md`(협찬 표지와 등급),
`references/research/korea/report-template.md`(보고서의 인용과 귀속),
`references/research/korea/legal-checklist.md`(법령 근거), `references/research/research-protocol.md`(검색어 확장,
기록 양식), `references/research/source-grading.md`(등급과 독립 단위),
`references/research/public-page-access.md`(읽기 계약).

## 11. 출처

확인일은 모두 2026-09-29입니다.

- Q01 네이버 검색 연산자(사용자 안내 글): https://www.clien.net/service/board/lecture/6343874,
  https://reinia.net/1873, https://lovedweb.com/71 — 미확인(요약)
- Q02 우리말샘: https://opendict.korean.go.kr/main,
  https://www.korea.kr/briefing/policyBriefingView.do?newsId=156157539 — 미확인(요약)
- Q03 국립국어원 신어 자료집: https://www.korean.go.kr/front/reportData/reportDataList.do,
  https://korean.go.kr/front/reportData/reportDataView.do?mn_id=45&searchOrder=&report_seq=1096&pageIndex=2 (2009년
  신어 자료집) — 미확인(요약)
- Q04 초성체: https://ko.wikipedia.org/wiki/%EC%B4%88%EC%84%B1%EC%B2%B4 — 미확인(요약)
- Q05 야민정음: https://ko.wikipedia.org/wiki/%EC%95%BC%EB%AF%BC%EC%A0%95%EC%9D%8C,
  https://www.hankyung.com/article/2022100694807 — 미확인(요약)
- Q06 혜자·창렬: https://www.kyeonggi.com/article/201505200651375,
  https://www.sportsworldi.com/newsView/20150521006131 — 미확인(요약)
- Q07 유동닉·고정닉·반고정닉: https://ko.wikipedia.org/wiki/%EC%9C%A0%EB%8F%99%EB%8B%89,
  https://ko.wikipedia.org/wiki/%EB%B0%98%EA%B3%A0%EC%A0%95%EB%8B%89 — 미확인(요약)
- Q08 KoCoSa 논문: https://aclanthology.org/2024.lrec-main.864/, https://arxiv.org/abs/2402.14428 — 미확인(요약)
- Q09 KoCoSa 저자 저장소: https://github.com/Yu-billie/KoCoSa_sarcasm_detection — 관찰됨(README에서 제목, 저자,
  학회를 읽음)
- Q10 상대 높임법(국립국어원 온라인가나다):
  https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=&qna_seq=332328&pageIndex=1 — 미확인(요약)
- Q11 한국어 증거성 어미 연구: https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001256271,
  https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003001951 — 미확인(요약, 논문 본문을 읽지 못함)
- Q12 유니코드 정규화(UAX #15): https://www.unicode.org/reports/tr15/ — 관찰됨(Python unicodedata, 유니코드 14.0으로
  직접 계산해 확인함. 표준 문서 페이지는 열지 못함)
