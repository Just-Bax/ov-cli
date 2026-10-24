---
title: External Widgets
description: Use when building, fixing or reviewing a OneVizion External Widget: a single-file HTML app shown in an OV iframe that reads live data through the API.
---

## How to work on a widget

1. Agree on what it shows, for whom, on which instance, and how much data (a few hundred rows or tens of thousands). That decides client-side or server-side filtering below.
2. Write the SQL first and run every query read-only with ov_sql on the instance, with the paging the widget will use. Show sample rows to the user with run_grid when it helps them confirm the data.
3. Write the widget as one HTML file in the workspace (ws_ tools), or in the run folder when no workspace is set. Ship a demo mode with sample data.
4. Run it live with browser_preview, then check it with browser_run: load, filters, the detail view, paging, an empty result, and the console (zero errors).
5. Hand the file to the user to paste into an External Widget. Never deploy it yourself.

## Runtime model

- One HTML file: embedded `<style>` and `<script>`, no build step, no local assets. CDN only for fonts and optional libraries (for example Leaflet), and every CDN dependency needs a fallback.
- It runs in an iframe with `sandbox="allow-same-origin allow-scripts"` (add `allow-forms` for forms, `allow-downloads` for CSV export). Same origin with the OV host is what makes the session token and relative URLs work. Without `allow-same-origin` the token request fails with "Blocked a frame with origin null".
- One IIFE with `'use strict'`. Keep all state in one `state` object; render functions re-render from state.
- Three modes, detected at startup:

| Mode | Detection | Data |
|---|---|---|
| Widget | `window !== window.top` | Live, session token |
| Standalone | top window and a `config.json` beside the file | Live through a token (usually blocked by CORS from `file://`) |
| Demo | `?demo` in the URL, or no config outside the widget | Embedded sample data |

- Always ship demo mode. It makes design review and screenshots possible without an API. Emulate the server behaviour (facets, sort, paging) on the demo data instead of special-casing the UI.
- Widget settings can inject SQL results and parameters as placeholders: `{$data}` is the JSON result of the widget's configured SQL, `{$name}` a named parameter (`JSON.parse('{$data}')`). Use them for settings such as keys, so nothing secret sits in the code. The preview does not fill them; read them through one function that returns demo values when the placeholder is still literal.
- The export format of External Widgets changed between platform versions (a standalone `<WIDGETS>` entry with a `<WIDGET_NAME>` reference against an embedded `<EXTERNAL_WIDGET>`); check the target version before moving a widget with a component import.

## Authentication

Copy this pattern as it is:

```js
function isWidgetMode(){ return window !== window.top; }
function getEndpoint(){
  try { return window.top.location.origin; }
  catch(e){
    if(window.location.ancestorOrigins && window.location.ancestorOrigins.length) return window.location.ancestorOrigins[0];
    throw new Error('Unable to determine API endpoint. Ensure sandbox="allow-same-origin" is enabled.');
  }
}
async function getWidgetToken(){
  var csrfMeta = window.top.document.querySelector('meta[name=_csrf]');
  if(!csrfMeta) throw new Error('CSRF token not found: the user may not be logged in, or allow-same-origin is off.');
  var response = await fetch('/widget/GenerateApiTokenForWebSession', {
    method:'POST', headers:{ 'Content-Type':'application/json', 'X-CSRF-Token':csrfMeta.getAttribute('content') }
  });
  if(!response.ok) throw new Error('Token request failed: '+response.status);
  return (await response.json()).bearerToken;
}
```

- The token URL is relative and has no `credentials:'include'`. A 404 means a wrong path; a 401 means the user is signed out or the page's CSRF token is stale.
- Session tokens expire: on a 401, mint a new one once and retry. Standalone mode cannot refresh itself.
- Standalone `config.json` holds `{ host, token }`; strip a trailing `/` from host and send `Bearer <token>`. It holds a live token: never read it into the conversation, never commit it. A missing config is not an error: use demo data.
- Never put credentials in widget code; users can read it. Session tokens carry the user's own privileges, so each user sees only their data.

## The SQL endpoint

`POST {endpoint}/api/v3/sql/test?rows_count=N`, `Content-Type: text/plain`, body = the SQL.

| Fact | Consequence |
|---|---|
| `rows_count` is at most 1000 (1001 answers HTTP 400) | Clamp every call in one place; page anything bigger |
| A failure answers HTTP 200 with `status:"FAILED"` and `error_message` | Check `data.status`, not only `response.ok` |
| It runs as the current user (`pkg_sec.get_cu`) | Row-level security applies; per-user widgets need no user parameter |
| Column names come back upper case | Normalise: `obj[col.toLowerCase()] = cells[i]` |
| SELECT and WITH only | Writes need REST endpoints |

```js
async function apiSqlQuery(sql, rowsCount){
  var rc = Math.min(rowsCount || ROWS_CAP, ROWS_CAP);
  var doReq = function(){
    return fetch(state.config.endpoint + '/api/v3/sql/test?rows_count=' + rc, {
      method:'POST', headers:{ 'Authorization':state.config.authHeader, 'Content-Type':'text/plain' }, body:sql });
  };
  var response = await doReq();
  if(response.status===401 && await refreshAuthAfter401()) response = await doReq();
  if(!response.ok) throw new Error('SQL API '+response.status+': '+(await response.text().catch(function(){return '';})));
  var data = await response.json();
  if(data && data.status==='FAILED') throw new Error('SQL error: '+(data.error_message||'Unknown'));
  var cols = data.columns || [];
  return (data.rows || []).map(function(r){ var o = {}; cols.forEach(function(c,i){ o[c.toLowerCase()] = r.cells[i]!==undefined ? r.cells[i] : null; }); return o; });
}
```

- The current user is `pkg_sec.get_cu()`. Do not alias it `uid`: UID is an Oracle built-in (ORA-00923). The user's own trackor: `select u.xitor_id from users u where u.user_id = pkg_sec.get_cu`.
- Pass an AbortController signal when a newer request can replace an older one.
- For REST calls the API pitfalls in OV CLI apply (TRACKOR_ID never in fields, parent filters by TRACKOR_KEY, files through `/api/v3/trackor/<id>/file/<FIELD>` fetched with the token and shown as blob URLs, since an `<img>` cannot send the token).

## Writing widget SQL

- Field storage: text in `config_value_char.value_char`; numbers and checkboxes in `config_value_number.value_number`; drop-downs as a number pointing to `attrib_v_table_value` (its `value`, colour in `color`); selectors as the target id, keyed to `xitor.xitor_key`; dates in `config_value_date.value_date`; workplan tasks in `wp_workplan` (`workplan_type in (1,2)`, `active = 1`), `wp_tasks`, `wp_links`. Always filter `xitor.is_template = 0`.
- Never hard-code `config_field_id`. Resolve object references once in a leading CTE and add `/*+ MATERIALIZE */` when many correlated subqueries use it; otherwise Oracle may inline it and run `id.get()` per row and column (one measured case went from 40 s to 4 s):

```sql
with ids as (
  select /*+ MATERIALIZE */ id.get('id.candidate.tt') site_tt,
         id.get('id.candidate.cf.c_state') state_id
    from dual)
select x.xitor_id, x.xitor_key,
       (select av.value from config_value_number n
          join attrib_v_table_value av on av.attrib_v_table_value_id = n.value_number
         where n.key_value = x.xitor_id and n.config_field_id = ids.state_id) state
  from xitor x cross join ids
 where x.xitor_type_id = ids.site_tt and x.is_template = 0
 order by x.xitor_key, x.xitor_id
```

- When fields are referenced by name, read them once from `config_field` (by name and trackor type) at startup and build the SQL from the ids found. If a field is missing on the host, hide what depends on it instead of failing.
- Build per-field columns from one map (`CF = { alias: { orid, kind } }` plus `colExpr(alias, kind, keyCol)`), so the SQL stays consistent and a new field is one line.
- Correlated scalar subqueries are fine for a few hundred rows. For tens of thousands, join each field once in a base CTE and filter and aggregate over it. Keep expensive joins out of queries that do not need them.
- Latest child per parent: rank rows of `ancestor` (filtered by both type columns) with `row_number() over (partition by a.parent_id order by ... desc nulls last, a.child_id desc)` and keep `rn = 1`. Fetch it for all parents in one query and merge in JS, never one query per opened record.
- Paging past 1000 rows: add a unique tiebreaker to `order by`, then loop `offset N rows fetch next 1000 rows only` until a page is short. A query that returns exactly 1000 rows is a silent truncation.
- A BI Table keeps the SQL on the server: the widget sends only `select * from <BI_TABLE>`, faster and without schema in the page source, but filtering and paging can no longer be generated per request.
- Values from the user: quote with `sqlStr`, escape LIKE with `sqlLike` (`escape '\'`), check ids with `/^\d+$/`, and map sort keys and enumerations through a whitelist before they reach SQL. Never concatenate raw input.

## Client-side or server-side filtering

| Rows | Strategy |
|---|---|
| Up to a few thousand, up to about 40 columns | Load everything (paged), filter, sort and facet in JS |
| More, or growing without bound | Server side: one facet query and one page query, in parallel |

Measure the row count and fill rate on the real instance with ov_sql before deciding.

### Server-side facets and paging

- Structure: a base CTE with every filterable column, a narrowed CTE with the non-facet filters, then a facet query (counts per dimension, KPIs, totals) and a page query (OFFSET/FETCH, sorted, dimension filters applied), run together with `Promise.all`.
- Each dropdown counts under every other active filter but ignores its own selection (exclude-self), so other values stay selectable. Build the WHERE with an `except` dimension.
- One `GROUP BY GROUPING SETS ((c1),(c2),...)` pass covers every unfiltered dimension; only filtered ones need their own exclude-self branch. Tag each branch with a uniform row shape (`d, v, c`).
- Cap values per facet with `row_number() over (partition by d order by c desc, v)` and always add the user's selected values back with count 0. Show NULL as a sentinel with a label per dimension, such as "(Unassigned)".
- Request hygiene: debounce checkbox changes (about 500 to 700 ms), apply Enter at once; a generation counter plus AbortController drops stale answers; coalesce reloads asked for while one runs; cache pages per filter state; go back to page 1 on any filter or sort change.

### Client-side facets

- The same UX computed over `state.all`, with a `passExcept(row, excludeDimension)` test.
- Precompute derived fields once per load (a search haystack, status buckets). Map blanks to one display token and compare against the same token.
- One list of dimensions drives dropdowns, chips, legends and colours. Hide a dimension whose source failed instead of showing wrong counts.

## UI patterns

- Facet dropdown: the button shows `Label`, `Label: value` or a count; the panel has a Find box past 8 options, a checkbox list with colour dot and count, Select shown and Clear. Dim zero counts, do not hide them. After re-rendering with innerHTML, restore focus, caret and list scroll. Close on outside click and Escape, returning focus to the button; flip right when the panel would overflow.
- Active-filter chips under the toolbar, each with a remove button, plus Clear all; otherwise filters set from another control become invisible.
- KPIs double as shortcuts (`role="button"`, `tabindex="0"`, Enter and Space) and show when their filter is on.
- Save filters, sort and view to localStorage under a versioned key, and validate every field when loading it (known ids, string arrays, enums, length caps). Bump the version when the shape changes.
- Theme: apply the saved theme in a tiny head script before first paint; otherwise follow `prefers-color-scheme`. A native-looking widget reads `GET /api/v3/params/system/CurrentTheme` and changes accent colours only.
- Respect `prefers-reduced-motion`; pause canvas animation while the tab is hidden; skip FLIP animations when the container is hidden or the page is in the background.
- Large lists: server paging, or render 60 cards and add 60 more as a Show more bar nears the viewport. Delegate clicks on the container; give cards `tabindex="0"`.
- One detail modal instance; opening another record replaces its content; previous and next walk the list it was opened from; one global keydown handler (Escape with `stopImmediatePropagation`), ignoring arrows while typing. Link to the record with `{endpoint}/form/ConfigAppForm.do?id=<id>` (tasks: `/form/TaskForm.do?id=<id>`), `target="_blank" rel="noopener"`.
- Show the age of time-sensitive data, and mark stale data as stale.
- Maps (Leaflet): load it on first use with a timeout and an SVG fallback; keep one map and swap a marker layer on filter changes; guard async builds with a generation token; call `invalidateSize()` after any resize.
- CSV export: UTF-8 BOM, `\r\n`, quote cells with `"`, `,` or line breaks, and prefix cells starting with `= + - @` (that are not plain numbers) with `'` against formula injection. Inside OV it needs `allow-downloads`.
- Writes when there is no write API: avoid them. If a read flag must be set, prefer a REST endpoint; anything else needs the user's agreement first.
- Auto-refresh: a countdown plus a manual refresh; skip while hidden, loading, a record is open or focus is in the list; a failed refresh keeps the current data.

## CSS

- Keep design tokens in `:root` and theme overrides in `[data-theme="..."]`. Add `[hidden]{display:none!important}`.
- Panels with `backdrop-filter` or `transform` create stacking contexts: give the header and toolbar `position:relative;z-index:5` so dropdowns stay on top.
- A nested `backdrop-filter` does not blur, so dropdowns inside a glass toolbar need an opaque background.
- Force dark text on native `<option>` lists in dark themes.

## JavaScript pitfalls

- A variable named like a function shadows it (`const render = render()`): name results differently.
- Building `onclick="..."` strings breaks on quotes in data; use delegated listeners with data attributes.
- Inline styles override classes: toggle `hidden` or classes, not `style.display`.
- Reset a modal form when opening it; old values stay otherwise.
- After an await, find the DOM element again by id before removing or changing it.
- Never assume a field has a value: check for null before formatting.

## Security

| Risk | Rule |
|---|---|
| XSS | Every interpolated value goes through `esc()` (`& < > " '`), attributes too |
| SQL injection | `sqlStr`, `sqlLike`, id checks and whitelists; no raw concatenation |
| CSV injection | The prefix rule above |
| Secrets | Tokens only from the session or an uncommitted config; never in source, logs or screenshots |
| Stored UI state | Validate on load |
| Links | `target="_blank"` always with `rel="noopener"` |

## Checklist

- Data: the auth pattern as above, 401 retry, demo mode; every query checked for FAILED; rows_count clamped and large sets paged; field ids from object references or metadata, missing fields hidden; user values escaped or whitelisted; every query run on the instance with ov_sql.
- UX: exclude-self facets, chips and Clear all; KPIs that filter; versioned, validated saved state; keyboard support; empty, loading, error and stale states; light and dark; reduced motion.
- Quality: `esc()` everywhere, the CSV guard, no secrets; browser_preview with zero console errors and `?demo` working.
