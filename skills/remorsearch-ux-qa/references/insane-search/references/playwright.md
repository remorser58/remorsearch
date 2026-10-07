# Playwright MCP — 브라우저 자동화

> JS 렌더링이 필수이거나 TLS 임퍼소네이션으로도 뚫리지 않는 사이트의 최후 수단.
> 실제 Chromium 브라우저를 구동하여 모든 JS 챌린지를 통과한다.
>
> **주의**: Playwright MCP가 기본(non-isolated) 모드로 실행 중이면, 다른 세션의 브라우저와 충돌할 수 있다 (`Browser is already in use`). 이 경우 `--isolated` 플래그 추가를 권장.

## 의존성

```bash
# Playwright MCP 연결 확인
claude mcp list 2>/dev/null | grep -q playwright && echo "OK" || echo "NOT CONNECTED"

# 미연결 시 설치
claude mcp add playwright -- npx @playwright/mcp@latest
```

**참고**: Playwright MCP는 Claude Code의 MCP 도구로 동작한다. pip install이 아닌 `claude mcp add`로 설치.

## 기본 워크플로

### 1단계: 페이지 접근

```
browser_navigate → URL
```

### 2단계: 콘텐츠 로딩 대기

```
browser_wait_for → 메인 콘텐츠 셀렉터 (예: "article", ".content", "#main")
```

SPA는 초기 HTML이 비어있으므로 반드시 대기 필요.

### 3단계: 콘텐츠 추출 (3가지 방법)

| 방법 | 도구 | 용도 |
|------|------|------|
| 접근성 트리 | `browser_snapshot` | 구조화된 텍스트, 가장 빠르고 토큰 효율적 |
| JS 실행 | `browser_evaluate` | 특정 데이터 추출 (innerText, querySelectorAll) |
| 풀 스크립트 | `browser_run_code` | 스크롤, 페이지네이션, 복잡한 자동화 |

### 4단계: 응답 검증

추출된 콘텐츠가 1,000자 이상 + 주제 관련 키워드 포함 시 성공.

## 핵심 도구 활용

### browser_snapshot — 접근성 트리 추출

스크린샷 대신 **접근성 트리**를 반환. 텍스트 + 인터랙티브 요소가 JSON 구조로 제공.

```
사용: browser_snapshot
결과: 페이지의 모든 텍스트 콘텐츠가 구조화되어 반환
```

### browser_evaluate — JS 실행

```javascript
// 본문 텍스트만 추출
() => document.body.innerText

// 특정 셀렉터의 텍스트
() => document.querySelector('.article-body').innerText

// 여러 요소 추출
() => [...document.querySelectorAll('.product-item')].map(el => ({
  name: el.querySelector('.name')?.innerText,
  price: el.querySelector('.price')?.innerText,
}))

// JSON-LD 구조화 데이터 추출
() => [...document.querySelectorAll('script[type="application/ld+json"]')]
  .map(el => JSON.parse(el.textContent))
```

### browser_run_code — 풀 스크립트

무한 스크롤, 페이지네이션 등 복잡한 시나리오:

```javascript
// 무한 스크롤 후 데이터 수집
async ({ page }) => {
  for (let i = 0; i < 5; i++) {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(1000);
  }
  return await page.evaluate(() => document.body.innerText);
}
```

### browser_network_requests — 숨은 API 발견

페이지가 내부적으로 호출하는 API 엔드포인트를 가로챈다.
**핵심 활용**: WAF 뒤의 실제 데이터 API를 찾아서 curl_cffi로 직접 호출.

```
1. browser_navigate → 대상 URL
2. browser_network_requests → XHR/fetch 호출 목록 확인
3. API 엔드포인트 발견 → curl_cffi로 직접 호출
```

### browser_console_messages — 디버깅

JS 에러와 로그를 확인. 페이지 구조 이해에 유용.

## 사이트별 패턴

### Cloudflare JS 챌린지

```
browser_navigate → URL
(Cloudflare 챌린지 자동 실행, 3-5초 대기)
browser_wait_for → 본문 콘텐츠 셀렉터
browser_snapshot → 콘텐츠 추출
```

### SPA (React/Vue/Next.js)

```
browser_navigate → URL
browser_wait_for → "[data-loaded]" 또는 특정 컴포넌트 셀렉터
browser_evaluate → () => document.querySelector('#__NEXT_DATA__')?.textContent
```

### 네이버 계열 (JS 필수)

```
browser_navigate → https://m.naver.com/...
browser_wait_for → ".content_area" 또는 "#content"
browser_snapshot → 콘텐츠
```

### 로그인 후 콘텐츠 (쿠키 전달)

```
browser_navigate → 로그인 페이지
browser_fill_form → ID/PW 입력
browser_click → 로그인 버튼
browser_wait_for → 로그인 완료 확인
browser_navigate → 대상 페이지
browser_snapshot → 콘텐츠
```

## 주의사항

- Playwright는 **실제 Chromium을 구동**하므로 리소스 소모가 크다
- 가능하면 curl_cffi나 다른 경량 방법을 먼저 시도한 후 최후 수단으로 사용
- `browser_take_screenshot`은 이미지이므로 텍스트 추출에는 비효율적 → `browser_snapshot` 사용
- 한 번에 여러 페이지를 처리하려면 `browser_tabs`로 탭 관리
