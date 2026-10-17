from __future__ import annotations

HELPERS = """
  const selector = [
    'a', 'button', 'input:not([type=hidden])', 'textarea', 'select', 'summary',
    '[tabindex]:not([tabindex="-1"])',
    '[contenteditable=""]', '[contenteditable=true]', '[onclick]', '[role=button]', '[role=link]',
    '[role=tab]', '[role=menuitem]', '[role=menuitemcheckbox]', '[role=option]', '[role=checkbox]',
    '[role=radio]', '[role=switch]', '[role=combobox]', '[role=textbox]', '[role=treeitem]',
    '[role=gridcell]', '[role=row]',
  ].join(', ');
  const clean = (text, max) => (text || '').replace(/\\s+/g, ' ').trim().slice(0, max);
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
      if (type === 'checkbox' || type === 'radio') return type;
      return 'textbox';
    }
    return el.isContentEditable ? 'textbox' : 'clickable';
  };
  const labelledBy = (el) =>
    (el.getAttribute('aria-labelledby') || '')
      .split(/\\s+/)
      .filter(Boolean)
      .map((id) => document.getElementById(id)?.innerText || '')
      .join(' ');
  const besideLabel = (el) => {
    if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return '';
    const cell = el.closest('td');
    const before = cell?.previousElementSibling;
    return before ? before.innerText : '';
  };
  const nameOf = (el) => {
    const buttonInput = el.tagName === 'INPUT' && roleOf(el) === 'button';
    const ownText = el.tagName === 'INPUT' || el.tagName === 'SELECT' ? '' : el.innerText;
    return clean(
      el.getAttribute('aria-label') ||
        labelledBy(el) ||
        (el.labels && el.labels[0] ? el.labels[0].innerText : '') ||
        (buttonInput ? el.value : '') ||
        ownText ||
        el.getAttribute('placeholder') ||
        el.getAttribute('title') ||
        el.getAttribute('alt') ||
        el.querySelector('img[alt]')?.getAttribute('alt') ||
        besideLabel(el) ||
        (document.getElementsByName(el.getAttribute('name')).length === 1 ? el.getAttribute('name') : ''),
      nameChars,
    );
  };
  const valueOf = (el) => {
    if (el.tagName === 'SELECT') return clean(el.selectedOptions[0]?.innerText, valueChars);
    if (el.type === 'checkbox' || el.type === 'radio') return el.checked ? 'checked' : 'unchecked';
    if (el.type === 'password') return el.value ? '(hidden)' : '';
    if (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && roleOf(el) === 'textbox')) {
      return clean(el.value, valueChars);
    }
    return '';
  };
  const areaOf = (el) => {
    const box = el.closest('[role=dialog], dialog, .ui-dialog, .modal');
    if (!box) return '';
    const heading = box.querySelector('[role=heading], h1, h2, h3, .ui-dialog-title, .modal-title');
    return clean(box.getAttribute('aria-label') || heading?.innerText, nameChars);
  };
  const pointer = (el) => getComputedStyle(el).cursor === 'pointer';
  const describe = (el, point) => ({
    role: roleOf(el),
    name: nameOf(el),
    value: valueOf(el),
    area: areaOf(el),
    disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
    x: point[0],
    y: point[1],
  });
"""

POINT_SCRIPT = (
    "({ x, y, nameChars, valueChars }) => {"
    + HELPERS
    + """
  const hit = document.elementFromPoint(x, y);
  if (!hit || hit === document.body || hit === document.documentElement) return null;
  const point = [Math.round(x), Math.round(y)];
  const control = hit.closest(selector);
  if (control) return describe(control, point);

  let el = hit;
  while (el.parentElement && pointer(el.parentElement)) el = el.parentElement;
  return pointer(el) ? describe(el, point) : { ...describe(el, point), role: 'text' };
}
"""
)

TEXT_SCRIPT = "() => document.body ? document.body.innerText : ''"
ELEMENT_SCRIPT = "(el, { x, y, nameChars, valueChars }) => {" + HELPERS + " return describe(el, [x, y]); }"
READY_SCRIPT = "() => document.readyState"

PICKER_SCRIPT = """
(() => {
  if (window.__ovPicker) return;
  window.__ovPicker = true;
  const ID = '__ov_picker';
  const close = () => document.getElementById(ID)?.remove();
  const choose = (select, index) => {
    select.selectedIndex = index;
    select.dispatchEvent(new Event('input', { bubbles: true }));
    select.dispatchEvent(new Event('change', { bubbles: true }));
    close();
    select.focus();
  };
  const open = (select) => {
    const box = select.getBoundingClientRect();
    const list = document.createElement('div');
    list.id = ID;
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', select.getAttribute('aria-label') || select.name || 'options');
    Object.assign(list.style, {
      position: 'fixed', left: box.left + 'px', top: box.bottom + 'px', minWidth: box.width + 'px',
      maxHeight: '320px', overflowY: 'auto', background: '#fff', border: '1px solid #767676',
      boxShadow: '0 4px 14px rgba(0,0,0,.22)', zIndex: '2147483647', padding: '2px 0',
      font: getComputedStyle(select).font, color: '#000',
    });
    [...select.options].forEach((option, index) => {
      const item = document.createElement('div');
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(option.selected));
      item.textContent = option.text || ' ';
      const rest = option.selected ? '#dbe8fb' : '';
      Object.assign(item.style, {
        padding: '3px 10px', whiteSpace: 'nowrap', background: rest,
        cursor: option.disabled ? 'default' : 'pointer', color: option.disabled ? '#999' : '#000',
      });
      item.addEventListener('mouseenter', () => {
        if (option.disabled) return;
        item.style.background = '#1a73e8';
        item.style.color = '#fff';
      });
      item.addEventListener('mouseleave', () => {
        item.style.background = rest;
        item.style.color = option.disabled ? '#999' : '#000';
      });
      item.addEventListener('mousedown', (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!option.disabled) choose(select, index);
      });
      list.appendChild(item);
    });
    document.documentElement.appendChild(list);
    const placed = list.getBoundingClientRect();
    if (placed.bottom > innerHeight && box.top > placed.height) list.style.top = box.top - placed.height + 'px';
    list.querySelector('[aria-selected=true]')?.scrollIntoView({ block: 'nearest' });
  };
  document.addEventListener('mousedown', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('#' + ID)) return;
    const select = target?.closest('select');
    if (!select || select.multiple || select.size > 1 || select.disabled) {
      close();
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const shown = document.getElementById(ID);
    close();
    if (!shown) {
      select.focus();
      open(select);
    }
  }, true);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close();
  }, true);
  window.addEventListener('resize', close);
  document.addEventListener('scroll', (event) => {
    if (!(event.target instanceof Element && event.target.closest('#' + ID))) close();
  }, true);
})();
"""
