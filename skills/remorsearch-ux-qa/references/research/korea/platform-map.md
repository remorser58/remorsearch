# 한국 플랫폼 지도

항목 조회용 문서입니다. 전체 읽기는 기본 경로에 포함하지 않습니다. 스킬 폴더에서 `python3 scripts/ref.py references/research/korea/platform-map.md naver-blog`로 필요한 ID만 조회합니다.

이 문서는 한국 채널 27곳에서 리서치를 계획할 때 쓰는 지도입니다. 채널마다 공개 범위, 정당한 경로, 예상 중단, 약관
상태, 콘텐츠 규범, 개인정보 주의점, 불연속 날짜를 적습니다. 데이터 원본은 `uxresearch/data/korea-platforms.json`이고,
이 문서는 같은 내용을 사람이 읽기 좋게 옮긴 판입니다. 한국 리서치 팩의 흐름은
`references/research/korea/overview.md`에서 시작합니다.

이 문서의 어떤 내용도 중단을 넘는 방법이 아닙니다. 멈춘 페이지는 다른 길로 가져오지 않고 수집 공백으로 적습니다.

## 1. 이 지도의 성격

- 계획용 지식입니다. 실제로 무엇을 읽고 어디서 멈출지는 reader 정책인 `uxresearch/data/routes.json`이 정합니다. 두
  파일이 어긋나면 routes.json을 따르고 이 지도를 고칩니다.
- 사용자 단서는 플랫폼 전체 사용자에 관한 조사·패널 값입니다. 채널을 고르는 단서일 뿐 세그먼트 비율이 아니고, 글쓴이
  구성도 아닙니다(`references/research/source-grading.md` 4절). 단서 신뢰도(high, medium, low)는 채널 선택 단서로서
  그 값을 얼마나 믿을 만한지를 뜻합니다.
- 커뮤니티의 성별·연령·정치 성향 추정치는 싣지 않습니다. 그런 추정치는 게시자, 주장, 페르소나 어디에도 붙이지
  않습니다(4절).
- 회원 전용이거나 닫힌 커뮤니티는 사용자 단서로 이름을 대지 않습니다. 회원 전용 글은 사용자가 브리프의
  `access_policy.signed_in_communities`에 직접 승인한 커뮤니티에서만, 요약으로만 다룹니다.
- 경로는 정당한 경로만 적습니다. 사용자 본인 키로 부르는 공식 API, 공식 피드, 팀 자체 자료, reader가 읽는 공개
  페이지, 사용자가 승인한 커뮤니티의 로그인 읽기입니다. 멈춘 페이지를 다른 호스트, 미러, 캐시, 아카이브, 앱, 요령으로
  가져오는 방법은 적지 않습니다. 중단은 그 자체로 답이며 보고서의 수집 공백이 됩니다.
- 플랫폼 이름은 설명을 위해 씁니다. 이 스킬은 어떤 운영사와도 제휴 관계가 없습니다.
- 원문을 읽은 약관·robots의 확인일(checked_at)은 2026-09-30 또는 2026-10-01이며, 그 밖의 사실은 각 행에 확인일을 적었습니다.
  사람이 실시간 확인(robots 확인과 약관 원문 읽기)을 마치기 전까지 verified_at은 비워 둡니다(null).
- 직접 읽은 운영사 원문과 기관 첨부는 관찰됨으로 적었습니다. 원문에 닿지 못한 판·사용자 구성·보도는 미확인으로
  남겨 두며, robots 관찰은 그날의 스냅샷입니다. 실제 실행에서는 현재 URL의 규칙과 중단을 다시 판정합니다.
- 이 문서는 법률 자문이 아닙니다. 약관 문구는 읽은 방식과 함께 적고, 법적 적용은 판단하지 않습니다. 법령 근거는
  `references/research/korea/legal-checklist.md`에 있습니다.

확인 표시는 `references/research/korea/promotion.md`, `references/research/korea/statistics.md`,
`references/research/korea/query-craft.md`와 같습니다.

| 표시 | 뜻 | JSON `read_via` |
| --- | --- | --- |
| 관찰됨 | 1차 출처의 원문을 직접 열어 읽음. 출처와 읽은 날짜를 함께 적음 | `direct_fetch` |
| 미확인(요약) | 검색 결과 요약으로만 봄. 운영사·기관 도메인으로 한정한 검색, 보도, 제3자 인용도 여기에 넣음 | `search_index`, `search_summary`, `third_party_quote` |
| 미확인(미러) | 법령 원문을 옮긴 공개 저장소 사본으로 읽음. law.go.kr 원문과 대조하지 못함 | `mirror` |
| 미확인 | 이번 확인에서 쓸 만한 자료를 찾지 못함 | `not_found` |
| 추론 | 위 사실에서 이 스킬이 끌어낸 판단 | `inference` |
| 규칙 | 이 스킬의 규칙. 규칙 문서를 함께 적음 | `skill_rule` |

값의 뜻은 다음과 같습니다.

| 항목 | 값 | 뜻 |
| --- | --- | --- |
| 정당한 경로 | `official_api_user_key` | 사용자 본인 키로 부르는 공식 API. 키는 `REMORSEARCH_*` 환경 변수로만 받음 |
| 정당한 경로 | `official_feed` | 운영사가 내놓은 공식 피드(RSS 등). reader의 R0 경로 |
| 정당한 경로 | `team_export` | 팀이 가진 자체 자료(VOC, 고객센터 기록, 스토어·판매자 콘솔 내보내기). 파일로 받으며 `team_provided` 출처가 됨. 개인 식별 정보를 지운 뒤 받음 |
| 정당한 경로 | `reader_public_page` | reader가 읽는 공개 페이지(`scripts/ux_research.py read`). 거부 신호 없이 스크립트만 있는 페이지라고 답할 때만 익명 브라우저로 렌더한 뒤 `ingest`. 로그인, 사람 확인, 봇 차단, 브라우저 확인 화면, 속도 제한에서 멈춤. 봇 차단(`bot_filter`)과 브라우저 확인(`js_check`)은 `opted_out`이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면 표지가 있거나 `waited_ms`가 0보다 큰 캡처는 `ingest`가 받지 않음 |
| 정당한 경로 | `signed_in_authorised` | 사용자가 브리프의 `access_policy.signed_in_communities`에 직접 적은 커뮤니티만 로그인해 읽고 요약만 남김. 에이전트는 이 목록에 더하지 않음 |
| 정당한 경로 | `none` | 이 스킬이 쓸 경로가 없음. 설문, 인터뷰, 팀 자료로 대신함 |
| 약관 상태 | `confirmed` | 운영사의 조항을 읽고 대조한 근거 상태. 해제 여부는 lift_requires로 정함. 사람이 원문을 읽기 전까지 verified_at은 null임 |
| 약관 상태 | `reported` | 원문·취득 경위·판이 아직 미확인인 근거 상태. 해제 여부는 lift_requires로 정함 |
| 약관 상태 | `checked_by_user` | 사용자가 직접 확인해 기록한 상태(이 지도에는 아직 없음) |
| 약관 상태 | `unchecked` | 사용자 확인이나 자동 수집 허용 범위를 확정하지 못함. 원문 조항을 읽은 경우도 조항·확인 줄에 따로 표시함. reader의 일반 중단 규칙을 적용함 |
| robots 예상 | `unknown` | 실행 때 robots 확인 전까지 모름 |
| robots 예상 | `reported_closed` | 보도상 우리 토큰에 적용될 그룹이 막혀 있음 |
| robots 예상 | `not_reached` | 약관 중단이나 범위 밖 중단이 먼저라 robots.txt를 요청하지 않음 |
| 공개 범위 | `public`, `mixed`, `app_heavy`, `app_only`, `private` | 공개, 공개·회원 전용 혼합, 앱 중심, 앱 전용, 비공개 |

예상 중단 값은 `references/research/public-page-access.md` 5절의 중단 유형에 약관 중단 `terms_restricted`를 더한
것입니다(`uxresearch/scope.py`). `terms_restricted`는 요청 전에, 그리고 리디렉션 단계마다 판정하므로 짧은 주소가 제한
호스트로 넘어가도 멈춥니다. 운영사의 짧은 주소(naver.me, me2.do, coupa.ng, t.co 등)도 요청 전에 멈춥니다.
근거 상태 `reported`·`confirmed`는 해제 여부를 정하지 않습니다. `lift_requires: never`인 유튜브·인스타그램·스레드·페이스북·틱톡·클리앙·앱스토어·Hacker News 페이지는 풀 수 없습니다. `written_permission`인 디시인사이드·네이버·네이버 카페 공지·쿠팡·X·당근·Reddit은 항목별 사용자 확인과 해당 읽기의 사전 서면 허락이 필요합니다. `terms_check`이면 항목별 사용자 확인이 필요합니다. X(x.com, twitter.com, t.co)는 `x-terms`의 `written_permission` 조건을 따릅니다. oEmbed 실행 경로는 제거했으며, `official_route`가 null이므로 공식 경로만 쓰는 방식으로 열 수 없습니다.

약관 확인의 `terms_url`은 그 항목에 기록된 약관 문서여야 합니다. 확인의 `host`는 항목의 호스트이거나 더 좁고, 읽을
URL을 포함해야 합니다. 한 URL에 걸린 제한은 항목마다 별도 확인으로 모두 풀어야 합니다. 네이버 카페 공지는
원문 주소가 기록되어 있으며, 공지와 네이버 이용약관을 각각 확인하고 사전 서면 허락을 기록해야 합니다. 풀린 항목도 모든 호스트를 합쳐
실행당 문서 10건까지만 읽습니다(`references/research/public-page-access.md` 17절).

공식 경로가 있는 제한 호스트(유튜브)는 그 경로만 씁니다. 실패해도 페이지나 대체 주소를 요청하거나 렌더하지 않으며,
`ingest`도 캡처를 받지 않습니다. 검색 결과 페이지는 직접 넘기면 exit 2로 거절하고, 리디렉션 중에 만나면 중단으로
기록합니다. 아카이브, 번역·리더 프록시, AMP 캐시, 대체 프런트엔드 같은 제3자 사본은 `third_party_copy`로
거절합니다. 브리프가 허용한 제품 공식 페이지의 과거 웨이백 사본만 예외입니다.

봇 차단과 브라우저 확인 화면은 `opted_out`이며 등록 도메인 전체를 이번 실행에서 멈춥니다. robots.txt 자리에 이런
화면이 와도 같습니다. 브라우저 도구도 멈춘 사이트를 열지 않으며, 거절 뒤에는 렌더하지 않습니다. 확인 화면 표지가
있거나 `waited_ms`가 0보다 큰 캡처는 `ingest`가 받지 않습니다(`references/research/public-page-access.md` 5절).

## 2. 한눈에 보기

행 순서는 JSON과 같습니다.

| id | 채널 | 계열 | 공개 범위 | 정당한 경로 | 예상 중단 | 약관 | 단서 신뢰도 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `naver-blog` | 네이버 블로그 | 블로그 | 공개 | `official_feed`, `reader_public_page` | `terms_restricted` | `confirmed` | medium |
| `naver-cafe` | 네이버 카페(육아·지역 카페 포함) | 커뮤니티 | 혼합 | `reader_public_page`, `signed_in_authorised` | `terms_restricted`, `auth_gate` | `confirmed` | low |
| `naver-kin` | 네이버 지식iN | 질문·답변 | 공개 | `reader_public_page` | `terms_restricted` | `confirmed` | medium |
| `naver-place` | 네이버 플레이스 리뷰 | 상거래 리뷰 | 앱 중심 | `team_export`, `reader_public_page` | `terms_restricted` | `confirmed` | medium |
| `kakao-map` | 카카오맵 리뷰 | 상거래 리뷰 | 앱 중심 | `reader_public_page` | - | `unchecked` | low |
| `daum-cafe` | 다음 카페 | 커뮤니티 | 혼합 | `reader_public_page`, `signed_in_authorised` | `auth_gate` | `unchecked` | low |
| `tistory` | 티스토리 | 블로그 | 공개 | `official_feed`, `reader_public_page` | - | `unchecked` | low |
| `dcinside` | 디시인사이드 | 커뮤니티 | 공개 | `reader_public_page` | `terms_restricted` | `confirmed` | medium |
| `fmkorea` | 에펨코리아 | 커뮤니티 | 공개 | `reader_public_page` | - | `unchecked` | low |
| `theqoo` | 더쿠 | 커뮤니티 | 혼합 | `reader_public_page` | `auth_gate` | `unchecked` | low |
| `nate-pann` | 네이트판 | 커뮤니티 | 공개 | `reader_public_page` | - | `unchecked` | low |
| `clien` | 클리앙 | 커뮤니티 | 공개 | `none` | `terms_restricted` | `confirmed` | low |
| `ppomppu` | 뽐뿌 | 커뮤니티 | 공개 | `reader_public_page` | - | `unchecked` | low |
| `ruliweb` | 루리웹 | 커뮤니티 | 공개 | `reader_public_page` | - | `unchecked` | low |
| `instiz` | 인스티즈 | 커뮤니티 | 혼합 | `reader_public_page` | `auth_gate` | `unchecked` | low |
| `blind` | 블라인드 | 커뮤니티 | 혼합 | `reader_public_page` | `auth_gate` | `unchecked` | medium |
| `everytime` | 에브리타임 | 커뮤니티 | 비공개 | `none` | `auth_gate` | `unchecked` | low |
| `band` | 네이버 밴드 | 커뮤니티 | 비공개 | `none` | `auth_gate` | `unchecked` | low |
| `kakaotalk-openchat` | 카카오톡 오픈채팅 | 커뮤니티 | 비공개 | `none` | `auth_gate` | `unchecked` | low |
| `daangn` | 당근(동네생활) | 커뮤니티 | 앱 중심 | `reader_public_page` | `terms_restricted` | `reported` | medium |
| `youtube` | 유튜브 댓글 | 영상 댓글 | 공개 | `official_api_user_key` | `terms_restricted` | `confirmed` | medium |
| `instagram` | 인스타그램 | 마이크로블로그 | 혼합 | `none` | `terms_restricted` | `confirmed` | medium |
| `threads` | 스레드 | 마이크로블로그 | 혼합 | `none` | `terms_restricted` | `confirmed` | medium |
| `app-store-kr` | 앱스토어 리뷰(한국) | 스토어 리뷰 | 공개 | `team_export` | `terms_restricted` | `confirmed` | medium |
| `google-play-kr` | 구글 플레이 리뷰(한국) | 스토어 리뷰 | 공개 | `team_export`, `reader_public_page` | - | `unchecked` | medium |
| `coupang` | 쿠팡 상품 리뷰 | 상거래 리뷰 | 공개 | `team_export`, `reader_public_page` | `terms_restricted`, `opted_out` | `reported` | medium |
| `delivery-apps` | 배달앱 리뷰(배달의민족·쿠팡이츠·요기요) | 상거래 리뷰 | 앱 전용 | `team_export` | - | `unchecked` | medium |

## 3. 채널별 상세

### `naver-blog` 네이버 블로그

- 호스트: `blog.naver.com`, `m.blog.naver.com` · route table id: `naver-blog`, `naver-blog-postview`
- 계열 `blog` · 공개 범위 `public`: 전체공개 글만 공개 페이지로 봄. 이웃공개·서로이웃공개·비공개 글은 로그인하지 않은 방문자가 읽을 수 없으므로 공개가 아님. — 규칙 (`references/research/public-page-access.md`)
- 정당한 경로(선호 순): `official_feed` → `reader_public_page`
  - routes.json의 naver-terms 항목(confirmed)이 네이버 호스트 전체를 덮어 RSS 피드와 공개 페이지가 함께 멈춤. lift_requires: written_permission 항목은 사용자가 그 항목의 약관 문서를 직접 읽고 access_policy.terms_checked에 result permits_this_reading과 운영사의 사전 서면 허락(permission: granted_by, granted_on, reference)을 함께 적은 실행에서만 풀림. checked_on은 effective_from이 있으면 그날 이후여야 하며, 오늘 이후이거나 365일이 지난 확인은 무효임. lift_requires: never 항목은 풀리지 않음. 에이전트는 확인 항목을 쓰지 않음. 풀린 항목은 모든 호스트를 합쳐 실행당 문서 10건까지 읽음. RSS 제공 여부와 주소 형태는 실시간 확인 전임. — 규칙 (`uxresearch/data/routes.json`)
  - 네이버 검색 API와 NAVER API HUB는 소유자가 현행 약관을 읽기 전까지 꺼 둠. 2026-09-30 직접 읽은 개발자센터 약관은 검색 결과를 독립적으로 가공 없이 보여 주고 네이버·원본 출처와 링크를 표시하도록 함. AI 입력·학습·개선·평가·노출, 예외 밖의 복사·저장·캐싱, 제3자 제공·판매, 광고 수익화를 금지함. 기기 보관은 24시간과 새 질의 중 짧은 기간, 서버 이력 보관은 최대 21일임. API HUB 자체 약관과 보도된 2026-09-07 시행일은 미확인. — 관찰됨 2026-09-30 [P138]
  - 2026-09-30 읽은 개발자센터 약관 부칙은 2026-07-30 24:00 이후 신규 신청을 중단하고, 그때까지 신청한 기존 이용자에게 2027-06-30 24:00까지 API를 제공한다고 적음. 쇼핑·책·학술정보는 2026-07-31 24:00에 종료됨. API HUB 자체의 현행 이용 조건은 미확인. — 관찰됨 2026-09-30 [P138]
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `terms_restricted`
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 목록·미리보기·내보내기·댓글 경로 등을 막으며 PostView.naver는 금지 목록에 없음. GPTBot·OAI-SearchBot·ClaudeBot·Claude-SearchBot·PerplexityBot 등 명시 그룹은 전체 경로를 막음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P135]
- 약관 `confirmed`(routes.json `naver-terms`), 제한 `automated_collection`
  - 조항: "네이버의 사전 허락 없이 자동화된 수단"을 이용하여 "네이버 서비스에 게재된 회원의 아이디(ID), 게시물 등을 수집하거나" 시도해서는 안 됨.
  - 확인: 2026-10-01 네이버 이용약관 원문에서 자동 수집 제한과 2025-07-10 시행일을 읽음. 검색결과 수집 정책도 읽었으나 그 문서의 개정·시행일과 2026-09 개정 여부는 미확인. lift_requires: written_permission에 따라 항목별 사용자 확인과 해당 읽기의 사전 서면 허락이 있어야 풀림. verified_at은 사람이 원문을 읽기 전까지 null임. — 관찰됨 2026-10-01 [P08, P155]
- 사용자 단서(신뢰도 `medium`): 네이버 발표를 전한 보도(2025-12): 2025년 블로그 새 글 3억 3천만 건, 순방문자 4,500만 명 이상. 작성자 연령 구성은 싣지 않음(측정 자료를 확인하지 못함). — 미확인(요약) [P11, P12]
- 콘텐츠 규범:
  - 협찬·체험단 글이 많은 채널임. 공정위 2024년 SNS 뒷광고 모니터링에서 네이버 블로그 의심 게시물은 9,423건(전체 22,011건). 적발 건수일 뿐 비율이나 분모가 아님. — 미확인(요약) [P14, P15]
  - 2024-12-01부터 블로그·카페의 추천·보증 글은 경제적 이해관계를 제목이나 첫 부분에 적어야 함(공정위 추천·보증 심사지침 개정). 그 전 글은 표시 위치가 다를 수 있으므로 게시일을 함께 봄. — 관찰됨 2026-10-01 [P163]
  - 표시가 없다고 협찬이 없는 글로 보지 않음. '내돈내산'은 자기 선언일 뿐 독립성의 근거가 아님. — 규칙 (`references/research/korea/promotion.md`)
- 개인정보:
  - 블로그 ID가 URL에 들어 있음. 작성자는 author-key로 바꾸고 글 URL은 번들의 source_ref에만 둠. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2024-12-01: 블로그·카페 추천·보증 글의 이해관계 표시를 제목이나 첫 부분에 두도록 한 공정위 지침 개정 시행 — 관찰됨 2026-10-01 [P163]
  - 2025-07: 네이버 블로그·카페 등에서 AI 봇 크롤링을 robots.txt로 막는다는 보도 — 미확인(요약) [P06, P07]
  - 2025-07-10: 네이버 이용약관 개정 시행: 사용자가 삭제·비공개로 돌린 글은 그 뒤 AI 연구 개발에 쓰지 않는다는 내용 보도 — 미확인(요약) [P17, P18]
  - 2025-12: 블로그 앱 추천 피드 개편 시험 보도(주제별 '내돈내산' 글 모아 보기 포함) — 미확인(요약) [P19]
  - 2026-07-31: 개발자센터 검색 API 신규 신청 중단(2026-07-30 24:00 이후). 쇼핑·책·학술정보 데이터는 2026-07-31 24:00 종료 — 관찰됨 2026-09-30 [P138]
  - 2026-09-07: 네이버 검색 API 특약 개정 시행 보도: 결과를 AI에 넣거나 저장·제3자 제공하는 행위 금지 — 미확인(요약) [P01, P02]
  - 2027-06-30: 개발자센터의 기존 이용자 대상 검색 API 제공 종료 예정(2027-06-30 24:00) — 관찰됨 2026-09-30 [P138]
- 확인일 2026-10-01 · verified_at 없음(null)

### `naver-cafe` 네이버 카페(육아·지역 카페 포함)

- 호스트: `cafe.naver.com`, `m.cafe.naver.com` · route table id: `naver-cafe`
- 계열 `community` · 공개 범위 `mixed`: 카페마다 공개 게시판과 회원 전용 게시판이 섞여 있고, 등급(등업) 조건이 붙은 게시판도 있음. 회원 전용·등업 게시판은 공개가 아님(auth_gate). — 규칙 (`references/research/public-page-access.md`)
- 정당한 경로(선호 순): `reader_public_page` → `signed_in_authorised`
  - 네이버 카페 주소에는 naver-terms와 naver-cafe-bulk-notice가 함께 적용되어 항목마다 별도 확인이 필요함. lift_requires: written_permission 항목은 사용자가 그 항목의 약관 문서를 직접 읽고 access_policy.terms_checked에 result permits_this_reading과 운영사의 사전 서면 허락(permission: granted_by, granted_on, reference)을 함께 적은 실행에서만 풀림. checked_on은 effective_from이 있으면 그날 이후여야 하며, 오늘 이후이거나 365일이 지난 확인은 무효임. lift_requires: never 항목은 풀리지 않음. 에이전트는 확인 항목을 쓰지 않음. 풀린 항목은 모든 호스트를 합쳐 실행당 문서 10건까지 읽음. 카페 공지 원문 주소가 기록되어 있으며, 공지 항목과 네이버 이용약관은 각각 별도 확인과 사전 서면 허락이 필요함. — 규칙 (`uxresearch/data/routes.json`)
  - 로그인 읽기는 사용자가 브리프의 access_policy.signed_in_communities에 카페 경로(path_prefix)와 함께 직접 적은 카페만 해당함. 요약만 남기고 회원 정보는 남기지 않음. 에이전트는 이 목록에 카페를 더하지 않음. — 규칙 (`references/research/public-page-access.md`)
  - 네이버 검색 API와 NAVER API HUB는 소유자가 현행 약관을 읽기 전까지 꺼 둠. 2026-09-30 직접 읽은 개발자센터 약관은 검색 결과를 독립적으로 가공 없이 보여 주고 네이버·원본 출처와 링크를 표시하도록 함. AI 입력·학습·개선·평가·노출, 예외 밖의 복사·저장·캐싱, 제3자 제공·판매, 광고 수익화를 금지함. 기기 보관은 24시간과 새 질의 중 짧은 기간, 서버 이력 보관은 최대 21일임. API HUB 자체 약관과 보도된 2026-09-07 시행일은 미확인. — 관찰됨 2026-09-30 [P138]
  - 2026-09-30 읽은 개발자센터 약관 부칙은 2026-07-30 24:00 이후 신규 신청을 중단하고, 그때까지 신청한 기존 이용자에게 2027-06-30 24:00까지 API를 제공한다고 적음. 쇼핑·책·학술정보는 2026-07-31 24:00에 종료됨. API HUB 자체의 현행 이용 조건은 미확인. — 관찰됨 2026-09-30 [P138]
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `terms_restricted`, `auth_gate`
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 Disallow: /로 전체 경로를 막음. GPTBot·OAI-SearchBot·ClaudeBot·Claude-SearchBot·PerplexityBot 등 명시 그룹도 전체 경로를 막음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P137]
- 약관 `confirmed`(routes.json `naver-cafe-bulk-notice`), 제한 `bulk_collection`, `automated_collection`
  - 조항: "크롤러·봇·스크립트 등 자동화된 방식으로 게시물과 댓글을 대량으로 조회·수집하는 행위" 금지.
  - 확인: 2026-10-01 공지 원문을 읽음. 공지 날짜는 2026-08-25이며 2026-08-31은 보도일임. lift_requires: written_permission에 따라 이 공지의 확인과 사전 서면 허락이 필요함. 네이버 이용약관도 별도로 확인해야 하며, 두 항목을 모두 풀어야 함. verified_at은 사람이 원문을 읽기 전까지 null임. — 관찰됨 2026-10-01 [P147]
- 사용자 단서(신뢰도 `low`): 와이즈앱 추정 네이버 카페 앱 월평균 사용자 904만 명(2026-01~04). 앱 사용자 수는 글쓴이 수도 세그먼트 비율도 아님. 육아·지역 카페 구성원의 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인(요약) [P22, P23]
- 콘텐츠 규범:
  - 업체가 회원인 척 쓴 가짜 후기와 숨은 마케팅 사례가 여러 차례 보도된 채널임. 공동구매·업체 홍보 글은 promotion 표지로 먼저 거름. — 미확인(요약) [P24, P25]
  - 경쟁 업체를 깎아내리는 댓글 사례도 보도됨(2026-04). 부정적인 글도 판촉일 수 있음. — 미확인(요약) [P26]
- 개인정보:
  - 아이 이름·학교·병원·동네 같은 세부는 남기지 않음. 미성년자로 보이는 사람의 글은 건너뜀. 공유 산출물에는 풀어 쓴 요약만 둠. — 규칙 (`references/research/korea/legal-checklist.md`)
- 불연속:
  - 2024-12-01: 블로그·카페 추천·보증 글의 이해관계 표시를 제목이나 첫 부분에 두도록 한 공정위 지침 개정 시행 — 관찰됨 2026-10-01 [P163]
  - 2025-07: 네이버 블로그·카페 등에서 AI 봇 크롤링을 robots.txt로 막는다는 보도 — 미확인(요약) [P06, P07]
  - 2025-07-10: 네이버 이용약관 개정 시행: 사용자가 삭제·비공개로 돌린 글은 그 뒤 AI 연구 개발에 쓰지 않는다는 내용 보도 — 미확인(요약) [P17, P18]
  - 2026-07-31: 개발자센터 검색 API 신규 신청 중단(2026-07-30 24:00 이후). 쇼핑·책·학술정보 데이터는 2026-07-31 24:00 종료 — 관찰됨 2026-09-30 [P138]
  - 2026-08-25: 게시글·댓글 대량 수집 금지 카페 공지 게시 — 관찰됨 2026-10-01 [P147]
  - 2026-09-07: 네이버 검색 API 특약 개정 시행 보도: 결과를 AI에 넣거나 저장·제3자 제공하는 행위 금지 — 미확인(요약) [P01, P02]
  - 2027-06-30: 개발자센터의 기존 이용자 대상 검색 API 제공 종료 예정(2027-06-30 24:00) — 관찰됨 2026-09-30 [P138]
- 확인일 2026-10-01 · verified_at 없음(null)

### `naver-kin` 네이버 지식iN

- 호스트: `kin.naver.com`, `m.kin.naver.com` · route table id: `naver-kin`
- 계열 `qna` · 공개 범위 `public`: 질문과 답변이 한 페이지에 공개됨. 질문자와 답변자는 서로 다른 사람으로 셈. — 규칙 (`references/research/public-page-access.md`)
- 정당한 경로(선호 순): `reader_public_page`
  - routes.json의 naver-terms 항목(confirmed)이 덮음. lift_requires: written_permission 항목은 사용자가 그 항목의 약관 문서를 직접 읽고 access_policy.terms_checked에 result permits_this_reading과 운영사의 사전 서면 허락(permission: granted_by, granted_on, reference)을 함께 적은 실행에서만 풀림. checked_on은 effective_from이 있으면 그날 이후여야 하며, 오늘 이후이거나 365일이 지난 확인은 무효임. lift_requires: never 항목은 풀리지 않음. 에이전트는 확인 항목을 쓰지 않음. 풀린 항목은 모든 호스트를 합쳐 실행당 문서 10건까지 읽음. — 규칙 (`uxresearch/data/routes.json`)
  - 네이버 검색 API와 NAVER API HUB는 소유자가 현행 약관을 읽기 전까지 꺼 둠. 2026-09-30 직접 읽은 개발자센터 약관은 검색 결과를 독립적으로 가공 없이 보여 주고 네이버·원본 출처와 링크를 표시하도록 함. AI 입력·학습·개선·평가·노출, 예외 밖의 복사·저장·캐싱, 제3자 제공·판매, 광고 수익화를 금지함. 기기 보관은 24시간과 새 질의 중 짧은 기간, 서버 이력 보관은 최대 21일임. API HUB 자체 약관과 보도된 2026-09-07 시행일은 미확인. — 관찰됨 2026-09-30 [P138]
  - 2026-09-30 읽은 개발자센터 약관 부칙은 2026-07-30 24:00 이후 신규 신청을 중단하고, 그때까지 신청한 기존 이용자에게 2027-06-30 24:00까지 API를 제공한다고 적음. 쇼핑·책·학술정보는 2026-07-31 24:00에 종료됨. API HUB 자체의 현행 이용 조건은 미확인. — 관찰됨 2026-09-30 [P138]
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `terms_restricted`
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 전문가·이벤트 일부 경로만 막고 /qna/detail은 금지 목록에 없음. ChatGPT-User·GPTBot·OAI-SearchBot·ClaudeBot·Claude-SearchBot·PerplexityBot 등 명시 그룹은 Disallow: /임. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P142]
- 약관 `confirmed`(routes.json `naver-terms`), 제한 `automated_collection`
  - 조항: "네이버의 사전 허락 없이 자동화된 수단"을 이용하여 "네이버 서비스에 게재된 회원의 아이디(ID), 게시물 등을 수집하거나" 시도해서는 안 됨.
  - 확인: 2026-10-01 네이버 이용약관 원문에서 자동 수집 제한과 2025-07-10 시행일을 읽음. 검색결과 수집 정책도 읽었으나 그 문서의 개정·시행일과 2026-09 개정 여부는 미확인. lift_requires: written_permission에 따라 항목별 사용자 확인과 해당 읽기의 사전 서면 허락이 있어야 풀림. verified_at은 사람이 원문을 읽기 전까지 null임. — 관찰됨 2026-10-01 [P08, P155]
- 사용자 단서(신뢰도 `medium`): 2022-10-06 발표를 전한 보도: 2021년 신규 사용자의 56%가 10-20대. 20년 누적 사용자 3,200만 명, 문답 8억 건. 글쓴이 구성으로 쓰지 않음. — 미확인(요약) [P27, P28]
- 콘텐츠 규범:
  - 2024-04-25 개편으로 질문 마감이 없어지고 여러 답변을 채택할 수 있게 됨. 누구나 답변에 UP/DOWN 투표를 할 수 있고 UP이 많은 답변이 위에 보임. 눈에 띄는 답변은 투표로 골라진 답변임. — 미확인(요약) [P29, P30]
  - AI 자동 답변 '지식이'는 2024-08 시범 시작 뒤 약 100만 건의 질문에 답했고 2026-05-24 종료됨. 이 기간의 답변은 AI가 썼을 수 있으므로 답변마다 작성 주체를 따로 적음. — 미확인(요약) [P31, P32, P33]
- 개인정보:
  - 2026-02-04 인물 정보와 지식iN 계정이 잘못 이어져 유명인의 과거 답변이 한때 드러났다는 보도가 있음. 답변 이력은 신원으로 이어질 수 있으므로 특정인의 질문·답변 이력을 모으지 않음. — 미확인(요약) [P34, P35]
- 불연속:
  - 2024-04-25: 지식iN 개편: 질문 마감 폐지, 여러 답변 채택, 답변 UP/DOWN 투표 — 미확인(요약) [P29, P30]
  - 2024-08: 지식iN AI 자동 답변 '지식이' 시범 시작 — 미확인(요약) [P31]
  - 2025-07: 네이버 블로그·카페 등에서 AI 봇 크롤링을 robots.txt로 막는다는 보도 — 미확인(요약) [P06, P07]
  - 2025-07-10: 네이버 이용약관 개정 시행: 사용자가 삭제·비공개로 돌린 글은 그 뒤 AI 연구 개발에 쓰지 않는다는 내용 보도 — 미확인(요약) [P17, P18]
  - 2026-05-24: 지식iN AI 자동 답변 '지식이' 종료 — 미확인(요약) [P32, P33]
  - 2026-07-31: 개발자센터 검색 API 신규 신청 중단(2026-07-30 24:00 이후). 쇼핑·책·학술정보 데이터는 2026-07-31 24:00 종료 — 관찰됨 2026-09-30 [P138]
  - 2026-09-07: 네이버 검색 API 특약 개정 시행 보도: 결과를 AI에 넣거나 저장·제3자 제공하는 행위 금지 — 미확인(요약) [P01, P02]
  - 2027-06-30: 개발자센터의 기존 이용자 대상 검색 API 제공 종료 예정(2027-06-30 24:00) — 관찰됨 2026-09-30 [P138]
- 확인일 2026-10-01 · verified_at 없음(null)

### `naver-place` 네이버 플레이스 리뷰

- 호스트: `m.place.naver.com` · route table id: `naver-place`
- 계열 `commerce_reviews` · 공개 범위 `app_heavy`: 장소 리뷰는 앱과 지도 화면이 중심임. 웹 주소 형태는 route table 기준이며 실시간 확인 전임. — 추론
- 정당한 경로(선호 순): `team_export` → `reader_public_page`
  - 업주인 팀은 스마트플레이스에서 자기 업체 리뷰를 먼저 봄(내보내기 형식은 확인하지 못함). — 추론
  - 네이버 오픈 API 명세에는 리뷰 본문을 주는 경로가 없음. 지역 검색 API는 업체 목록만 주며 정렬 옵션은 random(유사도순)과 comment(카페/블로그 리뷰 개수 순)뿐임. — 관찰됨 [P36]
  - routes.json의 naver-terms 항목(confirmed)이 덮음. lift_requires: written_permission 항목은 사용자가 그 항목의 약관 문서를 직접 읽고 access_policy.terms_checked에 result permits_this_reading과 운영사의 사전 서면 허락(permission: granted_by, granted_on, reference)을 함께 적은 실행에서만 풀림. checked_on은 effective_from이 있으면 그날 이후여야 하며, 오늘 이후이거나 365일이 지난 확인은 무효임. lift_requires: never 항목은 풀리지 않음. 에이전트는 확인 항목을 쓰지 않음. 풀린 항목은 모든 호스트를 합쳐 실행당 문서 10건까지 읽음. 페이지 뒤의 내부 데이터 경로는 부르지 않음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `terms_restricted`
- robots 예상 `unknown`: 보고된 robots 정보를 찾지 못함. 약관 제한이 풀린 실행에서 robots 확인이 판정함. — 미확인
- 약관 `confirmed`(routes.json `naver-terms`), 제한 `automated_collection`
  - 조항: "네이버의 사전 허락 없이 자동화된 수단"을 이용하여 "네이버 서비스에 게재된 회원의 아이디(ID), 게시물 등을 수집하거나" 시도해서는 안 됨.
  - 확인: 2026-10-01 네이버 이용약관 원문에서 자동 수집 제한과 2025-07-10 시행일을 읽음. 검색결과 수집 정책도 읽었으나 그 문서의 개정·시행일과 2026-09 개정 여부는 미확인. lift_requires: written_permission에 따라 항목별 사용자 확인과 해당 읽기의 사전 서면 허락이 있어야 풀림. verified_at은 사람이 원문을 읽기 전까지 null임. — 관찰됨 2026-10-01 [P08, P155]
- 사용자 단서(신뢰도 `medium`): 와이즈앱 추정 네이버지도 앱 월평균 사용자 3,044만 명(2025-01~11). 리뷰 작성자 구성은 측정된 적 없음. — 미확인(요약) [P37, P38]
- 콘텐츠 규범:
  - 2026-04-06부터 별점을 다시 기록하고, 3개월 검토 뒤 2026-07-09부터 평균 별점과 사용자별 별점을 공개함. 업주가 평균 별점 노출을 켜고 끌 수 있고, 2021-10 이후 개업한 업체는 기본값이 미노출임. 보이는 평균 별점은 업주가 고른 것이므로 장소끼리 비교하지 않음. — 미확인(요약) [P39, P40, P41]
  - 2026-03-31 보도: 리뷰 이용정책을 고쳐 설명 없이 3점 미만 별점을 무분별하게 주는 행위를 금지 행위에 넣고, 리뷰 수정은 작성 뒤 3개월 안에만 가능하게 함. 낮은 별점의 분포는 이 정책의 영향을 받음. — 미확인(요약) [P41, P42]
  - 리뷰는 방문 인증에 묶임. 2024-10 위치·영수증·실명 인증 강화와 2025-05-12 네이버 POS 연동 인증 추가가 마케팅 커뮤니티 글에 정리돼 있음(신뢰도 낮음). — 미확인(요약) [P43]
- 개인정보:
  - 리뷰에 방문 날짜·동행인·위치가 섞임. 작성자는 author-key로 바꾸고 방문 정보는 요약만 둠. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2021-10-25: 네이버 플레이스 별점 신규 수집 중단(키워드 리뷰 도입) — 미확인(요약) [P44]
  - 2024-10: 네이버 플레이스 리뷰 방문 인증 강화(마케팅 커뮤니티 정리, 신뢰도 낮음) — 미확인(요약) [P43]
  - 2025-05-12: 네이버 플레이스 리뷰에 네이버 POS 연동 인증 추가(마케팅 커뮤니티 정리, 신뢰도 낮음) — 미확인(요약) [P43]
  - 2025-07-10: 네이버 이용약관 개정 시행: 사용자가 삭제·비공개로 돌린 글은 그 뒤 AI 연구 개발에 쓰지 않는다는 내용 보도 — 미확인(요약) [P17, P18]
  - 2026-04-06: 네이버 플레이스 별점 기록 재개 — 미확인(요약) [P39, P40]
  - 2026-07-09: 네이버 플레이스 평균 별점·사용자별 별점 공개 시작. 평균 별점 노출은 업주가 켜고 끔 — 미확인(요약) [P39, P45]
- 확인일 2026-10-01 · verified_at 없음(null)

### `kakao-map` 카카오맵 리뷰

- 호스트: `place.map.kakao.com` · route table id: `kakao-map`
- 계열 `commerce_reviews` · 공개 범위 `app_heavy`: 2025-02 말 웹 개편 뒤 웹에서 '맛집' 평가가 사라지고, 후기는 PC 웹에 최대 3개, 모바일 웹에는 최신·업주 선정·본인 후기만 보인다는 보도가 있음(2025-03-15). 지금의 웹 노출은 확인하지 못함. — 미확인(요약) [P46, P47]
- 정당한 경로(선호 순): `reader_public_page`
  - 카카오 로컬 API는 장소 이름·주소·도로명 주소·전화·분류·좌표·place_url 같은 장소 정보만 주고 리뷰 필드는 없음. 이 스킬은 로컬 API를 쓰지 않음. — 미확인(요약) [P48]
  - 웹에 보이는 후기는 일부뿐이므로 대표성이 없음. 보이지 않는 후기는 수집 공백이며 다른 경로로 메우지 않음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: 없음
- robots 예상 `unknown`: 보고된 robots 정보를 찾지 못함. 실행 때 robots 확인이 판정함. — 미확인
- 약관 `unchecked`: 카카오맵 약관의 자동 수집 조항은 확인하지 못함. 제한이 없다는 뜻이 아니므로 reader의 일반 중단 규칙을 그대로 적용함. — 미확인
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 후기 화면이 개편마다 바뀜. 개편 날짜로 구간을 나눠 읽음. — 추론
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2025-02: 카카오맵 웹 개편: 웹에서 '맛집' 평가가 사라지고 후기 노출이 줄었다는 보도(2025-03-15) — 미확인(요약) [P46, P47]
- 확인일 2026-09-29 · verified_at 없음(null)

### `daum-cafe` 다음 카페

- 호스트: `cafe.daum.net`, `m.cafe.daum.net` · route table id: `daum-cafe`
- 계열 `community` · 공개 범위 `mixed`: 공개 카페와 회원 전용 카페가 있음. 다음 도움말은 카페글 검색이 공개 카페의 검색 공개 게시판 글만 대상으로 한다고 설명함. — 미확인(요약) [P49, P50]
- 정당한 경로(선호 순): `reader_public_page` → `signed_in_authorised`
  - 공개 카페의 공개 게시판만 읽음. 회원 전용 카페와 게시판은 auth_gate로 멈추며 읽거나 요약하지 않음. — 규칙 (`references/research/public-page-access.md`)
  - 회원 전용 카페는 사용자가 브리프에 직접 승인한 카페만 로그인으로 읽고 요약만 남김. — 규칙 (`references/research/public-page-access.md`)
  - 카카오 다음 검색 API는 꺼 둠(소유자가 현행 약관을 읽기 전까지). — 규칙 (`uxresearch/data/routes.json`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `auth_gate`
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 /_c21_/를 막되 home, bbs_search_read, bbs_list, bbs_read 경로를 열어 둠. 이름 있는 AI 그룹은 없음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P136]
- 약관 `unchecked`
  - 조항: 제12조제2호: "회사의 서비스 정보를 이용하여 얻은 정보를 회사의 사전 승낙 없이 복제 또는 유통시키거나 상업적으로 이용하는 행위" 금지.
  - 확인: 2026-09-30 Daum 서비스 약관(2026-09-22 시행)의 복제·유통·상업 이용 제한과 개인정보 수집 금지를 읽음. 카페 약관 제19조도 읽었으나 카페 운영원칙 본문과 자동 수집 허용 범위는 미확인. 사용자 확인 기록은 없으므로 unchecked를 유지하고 일반 중단 규칙을 따름. — 관찰됨 2026-09-30 [P154, P144]
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 카페마다 운영 규칙과 말투가 다름. 카페 단위로 문맥을 읽음. — 추론
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2024-12-01: 블로그·카페 추천·보증 글의 이해관계 표시를 제목이나 첫 부분에 두도록 한 공정위 지침 개정 시행 — 관찰됨 2026-10-01 [P163]
  - 2025-12-01: 카카오가 다음 서비스(카페·티스토리 포함) 운영을 자회사 AXZ로 넘김 — 미확인(요약) [P53, P54]
  - 2026-05-07: 업스테이지가 AXZ 인수를 마침(보도) — 미확인(요약) [P55, P56]
  - 2026-07-27: AXZ가 사명을 '주식회사 다음'으로 바꿨다고 발표(2026-07-20 임시주주총회 의결) — 미확인(요약) [P57, P58, P59]
  - 2026-09-28: 다음이 외부 AI 크롤링 허용 범위를 다시 정하는 중이라는 보도(시행일 미확인) — 미확인(요약) [P51, P52]
- 확인일 2026-09-30 · verified_at 없음(null)

### `tistory` 티스토리

- 호스트: `*.tistory.com` · route table id: `tistory`
- 계열 `blog` · 공개 범위 `public`: 블로그마다 하위 도메인이 따로 있음. 공개 글만 읽음. — 규칙 (`uxresearch/data/routes.json`)
- 정당한 경로(선호 순): `official_feed` → `reader_public_page`
  - 블로그별 /rss 피드는 최근 글만 담음(route table 기준, 실시간 확인 전). — 규칙 (`uxresearch/data/routes.json`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: 없음
- robots 예상 `unknown`: 2026-09-30 관찰: 직접 읽은 개별 블로그는 * 그룹에서 guestbook·manage·owner·admin·search 등만 막고 게시글 경로는 금지 목록에 없음. bingbot은 Crawl-delay: 20임. www.tistory.com/robots.txt는 404를 반환했으며 다른 블로그에도 같은 규칙이 적용된다고 단정하지 않음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P156, P171]
- 약관 `unchecked`
  - 조항: 운영정책 2.②: "서비스를 이용하여 얻은 정보를 회사의 사전 승낙 없이 영리 또는 비영리의 목적으로 복제, 출판, 방송 등에 사용하거나 제3자에게 제공하는 행위" 금지.
  - 확인: 2026-09-30 운영정책의 복제·제공 제한과 공통 Daum 약관을 읽음. 운영정책의 시행일은 표기되지 않았고 자동 수집을 직접 지칭하는 문구는 찾지 못함. 사용자 확인 기록과 자동 수집 허용 범위는 미확인이므로 unchecked를 유지함. — 관찰됨 2026-09-30 [P170, P154]
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 하위 도메인 하나가 작성자 한 명임. — 규칙 (`references/research/source-grading.md`)
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2024-12-01: 블로그·카페 추천·보증 글의 이해관계 표시를 제목이나 첫 부분에 두도록 한 공정위 지침 개정 시행 — 관찰됨 2026-10-01 [P163]
  - 2025-12-01: 카카오가 다음 서비스(카페·티스토리 포함) 운영을 자회사 AXZ로 넘김 — 미확인(요약) [P53, P54]
  - 2026-05-07: 업스테이지가 AXZ 인수를 마침(보도) — 미확인(요약) [P55, P56]
  - 2026-07-27: AXZ가 사명을 '주식회사 다음'으로 바꿨다고 발표(2026-07-20 임시주주총회 의결) — 미확인(요약) [P57, P58, P59]
  - 2026-09-28: 다음이 외부 AI 크롤링 허용 범위를 다시 정하는 중이라는 보도(시행일 미확인) — 미확인(요약) [P51, P52]
- 확인일 2026-09-30 · verified_at 없음(null)

### `dcinside` 디시인사이드

- 호스트: `gall.dcinside.com`, `m.dcinside.com` · route table id: `dcinside`
- 계열 `community` · 공개 범위 `public`: 갤러리 글은 로그인 없이 읽히고, 로그인 없이 글과 댓글도 쓸 수 있다고 보도됨. — 미확인(요약) [P60]
- 정당한 경로(선호 순): `reader_public_page`
  - routes.json의 dcinside-terms 항목(confirmed)이 dcinside.com 전체를 덮음. lift_requires: written_permission 항목은 사용자가 그 항목의 약관 문서를 직접 읽고 access_policy.terms_checked에 result permits_this_reading과 운영사의 사전 서면 허락(permission: granted_by, granted_on, reference)을 함께 적은 실행에서만 풀림. checked_on은 effective_from이 있으면 그날 이후여야 하며, 오늘 이후이거나 365일이 지난 확인은 무효임. lift_requires: never 항목은 풀리지 않음. 에이전트는 확인 항목을 쓰지 않음. 풀린 항목은 모든 호스트를 합쳐 실행당 문서 10건까지 읽음. 이 스킬은 약관이 그 읽기를 허용하는지 판단하지 않음(법률 자문 아님). — 규칙 (`uxresearch/data/routes.json`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `terms_restricted`
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 기본 Allow: /이며 일부 갤러리·개별 글·시스템 경로는 막음. GPTBot·ClaudeBot·PerplexityBot 등 명시 그룹은 Disallow: /임. 모바일도 기본 허용과 일부 경로 금지, www 호스트는 * 그룹 전체 허용을 확인함. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P141, P145, P161]
- 약관 `confirmed`(routes.json `dcinside-terms`), 제한 `automated_collection`
  - 조항: 제16조①: "당사의 사전 서면 동의 없이 어떤 형태로든 어떤 목적으로든 본 서비스를 크롤링하는 행위는 명시적으로 금지됩니다." 제16조②는 AI 학습에 사전 합의를 요구함.
  - 확인: 2026-09-30 원문 제16조와 2026-07-21 시행일을 읽음. 근거 상태는 confirmed이며 해제 조건은 lift_requires: written_permission임. 사용자의 항목별 확인과 해당 읽기의 사전 서면 허락이 필요함. verified_at은 사람이 원문을 읽기 전까지 null임. — 관찰됨 2026-09-30 [P61]
- 사용자 단서(신뢰도 `medium`): 2025-02-10 보도: 2024-12 기준 국내 방문 순위 8위, 하루 약 300만 명이 쓰고 하루 게시글·댓글이 300만 건에 가까움. 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인(요약) [P60]
- 콘텐츠 규범:
  - 갤러리마다 문화와 규범이 따로 자란다고 보도됨. 갤러리 단위로 문맥을 읽음. — 미확인(요약) [P60]
  - 로그인 없는 익명 게시판은 스레드 단위로 셈. — 규칙 (`references/research/source-grading.md`)
- 개인정보:
  - 로그인하지 않은 작성자는 닉네임 옆에 IP 일부가 보임. IP는 지우고, 기본 닉네임 'ㅇㅇ'과 IP가 붙은 닉네임은 author-key가 거절하므로 스레드 키(`author-key --thread-url`)로 셈. — 규칙 (`uxresearch/data/routes.json`)
- 불연속:
  - 2026-02-09: 디시인사이드 경영권 매각 본계약(에이치PE, 약 2,000억 원). 3월 중 대금 납입 예정으로 보도, 종결 여부 미확인 — 미확인(요약) [P63, P64]
- 확인일 2026-09-30 · verified_at 없음(null)

### `fmkorea` 에펨코리아

- 호스트: `www.fmkorea.com`, `fmkorea.com`, `m.fmkorea.com` · route table id: `fmkorea`
- 계열 `community` · 공개 범위 `public`: 공개 게시판 기준. 로그인 없이 읽히는 범위는 실시간 확인 전까지 정하지 않음. — 추론
- 정당한 경로(선호 순): `reader_public_page`
  - 공개 페이지만 읽음. 로그인, 회원 전용, 사람 확인, 봇 차단, 브라우저 확인 화면, 속도 제한이 나오면 그 자리에서 멈추고 수집 공백으로 적음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: 없음
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 Disallow: /와 메인·best·best2·humor 예외를 둠. 학습 크롤러는 메인만 열고, ChatGPT-User·Claude-User·Claude-SearchBot·OAI-SearchBot·Perplexity-User는 Allow: /임. 이 그룹의 허용은 * 그룹의 금지를 풀지 않음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P162]
- 약관 `unchecked`
  - 조항: 제11조①18)는 자동화 프로그램·봇으로 로그인하거나 로그인 사용자 기능을 이용하는 행위와 사이트 내용을 추출해 광고를 제거한 뒤 다시 제공하는 행위를 금지함.
  - 확인: 2026-09-30 이용약관(2023-04-17 시행) 제11조와 제13조를 읽음. 무로그인 표본 읽기의 허용 범위는 미확인이므로 unchecked를 유지함. 보안 시스템의 차단이 나오면 멈춤. — 관찰됨 2026-09-30 [P65]
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 게시판마다 정한 추천 수를 넘은 글이 첫 화면인 '포텐 터짐' 게시판에 모임. 눈에 띄는 글은 투표로 골라진 글이므로 어떤 목록과 정렬에서 읽었는지 기록함. — 미확인(요약) [P67, P68]
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `theqoo` 더쿠

- 호스트: `theqoo.net`, `www.theqoo.net` · route table id: `theqoo`
- 계열 `community` · 공개 범위 `mixed`: 대부분 게시판은 로그인 없이 읽히지만 일상 토크·연애 같은 일부 분류는 로그인해야 읽힘. 로그인하지 않으면 검색이 안 되고 쓴 지 1시간이 안 된 댓글은 보이지 않는다고 알려짐. 가입은 정해진 기간에만 열림(위키 수준 정보). — 미확인(요약) [P69]
- 정당한 경로(선호 순): `reader_public_page`
  - 공개 게시판만 읽음. 로그인이 필요한 분류는 auth_gate이며 수집 공백임. 로그인하지 않은 방문자에게 보이지 않는 최근 댓글도 수집 공백으로 적음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `auth_gate`
- robots 예상 `unknown`: 2026-09-30 관찰: 404를 반환하여 robots 규칙을 읽지 못함. 파일 부재 관찰은 약관 허락을 뜻하지 않으며 실행 때 다시 확인함. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P157]
- 약관 `unchecked`
  - 조항: 제13조3: "회사가 전항 이외의 방법으로 회원의 게시물을 이용하고자 하는 경우 이메일 또는 기타 방식으로 회원의 사전 동의를 얻어야 합니다."
  - 확인: 2026-09-30 이용약관(2023-06-25 시행)을 읽음. 이 조항은 회사의 게시물 이용에 관한 것이며 외부 수집 허락을 주지 않음. 별도 이용지침 본문과 자동 수집 허용 범위는 미확인이므로 unchecked를 유지함. — 관찰됨 2026-09-30 [P158]
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 연예·드라마 같은 대중문화 이야기가 많은 커뮤니티로 소개됨. — 미확인(요약) [P69]
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `nate-pann` 네이트판

- 호스트: `pann.nate.com` · route table id: `nate-pann`
- 계열 `community` · 공개 범위 `public`: 공개 게시판으로 봄. 로그인 규칙은 실시간 확인 전까지 정하지 않음. — 추론
- 정당한 경로(선호 순): `reader_public_page`
  - 공개 페이지만 읽음. 로그인, 회원 전용, 사람 확인, 봇 차단, 브라우저 확인 화면, 속도 제한이 나오면 그 자리에서 멈추고 수집 공백으로 적음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: 없음
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 Disallow: /임. 일부 검색·SNS 봇의 명시 그룹은 /talk/를 열어 두지만 GPTBot·ClaudeBot은 Disallow: /임. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P149]
- 약관 `unchecked`
  - 조항: 제12조제2호는 사전 승낙 없는 서비스 정보의 복제·유통·상업 이용을, 제10호는 다른 이용자의 개인정보 수집·저장·공개를 금지함.
  - 확인: 2026-09-30 판 서비스 약관(2025-02-18 시행)을 읽음. 크롤링·로봇을 직접 지칭하는 문구는 찾지 못했고 자동 수집 허용 범위와 사용자 확인은 미확인이므로 unchecked를 유지함. — 관찰됨 2026-09-30 [P148]
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 일상에 관한 고백적 사연 글이 중심인 커뮤니티로 연구됨. 같은 연구는 독자가 사연 조작을 의심하는 반응과 글쓴이가 진정성을 보이려는 서사 전략을 다룸(대중서사연구 24권 1호, 2018). 익명 1인칭 사연은 어느 게시판에서든 4절의 규칙을 따름. — 미확인(요약) [P70]
- 개인정보:
  - 사연 속 가족·직장·지역 정보는 요약에서 뺌. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `clien` 클리앙

- 호스트: `www.clien.net`, `clien.net` · route table id: `clien`
- 계열 `community` · 공개 범위 `public`: 로그인하지 않아도 글을 읽을 수 있고, 댓글에는 로그인이, 글쓰기·댓글 활동에는 이메일 인증이 필요하다고 안내됨. — 미확인(요약) [P71, P72]
- 정당한 경로(선호 순): `none`
  - clien-terms는 lift_requires: never로 요청 전에 멈추며 캡처도 받지 않음. 제13조③은 정보 권리자의 동의를 요구함. 플랫폼의 허락으로 각 작성자의 동의를 확인할 수 없어 현재 호스트 단위 기록으로는 풀 수 없음. — 규칙 (`uxresearch/data/routes.json`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `terms_restricted`
- robots 예상 `not_reached`: 2026-09-30 관찰: * 그룹은 /service/board/를 열고 sold·hongbo·검색·개인 경로와 쿼리 URL 등을 막음. ChatGPT-User·GPTBot·OAI-SearchBot 등은 Disallow: /임. lift_requires: never 정책은 그대로 적용됨. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P159]
- 약관 `confirmed`(routes.json `clien-terms`), 제한 `automated_collection`
  - 조항: 제13조③: "서비스를 통해 얻은 정보를 그 정보 권리자의 동의없이 수집, 복제, 배포할 수 없습니다." — 관찰됨 [P126]
  - 확인: 2026-09-30 AI 조사자가 운영사 약관 제13조③을 읽음. 근거 상태는 confirmed이며 해제 조건은 never임. 사람이 원문을 확인한 날짜는 없음. — 관찰됨 [P126]
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - IT·기기 이야기가 많은 게시판 구성으로 알려짐. — 미확인(요약) [P72]
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `ppomppu` 뽐뿌

- 호스트: `www.ppomppu.co.kr`, `ppomppu.co.kr`, `m.ppomppu.co.kr` · route table id: `ppomppu`
- 계열 `community` · 공개 범위 `public`: 공개 게시판 중심으로 봄. 성인·본인 인증이 필요한 게시판은 auth_gate로 멈춤. — 규칙 (`references/research/public-page-access.md`)
- 정당한 경로(선호 순): `reader_public_page`
  - 모바일 대체 주소가 route table에 있음(실시간 확인 전). — 규칙 (`uxresearch/data/routes.json`)
  - 공개 페이지만 읽음. 로그인, 회원 전용, 사람 확인, 봇 차단, 브라우저 확인 화면, 속도 제한이 나오면 그 자리에서 멈추고 수집 공백으로 적음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: 없음
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 /zboard/를 열고 검색·개인정보·openapi 등 경로를 막음. 모바일은 Crawl-delay: 1과 검색·개인 경로 금지를 둠. 이름 있는 AI 그룹은 없음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P165, P146]
- 약관 `unchecked`
  - 조항: 제13조2는 사전 승낙 없이 서비스에서 얻은 정보를 복제·전송·출판·배포·방송 등의 방법으로 영리 이용하거나 제3자에게 이용하게 하는 행위를 금지함.
  - 확인: 2026-09-30 이용약관(2015-04-24 시행)을 읽음. 자동 수집 수단을 직접 지칭하는 문구는 찾지 못했고 자동 수집 허용 범위와 사용자 확인은 미확인이므로 unchecked를 유지함. — 관찰됨 2026-09-30 [P166]
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 핫딜 게시판에는 판매 홍보와 제휴 링크 글이 섞임. promotion 표지를 먼저 확인함. — 규칙 (`uxresearch/data/routes.json`)
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `ruliweb` 루리웹

- 호스트: `bbs.ruliweb.com`, `m.ruliweb.com` · route table id: `ruliweb`
- 계열 `community` · 공개 범위 `public`: 공개 게시판 기준. 로그인 규칙은 실시간 확인 전까지 정하지 않음. — 추론
- 정당한 경로(선호 순): `reader_public_page`
  - 모바일 대체 주소도 게시판 경로를 그대로 씀(route table 기준). — 규칙 (`uxresearch/data/routes.json`)
  - 공개 페이지만 읽음. 로그인, 회원 전용, 사람 확인, 봇 차단, 브라우저 확인 화면, 속도 제한이 나오면 그 자리에서 멈추고 수집 공백으로 적음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: 없음
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 검색·타임라인·회원 경로와 여러 쿼리 파라미터를 막음. 게시글 경로는 금지 목록에 없고 이름 있는 AI 그룹은 없음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P134]
- 약관 `unchecked`
  - 조항: 2026-07 이용약관 개정 안내의 제13조4는 허위 사실과 권리 침해, 허위조작정보 생산·유포를 금지함.
  - 확인: 2026-09-30 개정 안내(2026-07-09 시행)를 읽음. 약관 전문을 확보하지 못하여 자동 수집 조항과 허용 범위는 미확인. unchecked를 유지함. — 관찰됨 2026-09-30 [P133]
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 콘솔·휴대용 비디오 게임을 주로 다루는 커뮤니티이며 애니메이션·만화·프라모델 게시판도 있음. 게임마다 공략 게시판이 따로 있음. — 미확인(요약) [P73]
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `instiz` 인스티즈

- 호스트: `www.instiz.net`, `instiz.net` · route table id: `instiz`
- 계열 `community` · 공개 범위 `mixed`: 대부분 글은 로그인 없이 읽히지만 공포·성인 인증 게시판 같은 일부 게시판은 회원 전용이라고 알려짐(위키 수준 정보). — 미확인(요약) [P74]
- 정당한 경로(선호 순): `reader_public_page`
  - 공개 게시판만 읽음. 회원 전용 게시판은 auth_gate이며 수집 공백임. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `auth_gate`
- robots 예상 `unknown`: 보고된 robots 정보를 찾지 못함. 실행 때 robots 확인이 판정함. — 미확인
- 약관 `unchecked`: 약관의 자동 수집 조항은 확인하지 못함. — 미확인
- 사용자 단서(신뢰도 `low`): 공개 사용자 구성 자료를 이번 확인에서 찾지 못함. 커뮤니티 성별·연령·정치 성향 추정치는 싣지 않음(4절). — 미확인
- 콘텐츠 규범:
  - 앱스토어 소개에서 연예계·아이돌 이슈 커뮤니티로 스스로를 소개함. — 미확인(요약) [P75]
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-29 · verified_at 없음(null)

### `blind` 블라인드

- 호스트: `www.teamblind.com`, `teamblind.com` · route table id: `blind`
- 계열 `community` · 공개 범위 `mixed`: 로그인하지 않으면 일부 글만 보임. 회사 채널과 대부분 주제는 회원 전용(auth_gate)임(route table 기준, 실시간 확인 전). — 규칙 (`uxresearch/data/routes.json`)
- 정당한 경로(선호 순): `reader_public_page`
  - 로그인 없이 보이는 글만 읽음. 로그인 읽기는 사용자가 브리프에 직접 승인한 경우에만 가능하며, 에이전트는 이 목록에 커뮤니티를 더하지 않음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `auth_gate`
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 사용자 이력·검색·일부 블로그 내부 경로를 막음. GPTBot·ClaudeBot·Google-Extended 등 학습 크롤러는 Disallow: /임. 이 관찰로 회원 전용 중단이 풀리지 않음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P167]
- 약관 `unchecked`
  - 조항: 3. 금지사항: "Teamblind로부터 명시적 허가를 받은 경우를 제외하고" 자동·수동 수단의 크롤링·스크래핑·데이터 추출·복제 등을 금지함.
  - 확인: 2026-09-30 게시된 약관의 금지사항과 계정 개설 의무를 읽음. 2026-10-04는 예정 시행일이며 읽은 날의 현행 판 시작일은 미확인. 회원 전용 중단을 유지하며 사용자 확인 기록과 현행 판이 미확인이므로 unchecked를 유지함. — 관찰됨 2026-09-30 [P143]
- 사용자 단서(신뢰도 `medium`): 회사 발표(2025-03-12): 전 세계 가입자 1,200만 명. 2025-01 기준 국내 10대 그룹 재직자 10명 중 9명 이상이 가입. 회사 자체 수치임. — 미확인(요약) [P76, P77]
- 콘텐츠 규범:
  - 재직 인증을 거친 직장인 익명 커뮤니티임. — 미확인(요약) [P76]
  - 직장 불만이 모이기 쉬운 구조이므로 일반 대중을 대표하지 않음. — 추론
- 개인정보:
  - 회사 이름·직무·사건을 합치면 사람을 알아볼 수 있음. 회사명과 세부 사건은 요약에서 뺌. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `everytime` 에브리타임

- 호스트: `everytime.kr` · route table id: 없음
- 계열 `community` · 공개 범위 `private`: 학교별 게시판은 학생증 등으로 재학생 인증을 거친 회원만 읽고 쓸 수 있다고 알려짐(위키 수준 정보). — 미확인(요약) [P78]
- 정당한 경로(선호 순): `none`
  - route table의 out_of_scope 채널임. 읽지 않고 요약하지 않음. 학생 사용자는 설문·인터뷰로 조사함. — 규칙 (`uxresearch/data/routes.json`)
- 예상 중단: `auth_gate`
- robots 예상 `not_reached`: 2026-09-30 관찰: * 그룹은 Disallow: /이며 메인과 일부 광고·아이콘 경로만 예외로 둠. 회원 전용·범위 밖 정책이 적용됨. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P140]
- 약관 `unchecked`
  - 조항: 제12조는 프로그램·스크립트·봇 등 컴퓨팅 시스템을 통한 서비스 접근을 금지하며, 제9조는 회사 승인 없는 데이터베이스 복제·배포·방송·전송을 금지함.
  - 확인: 2026-09-30 약관 본문과 2026-08-07 개정일을 읽음. 사용자 확인 기록은 없으므로 unchecked를 유지함. 회원 전용 채널은 계속 범위 밖이며 이 관찰은 읽기 경로를 만들지 않음. — 관찰됨 2026-09-30 [P139]
- 사용자 단서(신뢰도 `low`): 싣지 않음. 회원 전용 채널은 사용자 단서로 삼지 않음(1절). 학생 사용자는 설문·인터뷰로 조사함. — 규칙
- 확인일 2026-09-30 · verified_at 없음(null)

### `band` 네이버 밴드

- 호스트: `band.us` · route table id: 없음
- 계열 `community` · 공개 범위 `private`: 모임 단위 멤버 전용 서비스로 다룸. route table은 band.us 전체를 out_of_scope로 둠. — 규칙 (`uxresearch/data/routes.json`)
- 정당한 경로(선호 순): `none`
  - 읽지 않고 요약하지 않음. 50-60대 사용자는 공개 웹 글보다 설문·인터뷰로 조사함. — 규칙 (`uxresearch/data/routes.json`)
- 예상 중단: `auth_gate`
- robots 예상 `not_reached`: out_of_scope 채널이라 요청하지 않음. — 규칙 (`uxresearch/data/routes.json`)
- 약관 `unchecked`: 읽지 않는 채널이라 약관을 확인하지 않음. — 규칙 (`uxresearch/data/routes.json`)
- 사용자 단서(신뢰도 `low`): 싣지 않음. 멤버 전용 서비스는 사용자 단서로 삼지 않음(1절). 이 채널의 사용자는 설문·인터뷰로 조사함. — 규칙
- 확인일 2026-09-29 · verified_at 없음(null)

### `kakaotalk-openchat` 카카오톡 오픈채팅

- 호스트: `open.kakao.com` · route table id: 없음
- 계열 `community` · 공개 범위 `private`: 채팅방은 참여해야 보임. route table은 out_of_scope로 둠. — 규칙 (`uxresearch/data/routes.json`)
- 정당한 경로(선호 순): `none`
  - 읽지 않고 요약하지 않음. — 규칙 (`uxresearch/data/routes.json`)
- 예상 중단: `auth_gate`
- robots 예상 `not_reached`: out_of_scope 채널이라 요청하지 않음. — 규칙 (`uxresearch/data/routes.json`)
- 약관 `unchecked`: 읽지 않는 채널이라 약관을 확인하지 않음. — 규칙 (`uxresearch/data/routes.json`)
- 사용자 단서(신뢰도 `low`): 싣지 않음. 참여해야 보이는 채팅방은 사용자 단서로 삼지 않음(1절). — 규칙
- 확인일 2026-09-29 · verified_at 없음(null)

### `daangn` 당근(동네생활)

- 호스트: `www.daangn.com`, `daangn.com` · route table id: `daangn`
- 계열 `community` · 공개 범위 `app_heavy`: 앱이 중심이며 공개 웹 페이지가 있는 글만 대상임. 공개 범위는 실시간 확인 전까지 정하지 않음. — 추론
- 정당한 경로(선호 순): `reader_public_page`
  - daangn-terms는 사용자의 현행 약관 확인과 사전 서면 허락이 있어야 풀림(lift_requires: written_permission). 허락은 해당 수집·저장·분석과 후속 처리를 포함해야 함. 그 뒤에도 robots.txt와 모든 중단 규칙을 따름. 사이트 내부 데이터 경로는 부르지 않음. — 규칙 (`uxresearch/data/routes.json`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `terms_restricted`
- robots 예상 `not_reached`: 2026-09-30 관찰: * 그룹은 광고·관리·웹뷰·검색 경로 등을 막음. ChatGPT-User·Claude-User·Claude-SearchBot·OAI-SearchBot·Perplexity-User 등은 전체 금지와 일부 지역 프로필 예외를 둠. 학습 크롤러 그룹은 Disallow: /임. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P160]
- 약관 `reported`(routes.json `daangn-terms`), 제한 `automated_collection`, `ai_input`, `storage`
  - 조항: 데이터베이스에 대한 보호: "당근의 명시적인 사전 서면 동의 없이 자동화된 도구"를 활용한 "데이터 수집·복제·저장·배포·출판·분석·색인화·수정·파생 저작물 생성" 금지. — 관찰됨 [P127, P128]
  - 확인: 2026-09-30 AI 조사자가 운영사 페이지 데이터에서 조항과 2026-01-02 효력일을 읽음. 다른 조사자의 약관 페이지 요청은 실패하여 reported로 둠. 사람이 원문을 확인한 날짜는 없음. — 관찰됨 [P127, P128]
- 사용자 단서(신뢰도 `medium`): 와이즈앱: 2025-08 사용자 2,185만 명, 40대 비중 30.3%로 가장 큼. 2026-08 사용자 2,317만 명(보도). 앱 사용자 수이며 글쓴이 구성이 아님. — 미확인(요약) [P84, P85]
- 콘텐츠 규범:
  - 중고거래·동네 이야기·동네 가게 홍보가 섞인 동네 단위 채널임. — 추론
- 개인정보:
  - 동네 이름·닉네임·거래 장소는 개인 정보에 가까움. 공유 산출물에서 뺌. — 규칙 (`uxresearch/data/routes.json`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `youtube` 유튜브 댓글

- 호스트: `www.youtube.com`, `youtube.com`, `m.youtube.com`, `youtu.be` · route table id: `youtube`
- 계열 `video` · 공개 범위 `public`: 영상과 댓글은 공개지만 약관이 자동화 접근을 막으므로 페이지는 읽지 않음. 댓글은 Data API로만 받음. — 규칙 (`uxresearch/data/routes.json`)
- 정당한 경로(선호 순): `official_api_user_key`
  - YouTube Data API v3를 사용자 본인의 키로 부르는 공식 경로(R0)만 씀. 영상 주소(watch, youtu.be, shorts, live, embed)에서 영상 ID만 읽고 페이지는 요청하지 않음. 키는 환경 변수 REMORSEARCH_YOUTUBE_API_KEY에서 읽고 예전 이름 YOUTUBE_API_KEY도 받음. videos.list와 commentThreads.list를 쓰며, 렌더 캡처는 하지 않고 ingest도 그 캡처를 받지 않음. 채널·커뮤니티·재생목록·검색 페이지는 경로가 없어 terms_restricted 수집 공백으로 남음. — 규칙 (`uxresearch/data/routes.json`)
  - 댓글은 관련도 순으로 받은 최상위 댓글이며 한 영상에 정해진 쪽 수까지만 받음(쪽 크기와 쪽 수는 routes.json의 youtube 경로 설정). 답글과 그 뒤의 댓글은 수집 공백으로 적음. — 규칙 (`uxresearch/data/routes.json`)
  - commentThreads.list는 호출당 1단위임. 기본 할당은 search.list 하루 100회, videos.insert 하루 100회와 별도로 나머지 엔드포인트를 합쳐 하루 10,000단위이며, 일일 할당량은 태평양 시간 자정에 초기화됨. — 관찰됨 2026-09-30 [P86, P87, P88]
  - 개발자 정책 III.E.4.d: 사용자 자격 증명 없이 API 클라이언트가 접근할 수 있는 API Data가 Non-Authorized Data임. 저장한 데이터는 30일 뒤 삭제하거나 갱신해야 함. — 관찰됨 2026-09-30 [P89]
  - 개발자 정책은 승인 없이 API Data로 새 데이터·파생 데이터·지표를 만들지 못하게 함. 파생 지표의 예로 시청자 감정 분석과 콘텐츠 분류·태그를 듦. API 키 보유자는 YouTube API Services Terms of Service와 Developer Policies를 따라야 함. 적용은 법률가 판단이며, 그동안 API 항목은 정성 근거(풀어 쓰기, 짧은 인용의 존재 근거)로만 씀. API 항목으로 감정·분류·개수 지표를 계산하지 않음. — 미확인(요약) [P89, P125]
  - 나이·인종·종교·정치 성향·성적 지향·건강 상태 같은 보호 속성으로 사용자를 프로파일링하거나 시청자·제작자의 이런 속성을 추정해서는 안 됨. — 미확인(요약) [P89]
  - 키가 없으면 official_route_needs_key로 수집 공백이 되고 사용자에게 묻는 질문이 됨. 키 거절이나 그 밖의 실패로 공식 경로가 끝나면 그 주소는 terms_restricted로 끝나며 페이지로 바꾸지 않음. 댓글을 막은 영상은 gone(comments_disabled)으로 기록함. — 규칙 (`uxresearch/data/routes.json`)
- 예상 중단: `terms_restricted`
- robots 예상 `not_reached`: 2026-09-30 관찰: * 그룹은 내부 API·댓글·검색·로그인·live_chat·feeds/videos.xml 등을 막으며 /watch는 금지 목록에 없음. 페이지는 lift_requires: never로 계속 멈추고 Data API만 씀. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P172]
- 약관 `confirmed`(routes.json `youtube-terms`), 제한 `automated_collection`
  - 조항: Permissions and Restrictions: automated access requires YouTube’s prior written permission, except for public search engines following robots.txt.
  - 확인: 2026-09-30 원문의 자동화 접근 제한을 읽음. 영문 페이지의 날짜가 2023-12-15와 한국 화면의 영문 번역 2022-01-05로 달라 효력일은 미확인. lift_requires: never이므로 페이지는 풀 수 없고 공식 Data API만 씀. verified_at은 사람이 원문을 읽기 전까지 null임. — 관찰됨 2026-09-30 [P173, P174, P89]
- 사용자 단서(신뢰도 `medium`): 와이즈앱 추정 월평균 사용자 4,678만 명(2025-01~11). 한국갤럽 2025(만 13세 이상): 유튜브를 쓴다는 응답 95%. 한국언론진흥재단 2024(만 19세 이상): 84.9%. 조사마다 정의가 다름. 댓글 작성자는 그 영상을 본 사람 가운데 스스로 쓴 사람임. — 미확인(요약) [P37, P81, P82]
- 콘텐츠 규범:
  - 댓글은 특정 영상에 묶이고 정렬 순서에 따라 보이는 댓글이 달라짐. 어떤 정렬로 받았는지 기록함. — 추론
  - 공정위 2024년 SNS 뒷광고 모니터링에서 유튜브 의심 게시물은 1,409건. 적발 건수일 뿐 비율이 아님. — 미확인(요약) [P14, P15]
- 개인정보:
  - 작성자 이름은 솔트를 넣은 작성자 키로 바꾸고 채널 ID와 프로필 URL은 저장하지 않음. API로 받은 항목마다 retention_until(받은 시각 + 30일)을 두며, 사용자가 그 기한까지 지우거나 다시 받아야 함. 번들 항목을 자동으로 지우는 기능은 아직 없음. — 규칙 (`uxresearch/data/routes.json`)
  - 작성자 키에 나이·건강·정치 같은 단서를 붙이지 않음. 이런 단서는 세그먼트 수준 주장에만 씀. — 규칙 (`uxresearch/data/routes.json`)
- 확인일 2026-09-30 · verified_at 없음(null)

### `instagram` 인스타그램

- 호스트: `www.instagram.com`, `instagram.com` · route table id: `instagram`
- 계열 `microblog` · 공개 범위 `mixed`: 공개 계정과 비공개 계정이 있음. 공개 계정도 약관 때문에 읽지 않음. — 추론
- 정당한 경로(선호 순): `none`
  - Meta Content Library와 API는 자격을 갖춘 학술·비영리 연구자가 ICPSR 심사를 거쳐 쓰는 별도 경로이며, 이 스킬의 경로가 아님. — 미확인(요약) [P91, P92, P93]
- 예상 중단: `terms_restricted`
- robots 예상 `not_reached`: 2026-09-30 관찰: * 그룹은 Disallow: /이며 GPTBot·ClaudeBot·PerplexityBot 등도 전체 경로를 막음. 페이지는 lift_requires: never로 계속 멈춤. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P164]
- 약관 `confirmed`(routes.json `meta-instagram`), 제한 `automated_collection`
  - 조항: Operator robots.txt notice: "Collection of data on Instagram through automated means is prohibited unless you have express written permission from Instagram".
  - 확인: 2026-09-30 운영사의 robots.txt 공지와 Meta 자동 수집 조항을 읽음. 인스타그램 약관 자체의 본문과 시행일은 미확인. lift_requires: never이므로 페이지는 풀 수 없음. verified_at은 사람이 원문을 읽기 전까지 null임. — 관찰됨 2026-09-30 [P164, P94]
- 사용자 단서(신뢰도 `medium`): 한국언론진흥재단 2024(만 19세 이상): 20대 80.9%, 30대 70.7%가 씀. 와이즈앱 추정 2026-01~04 월평균 사용자 2,808만 명. — 미확인(요약) [P22, P82, P83]
- 콘텐츠 규범:
  - 공정위 2024년 모니터링에서 뒷광고 의심 게시물이 가장 많았던 채널임(10,195건). 적발 건수일 뿐 비율이 아님. — 미확인(요약) [P14, P15]
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2024-10-07: Meta 자동 데이터 수집 약관 현행본 시행 — 미확인(요약) [P94]
- 확인일 2026-09-30 · verified_at 없음(null)

### `threads` 스레드

- 호스트: `threads.com`, `www.threads.com`, `threads.net`, `www.threads.net` · route table id: `threads`
- 계열 `microblog` · 공개 범위 `mixed`: 공개·비공개 프로필이 있음. 공개 프로필도 약관 때문에 읽지 않음. — 추론
- 정당한 경로(선호 순): `none`
  - Threads API의 키워드 검색은 threads_keyword_search 권한이 필요하고, 그 권한을 승인받지 못한 앱은 인증한 사용자 자신의 글만 검색함. 이 스킬은 구현하지 않음. — 미확인(요약) [P96]
- 예상 중단: `terms_restricted`
- robots 예상 `not_reached`: 2026-09-30 관찰: * 그룹은 Disallow: /이며 GPTBot·ClaudeBot·PerplexityBot 등도 전체 경로를 막음. threads.net은 threads.com으로 이동함. 페이지는 lift_requires: never로 계속 멈춤. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P168, P169]
- 약관 `confirmed`(routes.json `meta-threads`), 제한 `automated_collection`
  - 조항: Operator robots.txt notice: "Collection of data on Threads through automated means is prohibited unless you have express written permission from Threads".
  - 확인: 2026-09-30 운영사의 robots.txt 공지와 Meta 자동 수집 조항을 읽음. 스레드 보충약관 본문과 시행일은 미확인. lift_requires: never이므로 페이지는 풀 수 없음. verified_at은 사람이 원문을 읽기 전까지 null임. — 관찰됨 2026-09-30 [P168, P94]
- 사용자 단서(신뢰도 `medium`): 와이즈앱: 2026-01~04 월평균 사용자 729만 명, 전년 같은 기간보다 21.0% 늘어남. — 미확인(요약) [P22, P23]
- 콘텐츠 규범:
  - 반말 중심의 가벼운 말투가 퍼졌다는 보도가 있음. — 미확인(요약) [P98, P99]
  - 말투와 높임 수준은 나이·성별 단서가 아님. — 규칙 (`references/research/korea/query-craft.md`)
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2025-04-24: 스레드 기본 주소가 threads.com으로 바뀌고 threads.net은 threads.com으로 넘어감 — 미확인(요약) [P100]
- 확인일 2026-09-30 · verified_at 없음(null)

### `app-store-kr` 앱스토어 리뷰(한국)

- 호스트: `apps.apple.com`, `itunes.apple.com` · route table id: `app-store`
- 계열 `app_store_reviews` · 공개 범위 `public`: 앱 페이지의 리뷰는 공개임. 나라(스토어)마다 리뷰가 따로 모임. — 추론
- 정당한 경로(선호 순): `team_export`
  - apple-app-store-terms는 apps.apple.com 페이지와 itunes.apple.com 피드를 요청 전에 멈춤(lift_requires: never). 공개 고객 리뷰 RSS 실행 경로는 제거함. 리뷰 피드가 200으로 응답했다는 조사 기록과 기존 소개 글은 경로의 과거 근거로만 남김. — 규칙 [P101] (`uxresearch/data/routes.json`)
  - 팀 자기 앱의 리뷰는 허가받은 App Store Connect 내보내기 파일로 받음(team_export, 출처 team_provided). 앱·국가·기간·취득 경위를 남기고 처리 범위와 개인정보를 확인함. — 관찰됨 [P102, P129]
- 예상 중단: `terms_restricted`
- robots 예상 `not_reached`: 2026-09-30 관찰: * 그룹은 WebObjects·api·includes·v1·검색 쿼리 경로를 막고 앱 상세 페이지는 금지 목록에 없음. AI 명시 그룹은 없음. 페이지·리뷰 피드는 lift_requires: never로 계속 멈춤. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P132]
- 약관 `confirmed`(routes.json `apple-app-store-terms`), 제한 `automated_collection`, `ai_input`
  - 조항: F: "소프트웨어, 기기, 자동화된 프로세스 또는 이와 유사하거나 동등한 수동 프로세스"를 사용한 "스크래핑, 복사, 측정, 분석 또는 모니터링" 금지. — 관찰됨 [P130, P131, P129]
  - 확인: 2026-09-30 AI 조사자가 Apple 미디어 서비스 약관 F절을 읽음. 2026-09-14는 최종 업데이트 날짜이며 효력일은 확인하지 못함. 피드별 예외 조항을 찾지 못함. 사람이 원문을 확인한 날짜는 없음. — 관찰됨 [P130, P131, P129]
- 사용자 단서(신뢰도 `medium`): 한국갤럽 2025-07 조사(만 18세 이상 1,001명, 스마트폰 사용자 986명): 주로 쓰는 스마트폰은 삼성 72%, 애플 24%. 애플은 18-29세에서 60%, 60세 이상에서 4%. 여성 27%, 남성 21%가 애플을 쓴다고 보도됨. 스마트폰 사용자 기준이며 리뷰 작성자 구성이 아님. 리뷰 작성자 구성은 측정된 적 없음(단서만). — 미확인(요약) [P103, P104, P105]
- 콘텐츠 규범:
  - 스토어 리뷰는 업데이트나 장애 직후 몰림. 리뷰가 몰린 기간은 사용성 발견이 아니라 맥락이며, 날짜 구간을 나눠 읽음. — 추론
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2025-09-23: 카카오톡 대규모 개편 직후 두 스토어 평점이 급락함(보도 시점마다 수치가 다름) — 미확인(요약) [P106, P107]
- 확인일 2026-09-30 · verified_at 없음(null)

### `google-play-kr` 구글 플레이 리뷰(한국)

- 호스트: `play.google.com` · route table id: `google-play`
- 계열 `app_store_reviews` · 공개 범위 `public`: 앱 페이지의 리뷰는 공개지만 클릭 없이 보이는 리뷰는 일부임. — 추론
- 정당한 경로(선호 순): `team_export` → `reader_public_page`
  - Play Developer API의 reviews.list는 팀 자기 앱에서 최근 1주일 안에 쓰이거나 고친 리뷰만 줌. 더 긴 기간은 Play Console의 CSV 내보내기로 받음. — 미확인(요약) [P108, P109]
  - 공개 페이지는 클릭 없이 처음 몇 개 리뷰만 보여 줌. 렌더는 스크롤만 하고 더 보기 버튼을 누르지 않음. — 규칙 (`references/research/public-page-access.md`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: 없음
- robots 예상 `unknown`: 2026-09-30 관찰: * 그룹은 /store/getreviews·/store/xhr·/store/search 등 내부·검색 경로를 막음. /store/apps/details는 금지 목록에 없고 AI 명시 그룹은 없음. 실행 때 현재 URL의 robots와 기록된 중단을 다시 판정함. — 관찰됨 2026-09-30 [P152]
- 약관 `unchecked`
  - 조항: Google 약관은 robots.txt 등 기계 판독 지시를 어기는 자동 접근을 금지함. Google Play 약관은 계정명 등 다른 사용자의 개인정보 수집을 금지함.
  - 확인: 2026-09-30 Google 서비스 약관(2026-07-30 시행)과 Google Play 약관(2026-07-29 판)을 읽음. 한국어 Play 페이지도 같은 날 읽음. 사용자 확인은 미확인이므로 unchecked를 유지하고 robots 및 개인정보 중단 규칙을 따름. — 관찰됨 2026-09-30 [P153, P150, P151]
- 사용자 단서(신뢰도 `medium`): 한국갤럽 2025-07 조사(스마트폰 사용자 986명): 삼성 72%. 50대·60대는 90% 안팎이 삼성. 남성 76%, 여성 67%가 삼성을 쓴다고 보도됨. 스마트폰 사용자 기준이며 리뷰 작성자 구성은 측정된 적 없음(단서만). — 미확인(요약) [P103, P104, P105]
- 콘텐츠 규범:
  - 스토어 리뷰는 업데이트나 장애 직후 몰림. 리뷰가 몰린 기간은 사용성 발견이 아니라 맥락이며, 날짜 구간을 나눠 읽음. — 추론
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2025-09-23: 카카오톡 대규모 개편 직후 두 스토어 평점이 급락함(보도 시점마다 수치가 다름) — 미확인(요약) [P106, P107]
  - 2025-10-02: 카카오톡 구글 플레이 평점 1.0 보도: 평가자 318만 5,098명 중 312만 4,788명(98.11%)이 1점 — 미확인(요약) [P106]
- 확인일 2026-09-30 · verified_at 없음(null)

### `coupang` 쿠팡 상품 리뷰

- 호스트: `www.coupang.com`, `m.coupang.com` · route table id: `coupang`
- 계열 `commerce_reviews` · 공개 범위 `public`: 상품 페이지의 리뷰는 공개지만 reader가 읽을 수 있는지는 약관과 robots가 정함. — 추론
- 정당한 경로(선호 순): `team_export` → `reader_public_page`
  - 판매자인 팀은 자기 상품 리뷰 자료를 먼저 씀(형식은 확인하지 못함). — 추론
  - routes.json의 coupang-terms 항목(reported)이 덮음. lift_requires: written_permission 항목은 사용자가 그 항목의 약관 문서를 직접 읽고 access_policy.terms_checked에 result permits_this_reading과 운영사의 사전 서면 허락(permission: granted_by, granted_on, reference)을 함께 적은 실행에서만 풀림. checked_on은 effective_from이 있으면 그날 이후여야 하며, 오늘 이후이거나 365일이 지난 확인은 무효임. lift_requires: never 항목은 풀리지 않음. 에이전트는 확인 항목을 쓰지 않음. 풀린 항목은 모든 호스트를 합쳐 실행당 문서 10건까지 읽음. 그 뒤에도 robots.txt가 허용할 때만 읽음. — 규칙 (`uxresearch/data/routes.json`)
  - 봇 차단(bot_filter)과 브라우저 확인 화면(js_check)은 opted_out이며 등록 도메인 전체를 이번 실행에서 멈춤. 거절 뒤에는 모바일 대체 주소나 렌더로 다시 열지 않고 확인 화면이 풀리기를 기다리지 않음. 확인 화면을 거친 캡처는 ingest가 받지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: `terms_restricted`, `opted_out`
- robots 예상 `reported_closed`: 보도(2026-04-27 분석, 2026-09-02 기준 분석): robots.txt가 검색엔진 봇에만 상품 경로를 열고 나머지 봇은 막으며, OpenAI의 GPTBot·ChatGPT-User·OAI-SearchBot을 이름으로 막음. 그대로라면 reader는 opted_out에서 멈춤. 실행 때 robots 확인이 판정함. — 미확인(요약) [P111, P112]
- 약관 `reported`(routes.json `coupang-terms`), 제한 `automated_collection`
  - 조항: 쿠팡 기업 사이트(aboutcoupang.com) 이용약관: 자동화된 에이전트나 스크립트로 자동 검색·요청·쿼리를 만들거나 데이터를 마이닝하는 행위를 금지하고, robots.txt를 따르는 공용 검색엔진 스파이더에만 색인용 복사를 조건부로 허락함. 쇼핑 사이트(coupang.com) 회원 약관의 같은 취지 조항은 검색 요약으로만 봄.
  - 확인: 원문은 이 환경에서 열리지 않음(미확인). routes.json의 coupang-terms 항목과 같은 상태임. 사용자의 항목별 약관 확인과 사전 서면 허락(permission: granted_by, granted_on, reference)이 제한을 모두 풀기 전까지 요청하지 않음(1절). — 미확인(요약) [P113, P114]
- 사용자 단서(신뢰도 `medium`): 와이즈앱 추정 월평균 사용자 3,388만 명(2025-01~11). — 미확인(요약) [P37, P38]
- 콘텐츠 규범:
  - 공정위(2024-08)는 쿠팡이 검색 순위를 조작하고 임직원 2,297명을 동원해 자체 브랜드(PB) 상품에 후기 72,614개를 달았다는 혐의로(수치는 의결서 요약 기준, `references/research/korea/promotion.md` 4g) 과징금 1,628억 원을 부과함. 쿠팡은 서울고법에 취소 소송을 냈고, 시정명령은 집행정지로 효력이 멈췄으나 과징금은 내도록 했다는 보도가 있음. 본안 결과는 확인하지 못함. — 미확인(요약) [P115, P116, P117]
  - 플랫폼 자체 브랜드 상품의 리뷰는 다른 채널 계열의 근거가 있어야 셈. — 규칙 (`references/research/korea/promotion.md`)
  - 리뷰 보상 표시가 있는 리뷰는 만족·선호·반대 근거 검색·별점 평균에서 D까지만 인정하고, 불만과 대처 방법은 한 단계만 낮춤(최소 C). 판매자나 게시판의 보상 공지는 리뷰별 후보로 검증자에게 넘기며 페이지 전체를 자동으로 낮추지 않음. 플랫폼 전체의 리뷰 적립 제도와 판매자가 여는 리뷰 이벤트는 구분함. — 규칙 (`references/research/korea/promotion.md`)
- 개인정보:
  - 작성자 이름·닉네임은 author-key로 바꾸고, 글 URL은 번들의 source_ref에만 둠. 인용은 300자 이하이고 풀어 쓰기를 먼저 씀. — 규칙 (`references/research/public-page-access.md`)
- 불연속:
  - 2024-08: 자체 브랜드 상품 검색 순위 조작·임직원 후기 혐의로 공정위 과징금 부과 — 미확인(요약) [P115]
  - 2024-09: 쿠팡이 서울고법에 과징금·시정명령 취소 소송 제기 — 미확인(요약) [P116]
- 확인일 2026-09-29 · verified_at 없음(null)

### `delivery-apps` 배달앱 리뷰(배달의민족·쿠팡이츠·요기요)

- 호스트: 없음(앱 전용) · route table id: 없음
- 계열 `commerce_reviews` · 공개 범위 `app_only`: 리뷰는 앱 안에서만 보임. — 추론
- 정당한 경로(선호 순): `team_export`
  - 입점 업주인 팀은 자기 가게 리뷰를 먼저 씀(내보내기 형식은 확인하지 못함). 앱 트래픽이나 내부 API는 쓰지 않음. — 규칙 (`references/research/public-page-access.md`)
- 예상 중단: 없음
- robots 예상 `not_reached`: 공개 웹 페이지가 없어 요청하지 않음. — 규칙 (`references/research/public-page-access.md`)
- 약관 `unchecked`: 읽지 않는 채널이라 약관을 확인하지 않음. — 규칙 (`uxresearch/data/routes.json`)
- 사용자 단서(신뢰도 `medium`): 와이즈앱 추정 배달의민족 월평균 사용자 2,226만 명(2025-01~11). — 미확인(요약) [P37, P38]
- 콘텐츠 규범:
  - 한국소비자원 2024-07-23 발표(최근 1년 안에 배달앱을 쓴 소비자 1,000명 설문, 자기 보고): 773명(77.3%)이 리뷰를 썼고, 그중 504명(65.2%)이 리뷰 이벤트 참여를 위해 씀. 참여자 가운데 401명(79.6%)은 이벤트가 별점에 영향을 줬다고 했고, 그중 394명(98.3%)은 실제 만족도보다 높은 별점을 줬다고 답함. 394명은 이벤트 참여자 504명의 약 78%임. — 미확인(요약) [P118, P119, P120]
  - 리뷰 이벤트가 도는 곳의 별점 평균은 만족도 근거로 쓰지 않음. 보상 표시가 있는 리뷰의 등급은 promotion.md 4d를 따름. — 규칙 (`references/research/korea/promotion.md`)
- 개인정보:
  - 리뷰에 주소·동·주문 내용이 섞임. 요약에서 뺌. — 규칙 (`references/research/public-page-access.md`)
- 확인일 2026-09-29 · verified_at 없음(null)

## 4. 커뮤니티 콘텐츠 규범(코퍼스 수준)

커뮤니티 사이의 차이는 사람의 특성이 아니라 콘텐츠 규범으로 적습니다. 커뮤니티의 성별·연령·정치 성향 추정치는
게시자, 주장, 페르소나 어디에도 붙이지 않습니다. 웹 트래픽 패널이 모델로 추정한 커뮤니티 성비나 위키가 인용한
성비는 커뮤니티 구성을 재는 자료가 아니므로 이 지도에 싣지 않습니다. 아래 항목은 JSON의 `corpus_norms`와
같습니다.

- 정치적 견해는 민감정보임(개인정보 보호법 제23조①. 법률 제21445호, 2026-09-11 시행판을 공개 저장소 사본으로 읽음. 문구는 2016-03-29 개정 뒤 그대로임). 커뮤니티 성향 추정치를 한 사람에게 붙이면 그 사람의 정치적 견해를 새로 추정하는 셈이 될 수 있으므로 하지 않음(추론). 법률 자문 아님. — 미확인(미러) [P121, P122] (`references/research/korea/legal-checklist.md` L10)
- 국내 방문자가 많은 커뮤니티 11곳의 2015-2022년 글과 댓글 396,496건으로 만든 혐오 표현 코퍼스 연구(PLOS ONE 19권 5호, 2024)는 대부분의 커뮤니티에서 정치 성향과 연령 차이에 따른 양극화가 혐오 표현을 이끌고, 다른 커뮤니티에서는 사회적 소수자에 대한 주변화가 두드러진다고 보고함. 성별을 겨냥한 혐오 글의 비중은 2018년에 크게 늘었다가 2019년 이후 줄었고, 연령을 겨냥한 혐오는 2021년에 치솟음. 코퍼스 전체의 경향이며 어느 커뮤니티의 사람도 설명하지 않음. — 미확인(요약) [P123, P124]
- 이 지도는 커뮤니티별 성향 위치(어느 커뮤니티가 어느 쪽인지)를 싣지 않음. 연구가 커뮤니티 이름을 들더라도 그 결과를 한 게시자, 한 주장, 한 페르소나로 옮기지 않음. — 규칙
- 비꼼, 반어, 밈이 흔한 게시판에서는 글의 극성(칭찬인지 비꼼인지)을 부모 글과 앞뒤 댓글과 함께 판단하고, 판단이 서지 않으면 극성 불확실로 둠. — 규칙 (`references/research/korea/query-craft.md`)
- 익명 1인칭 사연은 어느 게시판에서든 사실 확인이 안 된 진술로 다루고 narrative_unverified 주의 표시를 붙임. 존재 근거로만 쓰고, 보고서에는 "작성자는 ~라고 적었습니다 (작성자 진술, 사실 여부 미확인)"처럼 적음. — 규칙 (`references/research/korea/report-template.md`)
- 말투(반말·존댓말), 호칭, 은어는 나이·성별·정치 성향의 단서가 아님. — 규칙 (`references/research/korea/query-craft.md`)
- 로그인 없는 익명 게시판은 스레드 단위로 셈. 기본 익명 닉네임(ㅇㅇ 등, uxresearch/data/markers.json의 anonymous_handles)과 IP 일부가 붙은 닉네임은 신원이 아니며 scripts/ux_research.py author-key가 거절함. 이런 글은 --thread-url로 스레드 키를 받음. — 규칙 (`references/research/source-grading.md`)
- 추천으로 골라진 목록(예: 에펨코리아의 '포텐 터짐', 지식iN의 UP 투표 정렬)과 정렬 순서는 눈에 띄는 글을 바꿈. 어떤 목록과 정렬에서 읽었는지 기록함. — 규칙
- 협찬·제휴·리뷰 보상 표지는 promotion.md에 따라 먼저 확인함. 표지가 없다고 순수 후기로 보지 않음. 경쟁 업체를 깎아내리는 글처럼 부정적인 판촉도 있음. — 규칙 (`references/research/korea/promotion.md`)
- 미성년자로 보이는 사람의 글은 건너뛰고, 아이 이름·학교·병원·동네 같은 세부를 남기지 않음. — 규칙 (`references/research/korea/legal-checklist.md`)
- 이 규범은 모든 채널에 고르게 적용함. 채널별 콘텐츠 규범은 그 채널에서 확인된 글의 형식(투표 선별, 사연 중심, 협찬 비중 등)이며 게시자의 특성이 아님. — 규칙

## 5. 공개 웹에서 덜 잡히는 사용자

- 50-60대와 학생: 공개 웹 글보다 회원 전용 서비스에서 많이 활동한다고 조사됨. 이 스킬은 그런 서비스를 읽지 않으므로 서비스 이름을 단서로 싣지 않음 — 미확인(요약) [P81, P82, P83]
- 닫힌 카페와 회원 전용 게시판: 승인된 커뮤니티가 아니면 읽지 않고 요약하지도 않음. 이 지도는 그런 커뮤니티를 단서로
  이름 대지 않음 — 규칙 (`references/research/public-page-access.md`)

이 사용자 집단은 설문, 인터뷰, 팀 자체 자료로 조사합니다. 공개 웹에서 결과가 적다고 그 집단이 없다고 보지 않습니다.
보고서에는 덜 잡힌 집단을 수집 공백으로 적습니다.

## 6. 스토어·리뷰 편향

- 스마트폰 브랜드: 한국갤럽 2025-07 조사(스마트폰 사용자 986명)에서 주로 쓰는 스마트폰은 삼성 72%, 애플 24%임.
  애플은 18-29세에서 60%, 60세 이상에서 4%이고, 여성 27%·남성 21%가 애플을 쓴다고 보도됨. 아이폰 사용자는 더 젊은
  층에 몰리고 여성 비중이 상대적으로 높지만, 이 값은 스마트폰 사용자 기준이며 리뷰 작성자 구성이 아님. 리뷰
  작성자는 스스로 쓴 사람이고 구성은 측정된 적이 없음(단서만). 스토어별로 나눠 읽되 사람 구성을 추정하지 않음 —
  미확인(요약) [P103, P104, P105]
- 배달앱 리뷰 이벤트: 한국소비자원 2024-07-23 설문(자기 보고)에서 리뷰 이벤트 참여자 504명 가운데 401명(79.6%)이
  이벤트가 별점에 영향을 줬다고 했고, 그중 394명(98.3%)이 실제 만족도보다 높은 별점을 줬다고 답함. 394명은 참여자
  504명의 약 78%임. 이벤트가 도는 곳의 별점 평균은 만족도 근거가 아님 — 미확인(요약) [P118, P119, P120]
- 리뷰 보상 표시가 있는 리뷰는 만족·선호·반대 근거 검색·별점 평균에서 D까지만 인정함. 불만과 대처 방법은 한 단계만
  낮춤(최소 C). 판매자나 게시판의 보상 공지는 리뷰별 후보로 검증자에게 넘기며 페이지 전체를 자동으로 낮추지 않음.
  플랫폼 전체의 리뷰 적립 제도와 판매자가 여는 리뷰 이벤트는 구분함 — 규칙
  (`references/research/korea/promotion.md`)
- 자체 브랜드 상품 리뷰: 공정위는 쿠팡이 임직원을 동원해 자체 브랜드 상품에 후기를 달았다는 혐의 등으로 과징금을
  부과했고 소송이 이어지고 있음 — 미확인(요약) [P115, P116]. 플랫폼 자체 브랜드 상품의 리뷰는 다른 채널 계열의
  근거가 있어야 셈 — 규칙 (`references/research/korea/promotion.md`)
- 리뷰 폭주: 카카오톡 2025-09-23 개편 직후 두 스토어 평점이 급락함. 폭주 기간은 사용성 발견이 아니라 맥락이며, 날짜
  구간을 나눠 읽음 — 미확인(요약) [P106, P107]
- 업주가 고르는 평균 별점: 네이버 플레이스의 평균 별점은 업주가 노출을 켜고 끄며, 설명 없는 3점 미만 별점은 금지
  행위로 정해졌다고 보도됨. 보이는 평균 별점을 장소끼리 비교하지 않음 — 미확인(요약) [P39, P42]
- 일부만 보이는 후기: 카카오맵 웹은 후기를 일부만 보여 준다는 보도가 있음. 보이는 후기는 대표성이 없음 —
  미확인(요약) [P46, P47]

## 7. 불연속 날짜표

날짜 앞뒤로 같은 지표를 비교하지 않습니다. 비교가 필요하면 구간을 나눕니다.

| 날짜 | 채널 | 내용 | 근거 |
| --- | --- | --- | --- |
| 2021-10-25 | `naver-place` | 네이버 플레이스 별점 신규 수집 중단(키워드 리뷰 도입) | 미확인(요약) P44 |
| 2024-04-25 | `naver-kin` | 지식iN 개편: 질문 마감 폐지, 여러 답변 채택, 답변 UP/DOWN 투표 | 미확인(요약) P29, P30 |
| 2024-08 | `naver-kin` | 지식iN AI 자동 답변 '지식이' 시범 시작 | 미확인(요약) P31 |
| 2024-08 | `coupang` | 자체 브랜드 상품 검색 순위 조작·임직원 후기 혐의로 공정위 과징금 부과 | 미확인(요약) P115 |
| 2024-09 | `coupang` | 쿠팡이 서울고법에 과징금·시정명령 취소 소송 제기 | 미확인(요약) P116 |
| 2024-10 | `naver-place` | 네이버 플레이스 리뷰 방문 인증 강화(마케팅 커뮤니티 정리, 신뢰도 낮음) | 미확인(요약) P43 |
| 2024-10-07 | `instagram` | Meta 자동 데이터 수집 약관 현행본 시행 | 미확인(요약) P94 |
| 2024-12-01 | `naver-blog`, `naver-cafe`, `daum-cafe`, `tistory` | 블로그·카페 추천·보증 글의 이해관계 표시를 제목이나 첫 부분에 두도록 한 공정위 지침 개정 시행 | 관찰됨 2026-10-01 P163 |
| 2025-02 | `kakao-map` | 카카오맵 웹 개편: 웹에서 '맛집' 평가가 사라지고 후기 노출이 줄었다는 보도(2025-03-15) | 미확인(요약) P46, P47 |
| 2025-04-24 | `threads` | 스레드 기본 주소가 threads.com으로 바뀌고 threads.net은 threads.com으로 넘어감 | 미확인(요약) P100 |
| 2025-05-12 | `naver-place` | 네이버 플레이스 리뷰에 네이버 POS 연동 인증 추가(마케팅 커뮤니티 정리, 신뢰도 낮음) | 미확인(요약) P43 |
| 2025-07 | `naver-blog`, `naver-cafe`, `naver-kin` | 네이버 블로그·카페 등에서 AI 봇 크롤링을 robots.txt로 막는다는 보도 | 미확인(요약) P06, P07 |
| 2025-07-10 | `naver-blog`, `naver-cafe`, `naver-kin`, `naver-place` | 네이버 이용약관 개정 시행: 사용자가 삭제·비공개로 돌린 글은 그 뒤 AI 연구 개발에 쓰지 않는다는 내용 보도 | 미확인(요약) P17, P18 |
| 2025-09-23 | `app-store-kr`, `google-play-kr` | 카카오톡 대규모 개편 직후 두 스토어 평점이 급락함(보도 시점마다 수치가 다름) | 미확인(요약) P106, P107 |
| 2025-10-02 | `google-play-kr` | 카카오톡 구글 플레이 평점 1.0 보도: 평가자 318만 5,098명 중 312만 4,788명(98.11%)이 1점 | 미확인(요약) P106 |
| 2025-12 | `naver-blog` | 블로그 앱 추천 피드 개편 시험 보도(주제별 '내돈내산' 글 모아 보기 포함) | 미확인(요약) P19 |
| 2025-12-01 | `daum-cafe`, `tistory` | 카카오가 다음 서비스(카페·티스토리 포함) 운영을 자회사 AXZ로 넘김 | 미확인(요약) P53, P54 |
| 2026-02-09 | `dcinside` | 디시인사이드 경영권 매각 본계약(에이치PE, 약 2,000억 원). 3월 중 대금 납입 예정으로 보도, 종결 여부 미확인 | 미확인(요약) P63, P64 |
| 2026-04-06 | `naver-place` | 네이버 플레이스 별점 기록 재개 | 미확인(요약) P39, P40 |
| 2026-05-07 | `daum-cafe`, `tistory` | 업스테이지가 AXZ 인수를 마침(보도) | 미확인(요약) P55, P56 |
| 2026-05-24 | `naver-kin` | 지식iN AI 자동 답변 '지식이' 종료 | 미확인(요약) P32, P33 |
| 2026-07-09 | `naver-place` | 네이버 플레이스 평균 별점·사용자별 별점 공개 시작. 평균 별점 노출은 업주가 켜고 끔 | 미확인(요약) P39, P45 |
| 2026-07-27 | `daum-cafe`, `tistory` | AXZ가 사명을 '주식회사 다음'으로 바꿨다고 발표(2026-07-20 임시주주총회 의결) | 미확인(요약) P57, P58, P59 |
| 2026-07-31 | `naver-blog`, `naver-cafe`, `naver-kin` | 개발자센터 검색 API 신규 신청 중단(2026-07-30 24:00 이후). 쇼핑·책·학술정보 데이터는 2026-07-31 24:00 종료 | 관찰됨 2026-09-30 P138 |
| 2026-08-25 | `naver-cafe` | 게시글·댓글 대량 수집 금지 카페 공지 게시 | 관찰됨 2026-10-01 P147 |
| 2026-09-07 | `naver-blog`, `naver-cafe`, `naver-kin` | 네이버 검색 API 특약 개정 시행 보도: 결과를 AI에 넣거나 저장·제3자 제공하는 행위 금지 | 미확인(요약) P01, P02 |
| 2026-09-28 | `daum-cafe`, `tistory` | 다음이 외부 AI 크롤링 허용 범위를 다시 정하는 중이라는 보도(시행일 미확인) | 미확인(요약) P51, P52 |
| 2027-06-30 | `naver-blog`, `naver-cafe`, `naver-kin` | 개발자센터의 기존 이용자 대상 검색 API 제공 종료 예정(2027-06-30 24:00) | 관찰됨 2026-09-30 P138 |

## 8. 행을 고치는 방법

1. `python3 scripts/ux_research.py robots --run RUN URL`로 그 호스트의 robots 판정을 봅니다. 이 명령은 페이지를 읽지
   않습니다. 약관 제한 호스트는 요청 전에 멈추므로(exit 3) robots.txt도 읽지 않습니다. AI 에이전트 토큰 목록은
   `uxresearch/data/agent-tokens.json`에 있습니다.
2. 사람이 약관 원문을 읽고 URL, 조항 번호, 읽은 날짜를 적습니다.
3. 약관 상태가 바뀌면 `uxresearch/data/routes.json`의 `terms_restricted` 항목을 먼저 고칩니다. reader는
   routes.json만 봅니다.
4. 그다음 `uxresearch/data/korea-platforms.json`을 고치고(`terms.routes_entry` 포함) 이 문서를 맞춥니다. checked_at을
   바꾸고, 사람이 실시간 확인을 마친 경우에만 verified_at을 채웁니다. 행 순서와 출처 URL 목록은 두 파일이 같아야
   합니다.
5. 문서화되지 않은 엔드포인트, 검색 결과 페이지, 다른 호스트·미러·캐시·아카이브·앱은 경로로 추가하지 않습니다.
   회원 전용이나 닫힌 커뮤니티를 사용자 단서로 추가하지 않습니다.
6. 사용자 단서에는 조사·패널 값만 넣습니다. 커뮤니티 성비·연령·정치 성향 추정치는 넣지 않습니다.

## 9. 완료 기준(Done when)

- 실행에 쓴 채널마다 정당한 경로, 예상 중단, 약관 상태를 계획(`plan.md`)에 적음.
- `reported`·`confirmed` 채널은 routes.json의 `terms_restricted` 항목과 상태가 같음.
- 접근 표에 `terms_restricted` 중단을 다른 중단과 나눠 적고, out_of_scope 채널은 따로 셈.
- 사용자 단서를 세그먼트 비율로 쓰지 않았고, 커뮤니티 구성 추정치를 사람·주장·페르소나에 붙이지 않음.
- 공개 웹에서 덜 잡힌 집단을 수집 공백으로 적음.
- 확인일이 90일을 넘은 행은 다시 확인함.

## 10. 실패 유형(Failure modes)

- 네이버 채널 대부분이 `terms_restricted`에서 멈춤: 예상된 결과임. 보고서에 수집 공백으로 적고 팀 자료와 다른 채널
  계열로 보완함. 우회하지 않음.
- 전역 검색 도구가 네이버 글을 잘 찾지 못할 수 있음(미확인): 결과가 없다고 논의가 없다는 뜻이 아님.
- 커뮤니티 구성 수치가 서로 어긋남: 이 지도에 싣지 않으며, 다른 곳에서 보더라도 단서로만 씀.
- 리뷰 폭주 기간이나 업주가 고른 평균 별점, 이벤트로 부풀린 별점을 만족도로 읽음: 날짜 구간을 나누고 별점 평균을
  만족도 근거로 쓰지 않음.
- 오래된 행을 그대로 믿음: 확인일이 90일을 넘으면 다시 확인함.
- 운영사·약관 변경을 놓침: 디시인사이드 매각(2026), 다음 운영사 변경(2025-12, 2026-05, 2026-07), 다음의 외부 AI
  크롤링 정책 개정(2026-09 보도), 네이버 카페 공지(2026-08) 뒤에는 약관과 robots를 다시 확인함.
- 앱스토어 공개 페이지·RSS는 약관 제한으로 멈춤. 경쟁 앱 리뷰는 수집 공백으로 적고, 팀 자기 앱은 허가받은 App Store Connect 내보내기 자료를 씀.
- 유튜브 키가 없음: 수집 공백이자 사용자에게 묻는 질문임. 페이지를 읽지 않음.

## 11. 출처

확인일은 각 사실에 적었습니다(2026-09-29, 2026-09-30, 2026-10-01). 원문을 직접 열지 못한 출처는 본문에서 미확인으로 표시했습니다. 약관 URL은 3절의
약관 줄과 JSON의 `terms.terms_url`에 있습니다.

- P01 https://www.newsway.co.kr/news/view?ud=2026090215314059117
- P02 https://www.tokenpost.kr/news/ai/403521
- P06 https://www.etnews.com/20250716000347
- P07 https://v.daum.net/v/20250716143440337
- P08 https://policy.naver.com/rules/service.html
- P11 https://v.daum.net/v/20251222105605977
- P12 https://zdnet.co.kr/view/?no=20251222220821
- P14 https://www.korea.kr/briefing/pressReleaseView.do?newsId=156679064
- P15 https://zdnet.co.kr/view/?no=20250317092935
- P17 https://www.mt.co.kr/tech/2025/07/10/2025071010042598666
- P18 https://news.nate.com/view/20250711n01759
- P19 https://www.hankyung.com/article/202512155313g
- P22 https://www.wiseapp.co.kr/insight/detail/997
- P23 https://platum.kr/archives/286798
- P24 https://www.hankyung.com/society/article/2020100565571
- P25 https://news.sbs.co.kr/news/endPage.do?news_id=N1006281658
- P26 https://news.nate.com/view/20260419n07489
- P27 https://byline.network/2022/10/%EC%A7%80%EC%8B%9Din-%EC%82%B4%EC%95%84%EC%9E%88%EB%84%A4-%EC%8B%A0%EA%B7%9C-%EC%82%AC%EC%9A%A9%EC%9E%90-56%EA%B0%80-1020/
- P28 https://zdnet.co.kr/view/?no=20221006105245
- P29 https://www.newspim.com/news/view/20240425000333
- P30 https://www.mt.co.kr/tech/2024/04/25/2024042509581150389
- P31 https://www.newstree.kr/newsView/ntr202408290017
- P32 https://www.newsis.com/view/NISX20260427_0003608405
- P33 https://www.hankyung.com/article/2026042453671
- P34 https://www.asiae.co.kr/article/2026020517015841527
- P35 https://v.daum.net/v/20260205143407660
- P36 https://github.com/naver/naver-openapi-guide/blob/master/ko/naver-openapi-swagger.yaml
- P37 https://www.wiseapp.co.kr/insight/detail/884/2025-top-user-time-sessions-app-trend
- P38 https://kbench.com/?q=node%2F274790
- P39 https://www.navercorp.com/media/pressReleasesDetail?seq=10034317
- P40 https://www.newspim.com/news/view/20260601001153
- P41 https://edaily.co.kr/News/Read?mediaCodeNo=257&newsId=03325926645477456
- P42 https://v.daum.net/v/20260331161500211
- P43 https://www.i-boss.co.kr/ab-6141-66992
- P44 https://www.fnnews.com/news/202110271247564428
- P45 https://www.etnews.com/20260715000174
- P46 https://www.mt.co.kr/amp/tech/2025/03/15/2025031418022011568
- P47 https://v.daum.net/v/20250315080001376
- P48 https://developers.kakao.com/docs/latest/en/local/dev-guide
- P49 https://cs.daum.net/faq/service/15/category/4122/detail/29058
- P50 https://cs.daum.net/faq/service/36/category/6029/detail/32516
- P51 https://www.hankyung.com/article/2026092800641
- P52 https://www.seoulfn.com/news/articleView.html?idxno=638901
- P53 https://v.daum.net/v/20251201111330982
- P54 https://www.kyeonggi.com/article/20251201580062
- P55 https://www.fnnews.com/news/202605070819041556
- P56 https://view.asiae.co.kr/article/2026050708124400944
- P57 https://www.etoday.co.kr/news/view/2607642
- P58 https://view.asiae.co.kr/article/2026072709372724707
- P59 https://www.aitimes.com/news/articleView.html?idxno=213198
- P60 https://www.koreaherald.com/article/10416369
- P61 https://nstatic.dcinside.com/dc/w/policy/policy_index.html
- P63 https://v.daum.net/v/20260209160127574
- P64 https://www.kmnanews.com/news/articleView.html?idxno=10005
- P65 https://www.fmkorea.com/policy
- P67 https://www.fmkorea.com/best
- P68 https://www.mediaus.co.kr/news/articleView.html?idxno=197845
- P69 https://namu.wiki/w/%EB%8D%94%EC%BF%A0
- P70 https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002317859
- P71 https://www.clien.net/service/board/park/18388326
- P72 https://m.clien.net/service/group/community
- P73 https://ko.wikipedia.org/wiki/%EB%A3%A8%EB%A6%AC%EC%9B%B9
- P74 https://namu.wiki/w/%EC%9D%B8%EC%8A%A4%ED%8B%B0%EC%A6%88
- P75 https://apps.apple.com/kr/app/%EC%9D%B8%EC%8A%A4%ED%8B%B0%EC%A6%88-%EB%8C%80%ED%95%9C%EB%AF%BC%EA%B5%AD-%EC%B5%9C%EB%8C%80%EC%9D%98-%EC%97%B0%EC%98%88-%EC%98%A4%EB%9D%BD-%EC%BB%A4%EB%AE%A4%EB%8B%88%ED%8B%B0/id1218109903
- P76 https://www.mt.co.kr/future/2025/03/12/2025031209550036521
- P77 https://edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02118886642102664
- P78 https://namu.wiki/w/%EC%97%90%EB%B8%8C%EB%A6%AC%ED%83%80%EC%9E%84/%ED%95%99%EC%83%9D%20%EC%BB%A4%EB%AE%A4%EB%8B%88%ED%8B%B0
- P81 https://www.gallup.co.kr/gallupdb/reportContent.asp?seqNo=1586
- P82 https://www.kpf.or.kr/front/board/boardContentsView.do?board_id=246&contents_id=940a3bc4be914ac2a065b8922021728e
- P83 http://m.journalist.or.kr/m/m_article.html?no=57805
- P84 https://www.wiseapp.co.kr/insight/detail/848/secondhand-resale-app-trend-2025-carrot-bunjang-joonggonara
- P85 https://datanews.co.kr/news/article.html?no=146423
- P86 https://developers.google.com/youtube/v3/docs/commentThreads/list
- P87 https://developers.google.com/youtube/v3/getting-started
- P88 https://developers.google.com/youtube/v3/determine_quota_cost
- P89 https://developers.google.com/youtube/terms/developer-policies
- P90 https://www.youtube.com/static?template=terms
- P91 https://about.fb.com/news/2023/11/new-tools-to-support-independent-research/
- P92 https://www.icpsr.umich.edu/sites/icpsr/news/icpsr-to-facilitate-researcher-access-to-metas-api-products
- P93 https://transparency.meta.com/researchtools/meta-content-library
- P94 https://www.facebook.com/legal/automated_data_collection_terms
- P96 https://developers.facebook.com/docs/threads/keyword-search/
- P98 https://biz.heraldcorp.com/article/10546627
- P99 https://v.daum.net/v/3bSk2vLxgE?f=p
- P100 https://techcrunch.com/2025/04/24/threads-officially-moves-to-threads-com-and-updates-its-web-app/
- P101 https://dev.to/antonio_fernandorincond/how-to-pull-app-store-reviews-via-apples-official-rss-feed-no-api-key-1hkk
- P102 https://developer.apple.com/documentation/appstoreconnectapi/get-v1-apps-_id_-customerreviews
- P103 https://www.gallup.co.kr/gallupdb/reportContent.asp?seqNo=1566
- P104 https://www.datanews.co.kr/news/article.html?no=139581
- P105 https://v.daum.net/v/20250708091125354
- P106 https://news.mtn.co.kr/news-detail/2025100215420069531
- P107 https://v.daum.net/v/20250928072646243
- P108 https://developers.google.com/android-publisher/api-ref/rest/v3/reviews/list
- P109 https://developers.google.com/android-publisher/reply-to-reviews
- P111 https://byline.network/2026/04/27_1928774/
- P112 https://www.digitalmarketer.co.kr/insights/coupang-robots-txt-partners-strategy
- P113 https://www.coupang.com/np/policies/terms
- P114 https://www.aboutcoupang.com/ko/terms/
- P115 https://www.hankyung.com/article/202408078618g
- P116 https://www.newsis.com/view/NISX20241014_0002918847
- P117 https://economist.co.kr/article/view/ecn202502200054
- P118 https://www.kmib.co.kr/article/view.asp?arcid=0020341507
- P119 https://v.daum.net/v/20240723120031511
- P120 https://www.khan.co.kr/article/202407240600005
- P121 https://www.law.go.kr/법령/개인정보보호법
- P122 https://raw.githubusercontent.com/legalize-kr/legalize-kr/main/kr/개인정보보호법/법률.md
- P123 https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0300530
- P124 https://pubmed.ncbi.nlm.nih.gov/38709721/
- P125 https://developers.google.com/youtube/terms/derived-metrics-policy
- P126 https://www.clien.net/service/cs/conditions
- P127 https://www.daangn.com/policy/terms/
- P128 https://terms-proxy.kr.karrotwebview.com/page-data/policy/terms/page-data.json
- P129 https://developer.apple.com/documentation/appstoreconnectapi/customer-reviews
- P130 https://www.apple.com/kr/legal/internet-services/itunes/kr/terms.html
- P131 https://www.apple.com/legal/internet-services/itunes/
- P132 https://apps.apple.com/robots.txt
- P133 https://bbs.ruliweb.com/etcs/board/10/read/165
- P134 https://bbs.ruliweb.com/robots.txt
- P135 https://blog.naver.com/robots.txt
- P136 https://cafe.daum.net/robots.txt
- P137 https://cafe.naver.com/robots.txt
- P138 https://developers.naver.com/products/terms/
- P139 https://everytime.kr/page/serviceagreement
- P140 https://everytime.kr/robots.txt
- P141 https://gall.dcinside.com/robots.txt
- P142 https://kin.naver.com/robots.txt
- P143 https://kr.teamblind.com/setting/term
- P144 https://m.cafe.daum.net/_agreement?svc=webview
- P145 https://m.dcinside.com/robots.txt
- P146 https://m.ppomppu.co.kr/robots.txt
- P147 https://notice.naver.com/notices/cafe/33743
- P148 https://pann.nate.com/notice/view?pann_id=373990365
- P149 https://pann.nate.com/robots.txt
- P150 https://play.google.com/about/play-terms.html
- P151 https://play.google.com/intl/ko_kr/about/play-terms.html
- P152 https://play.google.com/robots.txt
- P153 https://policies.google.com/terms
- P154 https://policy.daum.net/policy/info
- P155 https://policy.naver.com/policy/search_policy.html
- P156 https://ribi.tistory.com/robots.txt
- P157 https://theqoo.net/robots.txt
- P158 https://theqoo.net/service
- P159 https://www.clien.net/robots.txt
- P160 https://www.daangn.com/robots.txt
- P161 https://www.dcinside.com/robots.txt
- P162 https://www.fmkorea.com/robots.txt
- P163 https://www.ftc.go.kr/www/downloadBbsFile.do?atchmnflNo=53785
- P164 https://www.instagram.com/robots.txt
- P165 https://www.ppomppu.co.kr/robots.txt
- P166 https://www.ppomppu.co.kr/zboard/view.php?id=regulation&page=2&divpage=1&no=4
- P167 https://www.teamblind.com/robots.txt
- P168 https://www.threads.com/robots.txt
- P169 https://www.threads.net/robots.txt
- P170 https://www.tistory.com/info/policy
- P171 https://www.tistory.com/robots.txt
- P172 https://www.youtube.com/robots.txt
- P173 https://www.youtube.com/t/terms
- P174 https://www.youtube.com/t/terms?hl=en
