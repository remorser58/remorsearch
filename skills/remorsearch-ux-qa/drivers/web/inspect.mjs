// Read-only DOM state for the interactive client. Serialized by Playwright;
// this function must be self-contained and must never return sensitive values.
export function inspectPage({ redactSelectors = [] } = {}) {
  const all = [];
  const visit = (root) => {
    for (const el of root.children || []) {
      all.push(el);
      if (el.shadowRoot) visit(el.shadowRoot);
      visit(el);
    }
  };
  visit(document);
  const fieldRoles = new Set(['textbox', 'searchbox', 'combobox', 'listbox', 'checkbox', 'radio', 'switch', 'spinbutton', 'slider', 'option']);
  const interactiveRoles = new Set([...fieldRoles, 'button', 'link', 'tab', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'treeitem']);
  const fields = all.filter((el) => ['input', 'select', 'textarea'].includes(el.localName)
    || el.isContentEditable || fieldRoles.has(el.getAttribute('role')) || el.hasAttribute('aria-invalid') || el.hasAttribute('aria-errormessage'));
  const opted = [];
  const roots = [document, ...all.map((el) => el.shadowRoot).filter(Boolean)];
  for (const root of roots) for (const selector of redactSelectors) {
    try { opted.push(...root.querySelectorAll(selector)); } catch { /* invalid selectors never reveal values */ }
  }
  const parent = (el) => el.parentElement || el.getRootNode().host || null;
  const privateNode = (el) => {
    for (let node = el; node; node = parent(node)) if (opted.includes(node)) return true;
    return false;
  };
  const byId = (el, id) => el.getRootNode().getElementById?.(id) || null;
  const refs = (el, attr) => (el.getAttribute(attr) || '').split(/\s+/).filter(Boolean)
    .map((id) => ({ id, node: byId(el, id) }));
  const text = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
  const nameOf = (el) => {
    const labelled = refs(el, 'aria-labelledby').map((r) => text(r.node)).join(' ').trim();
    const labels = [...(el.labels || [])].map(text).join(' ').trim();
    return labelled || el.getAttribute('aria-label') || labels || el.getAttribute('title')
      || el.getAttribute('alt') || (['input', 'select', 'textarea'].includes(el.localName) || el.isContentEditable ? el.getAttribute('placeholder') || ''
        : ['body', 'html'].includes(el.localName) ? '' : text(el));
  };
  const shown = (el) => {
    if (el.localName === 'input' && el.type === 'hidden') return false;
    if (!el.getClientRects().length) return false;
    const box = el.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return false;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true })) return false;
    for (let n = el; n; n = parent(n)) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility !== 'visible' || Number(cs.opacity) === 0) return false;
      if (/inset\(\s*50%/.test(cs.clipPath || '') || /rect\(\s*0(px)?,?\s*0(px)?,?\s*0(px)?,?\s*0(px)?\s*\)/.test(cs.clip || '')) return false;
      const r = n.getBoundingClientRect();
      if (r.width <= 1 && r.height <= 1 && ['hidden', 'clip'].includes(cs.overflow)) return false;
    }
    return true;
  };
  const enabled = (el) => {
    if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return false;
    for (let n = el; n; n = parent(n)) if (n.hasAttribute('inert')) return false;
    return true;
  };
  const selectorOf = (el) => {
    const parts = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const id = n.getAttribute('id');
      if (id) {
        parts.unshift(`#${CSS.escape(id)}`);
        break;
      }
      const siblings = [...(n.parentNode?.children || [])].filter((s) => s.localName === n.localName);
      parts.unshift(`${n.localName}${siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(n) + 1})` : ''}`);
    }
    return parts.join(' > ');
  };
  const roleOf = (el) => el.getAttribute('role') || ({ button: 'button', select: 'combobox', textarea: 'textbox', summary: 'button' }[el.localName])
    || (el.localName === 'a' && el.hasAttribute('href') ? 'link' : el.localName === 'input'
      ? ({ checkbox: 'checkbox', radio: 'radio', range: 'slider', number: 'spinbutton', button: 'button', submit: 'button', reset: 'button' }[el.type] || 'textbox') : el.localName);
  const describe = (el) => {
    const r = el.getBoundingClientRect();
    const vv = window.visualViewport;
    return {
      selector: selectorOf(el), dom_id: el.getAttribute('id'), tag: el.localName, role: roleOf(el), name: nameOf(el),
      visible: shown(el), in_viewport: r.width > 0 && r.height > 0 && r.right > (vv?.offsetLeft || 0) && r.bottom > (vv?.offsetTop || 0)
        && r.left < (vv?.offsetLeft || 0) + (vv?.width || innerWidth) && r.top < (vv?.offsetTop || 0) + (vv?.height || innerHeight),
      enabled: enabled(el), tabindex: el.tabIndex,
    };
  };

  // Match semantic hints as well as common identifiers, including camelCase.
  // Unknown hidden/file values are omitted too; long card-like numbers are
  // redacted even when the page supplied no label or autocomplete metadata.
  const sensitiveHint = /password|passwd|passphrase|secret|one[\s_-]*time|\botp\b|\bpin\b|card|credit|debit|payment|billing|\bcc\b|\bcc[\s_-]|\b(?:cvc|cvv|cvn|csc)\d*\b|security[\s_-]*code|expir|\bexp\b|\bpan\b|\biban\b|\bswift\b|routing|bank|account[\s_-]*(number|no)|비밀번호|카드|계좌|결제/i;
  const rawValue = (el) => ['input', 'select', 'textarea'].includes(el.localName) ? el.value
    : el.isContentEditable ? el.textContent : el.getAttribute('aria-valuetext') ?? el.getAttribute('aria-valuenow');
  const secrets = new Set();
  const sensitive = new Map();
  for (const el of fields) {
    const hint = ['id', 'name', 'autocomplete', 'aria-label', 'placeholder', 'title'].map((attr) => el.getAttribute(attr) || '').concat(nameOf(el)).join(' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[._-]+/g, ' ');
    const value = rawValue(el);
    const redacted = privateNode(el) || ['password', 'hidden', 'file'].includes(el.type) || el.hasAttribute('data-sensitive') || el.hasAttribute('data-private')
      || sensitiveHint.test(hint) || (typeof value === 'string' && /^(?:\d[ -]?){13,19}$/.test(value.trim()));
    sensitive.set(el, redacted);
  }

  for (const el of opted) {
    if (text(el)) secrets.add(text(el));
    for (const attr of ('title aria-label aria-valuetext'.split(' '))) if (el.getAttribute(attr)) secrets.add(el.getAttribute(attr));
  }
  for (const el of fields) {
    for (let n = parent(el); n; n = parent(n)) {
      if (sensitive.get(n) || n.hasAttribute('data-sensitive') || n.hasAttribute('data-private')) {
        sensitive.set(el, true);
        break;
      }
    }
    if (sensitive.get(el)) {
      const value = rawValue(el);
      if (typeof value === 'string' && value) secrets.add(value);
      for (const option of el.selectedOptions || []) {
        if (option.value) secrets.add(option.value);
        if (text(option)) secrets.add(text(option));
      }
    }
  }

  const stateOf = (el) => {
    const redacted = sensitive.get(el);
    const ariaInvalid = el.getAttribute('aria-invalid');
    const nativeInvalid = !!el.willValidate && el.validity?.valid === false;
    const invalid = nativeInvalid || (ariaInvalid !== null && ariaInvalid !== 'false');
    const described = refs(el, 'aria-describedby').map((r) => ({ id: r.id, text: text(r.node), exists: !!r.node }));
    const errors = refs(el, 'aria-errormessage').map((r) => ({ id: r.id, text: text(r.node), exists: !!r.node }));
    return {
      ...describe(el), type: el.localName === 'input' ? el.type : null,
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      value: redacted ? null : rawValue(el), redacted,
      checked: redacted ? null : el.localName === 'input' && ['checkbox', 'radio'].includes(el.type) ? el.checked : el.getAttribute('aria-checked'),
      selected: el.localName === 'select' ? [...el.options].map((o, index) => ({ o, index })).filter(({ o }) => o.selected)
        .map(({ o, index }) => ({ index, value: redacted ? null : o.value, text: redacted ? null : text(o) })) : null,
      aria_selected: redacted ? null : el.getAttribute('aria-selected'),
      invalid, native_invalid: nativeInvalid, user_invalid: el.matches(':user-invalid'), aria_invalid: ariaInvalid,
      aria_describedby: el.getAttribute('aria-describedby'), described_by: described, described_by_text: described.map((r) => r.text).filter(Boolean).join(' '),
      aria_errormessage: el.getAttribute('aria-errormessage'), error_messages: errors,
      error_associated: invalid && [...described, ...errors].some((r) => r.exists && r.text),
    };
  };
  const fieldStates = fields.map(stateOf);
  const readingOrder = all.filter((el) => shown(el) && (el.matches('a[href], button, input, select, textarea, summary, [tabindex], [onclick]')
    || el.isContentEditable || interactiveRoles.has(el.getAttribute('role')))).map((el, order) => ({ order, ...describe(el) }));
  let active = document.activeElement;
  while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
  const result = {
    source: 'dom',
    fields: fieldStates,
    focus: active ? { ...describe(active), on_body: active === document.body || active === document.documentElement } : null,
    invalid_fields: fieldStates.filter((f) => f.invalid),
    reading_order: readingOrder,
    reading_order_basis: 'document order of visible interactive elements, including elements outside the viewport',
    limits: ['Main document and open shadow roots only; frame contents and closed shadow roots are not inspected.',
      'Error association reports non-empty ARIA references on an invalid field; inspect their text to judge whether it is an error.'],
  };
  // A page may echo a secret in a label, error or contenteditable region. Scrub
  // those echoes too, before anything crosses the browser/driver boundary.
  const secretList = [...secrets].sort((a, b) => b.length - a.length);
  const scrub = (value, key = '') => {
    if (typeof value === 'string') {
      for (const secret of secretList) value = secret.length < 3 ? (value === secret ? '[redacted]' : value) : value.split(secret).join('[redacted]');
      return value.replace(/\b(?:\d[ -]?){13,19}\b/g, '[redacted]');
    }
    if (Array.isArray(value)) return value.map((item) => scrub(item, key));
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, scrub(v, k)]));
    return value;
  };
  return scrub(result);
}
