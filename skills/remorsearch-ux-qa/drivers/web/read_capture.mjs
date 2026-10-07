// Serialized into the page by read_page.mjs; all helpers must stay in this function.
// Metadata is read from the live page. Only the detached body copy is changed.
export function capturePage(limits) {
  const bodyText = () => {
    if (!document.body) return '';
    const rules = limits.structure;
    const chrome = new Set(rules.chrome);
    const authors = new Set(rules.author);
    const items = new Set(rules.item);
    const keeps = new Set(rules.keep);
    for (const route of rules.overrides) {
      if (!route.hosts.some((h) => location.hostname.toLowerCase() === h
        || (h.startsWith('*.') && location.hostname.toLowerCase().endsWith(h.slice(1))))) continue;
      for (const t of route.drop) chrome.add(t);
      for (const t of route.author) authors.add(t);
    }
    // These structural constants and value shapes mirror extract.py. Token lists
    // and platform profile URL shapes come from the packaged data, never the page.
    const skipTags = new Set(['script', 'style', 'noscript', 'template', 'svg', 'head', 'iframe', 'object', 'canvas', 'math']);
    const navTags = new Set(['header', 'nav', 'footer', 'aside', 'menu']);
    const navRoles = new Set(['navigation', 'banner', 'contentinfo', 'complementary', 'search', 'menu', 'menubar', 'toolbar']);
    const widgetTags = new Set(['button', 'select', 'option', 'label', 'textarea', 'dialog']);
    const blockTags = new Set(['p', 'div', 'br', 'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'table',
      'section', 'article', 'header', 'footer', 'nav', 'aside', 'main', 'blockquote', 'pre', 'dd', 'dt', 'dl', 'figure',
      'figcaption', 'form', 'hr', 'address', 'details', 'summary', 'fieldset', 'legend', 'tbody', 'thead', 'tfoot', 'caption']);
    const itemSides = new Set(['list', 'lists', 'wrap', 'wrapper', 'box', 'area', 'all', 'group', 'container', 'section',
      'holder', 'info', 'count', 'cnt', 'num', 'total', 'sort', 'order', 'filter', 'write', 'form', 'pagination', 'pager',
      'more', 'body', 'content', 'text']);
    const edge = " \t\n\r\f\v·|/:,;()[]{}<>\"'“”‘’.-–—~ㆍ∙•";
    const trimEdge = (s) => {
      let a = 0, b = s.length;
      while (a < b && edge.includes(s[a])) a++;
      while (b > a && edge.includes(s[b - 1])) b--;
      return s.slice(a, b);
    };
    const num = String.raw`\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?`;
    const months = 'jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec';
    const koUnits = '건|명|개|번|회|점|층|권|잔|편|곡|부|대|마리|채|살|표|위|등|배|천|만|억|조|년|월|일|주|달|개월|시간|시|분|초';
    const enUnits = 'years?|yrs?|months?|weeks?|days?|hours?|hrs?|minutes?|mins?|seconds?|secs?|views?|likes?|k|m|g|b';
    const countWords = '(?:조회|추천|비추|반대|댓글|덧글|댓수|좋아요|싫어요|별점|평점|평가|점수|리뷰|like|likes|view|views|hit|hits|comment|comments|reply|replies|count|score|rating|star|stars)';
    const date = String.raw`\d{4}\s?[년./-]\s?\d{1,2}\s?[월./-]\s?\d{1,2}\s?일?|\d{4}\s?년(?:\s?\d{1,2}\s?월)?(?:\s?\d{1,2}\s?일)?|\d{1,2}\s?월(?:\s?\d{1,2}\s?일)?|\d{1,2}\s?[./-]\s?\d{1,2}|(?:${months})[a-z]*\.?\s*\d{1,2}(?:st|nd|rd|th)?(?:\s*,\s*\d{4})?|\d{1,2}\s+(?:${months})[a-z]*\.?(?:\s*,?\s*\d{4})?`;
    const time = String.raw`(?:오전|오후|am|pm)?\s*\d{1,2}\s?:\s?\d{2}(?:\s?:\s?\d{2})?\s?(?:am|pm)?`;
    const relative = String.raw`\d+\s?(?:초|분|시간|일|주|개월|달|년)\s?(?:전|후|째)|\d+\s?(?:${enUnits})\s+ago|방금|방금전|금방|아까|어제|그제|작일|금일|오늘|올해|작년|내년|모레|지금|just now|yesterday|today|now`;
    const number = String.raw`(?:${countWords})?\s*[:.]?\s*(?:${num})(?:\s?(?:${koUnits}|${enUnits}|%|\+))?(?:\s?/\s?(?:${num})(?:\s?(?:${koUnits}|${enUnits}|%|\+))?)?`;
    const shape = `^(?:(?:${date})(?:\\s+(?:${time}))?|${time}|${relative}|${number}|[★☆✩✪⭐]{1,10})$`;
    // Python's Unicode \d and \s include decimal digits and four additional
    // whitespace controls that JavaScript's shorthand classes do not.
    const value = new RegExp(shape.replaceAll('\\d', '\\p{Nd}').replaceAll('\\s', '[\\s\\x1c-\\x1f]'), 'iu');
    const keepsValue = (s) => {
      const stripped = trimEdge(s);
      return !stripped || stripped.split(/[·|/,;()\[\]{}•∙ㆍ]/).map(trimEdge).filter(Boolean).every((p) => value.test(p));
    };
    const profiles = rules.profilePatterns.map((p) => new RegExp(p, 'iu'));
    const memberLink = (n) => {
      try {
        const href = n.getAttribute('href');
        const url = new URL(href, document.baseURI);
        // URL.href percent-encodes literal Unicode @handles. Match that original
        // path too, like privacy.profile_href's bare member/profile path rule.
        return /^https?:$/.test(url.protocol) && (profiles.some((p) => p.test(href) || p.test(url.href))
          || /(?:^|\/)(?:@[\p{L}\p{N}_.-]+|(?:user|users|u|profile|profiles|member|members|people|author|authors|mypage)\/)/u.test(href));
      }
      catch { return false; }
    };
    const tokensOf = (n) => {
      const raw = [(n.getAttribute('id') || '').trim().toLowerCase(), ...(n.getAttribute('class') || '').toLowerCase().split(/\s+/),
        ...[...n.attributes].filter((a) => a.name.startsWith('data-')).map((a) => a.name.slice(5).toLowerCase())];
      return new Set(raw.filter(Boolean).flatMap((s) => [s, ...s.split(/[-_]+/)]));
    };
    const has = (tokens, set) => [...tokens].some((t) => set.has(t));
    const clone = document.body.cloneNode(true);
    const scopes = [];
    let itemDepth = 0;
    const visit = (live, copy, keep = false) => {
      if (live.nodeType === Node.TEXT_NODE) {
        const scope = scopes.at(-1);
        if (scope?.mode === 'label') {
          scope.buffer.push({ node: copy, keep });
          scope.size += [...live.data.replace(/[\s\x1c-\x1f]/gu, '')].length;
          if (scope.size > 80) {
            // As in extract.py, a nested content wrapper overflows its enclosing
            // labels too. Already scrubbed nested labels/member links stay scrubbed.
            for (const s of scopes) if (s.mode === 'label') s.mode = 'content';
          }
        }
        return;
      }
      if (live.nodeType !== Node.ELEMENT_NODE) { copy.remove(); return; }
      const tag = live.localName;
      const role = (live.getAttribute('role') || '').toLowerCase();
      const style = getComputedStyle(live);
      if (skipTags.has(tag) || live.hasAttribute('hidden') || style.display === 'none' || style.visibility === 'hidden'
        || navTags.has(tag) || navRoles.has(role) || chrome.has((live.getAttribute('id') || '').trim().toLowerCase())
        || (live.getAttribute('class') || '').toLowerCase().split(/\s+/).some((c) => chrome.has(c))
        || widgetTags.has(tag) || ['dialog', 'alertdialog'].includes(role)) {
        if (copy === clone) copy.replaceChildren();
        else copy.remove();
        return;
      }
      const tokens = tokensOf(live);
      const author = (live.getAttribute('itemprop') || '').toLowerCase().split(/\s+/).includes('author')
        || (live.getAttribute('rel') || '').toLowerCase().split(/\s+/).includes('author') || has(tokens, authors)
        || (tag === 'a' && scopes.length > 0 && live.hasAttribute('href') && memberLink(live));
      const item = has(tokens, items) && !has(tokens, itemSides);
      if (item && itemDepth === 0 && scopes.length === 0 && !author) copy.before(document.createTextNode('\n---\n'));
      if (item) itemDepth++;
      const scope = author ? { mode: 'label', buffer: [], size: 0, emitted: false } : null;
      if (scope) scopes.push(scope);
      const block = blockTags.has(tag) || ['block', 'list-item', 'table-row'].includes(style.display);
      if (copy !== clone) {
        if (block) { copy.before(document.createTextNode('\n')); copy.after(document.createTextNode('\n')); }
        else if (['td', 'th'].includes(tag)) copy.before(document.createTextNode(' '));
      }
      const originals = [...live.childNodes], copies = [...copy.childNodes];
      for (let i = 0; i < originals.length; i++) visit(originals[i], copies[i], keep || tag === 'time' || has(tokens, keeps));
      if (scope) {
        scopes.pop();
        if (scope.mode === 'label') {
          for (const piece of scope.buffer) if (!piece.keep && !keepsValue(piece.node.data)) piece.node.remove();
          if (!scope.emitted) {
            copy.append(document.createTextNode('[author]'));
            const outer = [...scopes].reverse().find((s) => s.mode === 'label');
            if (outer) outer.emitted = true;
          }
          // Flatten the label to text nodes. Exactly one placeholder represents
          // nested labels for the same name; retained facts keep their own nodes.
          const walker = document.createTreeWalker(copy, NodeFilter.SHOW_TEXT);
          const textNodes = [];
          while (walker.nextNode()) textNodes.push(walker.currentNode);
          if (copy === clone) copy.replaceChildren(...textNodes);
          else copy.replaceWith(...textNodes);
        }
      }
      if (item) itemDepth--;
    };
    visit(document.body, clone);
    // A detached body's innerText falls back to textContent. Explicit block/item
    // breaks above retain readability without ever attaching the clone to the page.
    return clone.textContent.normalize('NFC').replace(/[\u200b\ufeff]/g, '')
      .replace(/[ \t\f\v\r\u00a0\u3000]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  };
  const pick = (sel) => {
    const n = document.querySelector(sel);
    return n ? (n.getAttribute('content') || '').trim() : null;
  };
  const og = {};
  for (const n of document.querySelectorAll('meta[property^="og:"]')) {
    const k = n.getAttribute('property');
    if (Object.keys(og).length < 20 && !(k in og)) og[k] = (n.getAttribute('content') || '').slice(0, 2000);
  }
  const blocks = [];
  let total = 0;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    if (blocks.length >= limits.blocks) break;
    const raw = s.textContent || '';
    if (total + raw.length > limits.chars) break;
    total += raw.length;
    try { blocks.push(JSON.parse(raw)); } catch { blocks.push(raw); }
  }
  const visible = (n) => {
    const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  return {
    title: (document.title || '').slice(0, 2000),
    lang: (document.documentElement.getAttribute('lang') || '').slice(0, 35),
    text: bodyText(),
    json_ld: blocks,
    description: pick('meta[name="description" i]'),
    og,
    robots: pick('meta[name="robots" i]'),
    tdm: pick('meta[name="tdm-reservation" i]'),
    login_form: [...document.querySelectorAll('input[type="password" i]')].some(visible),
  };
}
