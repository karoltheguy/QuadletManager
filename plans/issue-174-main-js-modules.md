# Decomposition plan for issue #174: split `static/main.js` into ES modules

## Context

`static/main.js` is a single classic script that has grown to **3,373 lines** (issue
#174 was filed when it was 2,579). It hand-rolls an `EventSource` client, two
WebSocket clients, Monaco wiring, xterm wiring, monitoring charts, the stats
table, the quadlet tree, and all UI glue in one global scope. The app works; this
is a maintainability problem that compounds with every PR.

Issue #174 is labeled `size: complex` and asks for the split to happen
incrementally, one module per PR. It cannot be done in a single pass, so this
plan decomposes it into sub-issues.

Exploration surfaced four constraints the issue does not mention. They drive the
whole sequence:

1. **45 inline `onclick`/`onchange` handlers in `templates/` depend on implicit
   globals.** A classic script puts every top-level `function` on `window`; an ES
   module does not. Splitting naively produces silently dead buttons, and almost
   nothing in the suite would catch it.
2. **30 test files read `static/main.js` as text** and regex its source, each with
   its own hardcoded `MAIN_JS`/`JS_PATH` constant and no shared fixture. Several
   brace-match function bodies out of the full file text. Moving any function
   breaks its tests even when behavior is identical.
3. **The lint gate is hardcoded to one path.** `tests/test_code_quality.py` runs
   eslint and codacy-analysis against the literal `static/main.js`. New module
   files escape both gates silently.
4. **Cross-cluster mutable state is the real obstacle, not file size.**
   `lastStatsPerServer`, `runningContainersBySid`, the `window._selectedContainer*`
   quartet, `_monitoringServerId`, `_monitorChartMinutes`, the two chart
   instances, `monitorContainerFilter`, and the `_terminalTabs`/`_logTabs` Maps
   are each touched by three or more concern clusters. Extracting a concern
   before this state has a home produces circular imports.

Additionally, `tests/e2e/conftest.py` blocks every `page.goto` until
`window.runningContainersBySid` is defined, and `AGENTS.MD:31` documents that as
the sanctioned wait. `type="module"` is deferred and scoped, so the loader change
must preserve or replace that signal.

Intended outcome: `main.js` becomes a thin entry module; each concern lives in its
own file under `static/modules/`; the test and lint pipeline stops caring which
file a given function lives in.

## Decisions taken

- **No bundler.** Native ES modules served directly, matching
  `static/quadlet_lint.js`, which is already an ES module in this repo. No node
  build step in the Dockerfile or CI.
- **Explicit `window` bridge, then retire it.** One `Object.assign(window, {...})`
  block in the entry module enumerating every template-facing name, guarded by a
  structural test. A follow-up issue converts inline handlers to delegated
  listeners and shrinks the bridge to zero.
- **Shared test fixture before any code moves.** Source-pattern tests read all
  non-vendor static JS through one helper, so later extractions are pure moves.

## Foundation sub-issues

These four carry the design content and unblock every extraction. Each is
independently implementable and committable. The issue bodies are deliberately
short; this file is where their operational detail lives.

### F1 (#388). Shared JS-source fixture for structural frontend tests
`size: moderate` · `type: enhancement` · `prio: could-have`

Add one helper (e.g. `tests/js_source.py`, or a `conftest.py` fixture) that reads
and concatenates every non-vendor file under `static/` matching `*.js`, in sorted
order. Migrate all 30 source-reading test files off their private `MAIN_JS` /
`JS_PATH` / `_MAIN_JS` / `MAIN_JS_PATH` constants onto it.

Representative files: `tests/test_main_js_security_hardening.py`,
`tests/test_frontend_unit_naming.py`, `tests/test_monitor_unit_state.py`,
`tests/test_reconnect_prompt.py`, `tests/test_theme_preview_on_primary.py`.

Exclude `static/vendor/`. Absence assertions (e.g.
`tests/test_stats_monitoring_dedup.py` asserting `statsChart` is gone) get
stronger under concatenation; presence assertions become file-agnostic, which is
the point. `tests/test_theme_preview_on_primary.py` executes extracted functions
via `node`. Keep that working, and prefer importing the module directly once
`color.js` exists.

**Done when:** no test file hardcodes `static/main.js` for source reading, and the
full suite is green with `main.js` unchanged.

### F2 (#389). Make the static JS pipeline multi-file aware
`size: straightforward` · `type: enhancement` · `prio: could-have`

Two coupled changes, both currently hardcoded to a single path:

- `tests/test_code_quality.py::test_eslint_static_files` and
  `test_no_eslint_object_injection` target the literal `static/main.js`. Widen
  both to every non-vendor `static/**/*.js`.
- `api/routes.py:545` calls `_asset_version("main.js")` into a per-asset template
  variable. Generalize so any static JS module gets a `?v=` value without a new
  hand-written context key. `_asset_version` at `api/routes.py:82` is already a
  parameterized pure function; reuse it rather than replacing it. Note
  `static/quadlet_lint.js` currently ships with no cache-busting at all, so fold
  it in.

Keep `tests/test_static_asset_cache_busting.py` passing, extending it to cover a
second JS file.

**Done when:** adding a new file under `static/` puts it under eslint and codacy
automatically and gives it a cache-busting version, with no further edits.

### F3 (#390). Load `main.js` as an ES module behind an explicit window bridge
`size: moderate` · `type: enhancement` · `prio: could-have`

The risky one. **No code moves out of `main.js` in this sub-issue.** It only
changes how the file loads and how templates reach it.

- `templates/dashboard.html:572` becomes `<script type="module" src="/static/main.js?v=...">`.
- Add one bridge block at the end of `main.js`: a single
  `Object.assign(window, { ... })` listing every template-facing name. Do not
  scatter `window.x =` assignments. Source the list from the 45 inline handlers
  plus the 16 `window.*` names templates reference (`switchTab`, `toggleTheme`,
  `saveQuadlet`, `connectTerminal`, `tailLogsFromPanel`, `setSelectedQuadletBtn`,
  `showFileContextMenu`, `applyThemePreview`, `clearThemePreview`, and so on).
- Add a structural test that greps `templates/` for inline handler names and
  asserts each appears in the bridge. This is what stops a later extraction from
  producing a dead button, and it doubles as the retirement checklist.
- Replace the e2e readiness gate. `tests/e2e/conftest.py` waits on
  `window.runningContainersBySid`; switch to an explicit signal such as
  `document.documentElement.dataset.appReady = '1'` set at the end of bootstrap,
  and update `AGENTS.MD:31` to match.

Timing note: `type="module"` is deferred, so it executes after HTML parsing but
still **before** `DOMContentLoaded` fires. The `DOMContentLoaded` handler at
`main.js:2690` therefore still registers in time. The parse-time listeners
(lines 55, 65, 216, 233, 236, 318, 436, 483, 517, 2522, 2533, 3204, 3207, 3219,
3367) now register later than today; verify nothing depends on them being live
during parse. `require.config(...)` at `main.js:341` must still run before
`editor_pane.html` is swapped in. It is, since that partial arrives via htmx.

**Done when:** the dashboard loads as a module, all 45 inline handlers work, the
bridge test passes, and the e2e suite is green on the new readiness signal.

### F4 (#391). Extract shared mutable state into `static/modules/state.js`
`size: moderate` · `type: enhancement` · `prio: could-have`

Move the cross-cluster state out of `main.js` so later extractions do not create
circular imports. Export live bindings (or a small accessor object) for:
`lastStatsPerServer`, `runningContainersBySid`, `monitorContainerFilter`,
`_selectedContainerStem`/`ServerId`/`Scope`/`Type`, `_quadletRestored`,
`activeServerId`, `_monitoringServerId`, `_monitorChartMinutes`,
`cpuHistoryChart`, `memHistoryChart`, `chartColorByName`,
`monitorChartSelection`, `manualStops`, `pendingStarts`, `_terminalTabs`,
`_activeTerminalTabKey`, `_logTabs`, `_activeLogTabKey`.

`main.js` imports from it and keeps re-exporting the template-facing and e2e-facing
ones through the F3 bridge. Note `window.editor` and `window._editorDirty` are
owned by `templates/partials/editor_pane.html`, not by `main.js`. Leave them on
`window` and read them through a documented accessor rather than pretending
`state.js` owns them.

**Done when:** no cross-cluster mutable state is declared in `main.js`, and the
full suite plus e2e is green.

## Extraction sequence (file each when its turn comes)

File these as sub-issues one at a time, not upfront, because each one's scope depends on
the shape `state.js` actually takes. Record the order as a checklist comment on
#174. Ordered lowest-tangle first, so the pattern is proven on cheap modules:

1. `dom.js` + `color.js`: leaf utilities. `el()`, `hexToRgba`, `getRelativeTime`,
   `setStatText`, `sendNotification`; WCAG math (`linearize`, `relativeLuminance`,
   `contrastRatio`, `onPrimaryFor`). Pure functions, zero inbound coupling.
2. `theme.js`: theme/density/editor-theme toggles, theme preview,
   `applyChartTheme`, `applyEditorTheme`.
3. `modals.js`: `bindModalDismissal`, `setupModalDismissal`. A leaf.
4. `panel.js`: bottom-panel chrome, sessions strip, resize handles.
5. `logs.js`: the `/ws/logs` client.
6. `terminal.js`: xterm + `/ws/exec` client.
7. `sse.js`: the `EventSource` subscription, dispatch, poll health.
8. `charts.js`: CPU/mem time-series charts.
9. `stats.js`: stats table rendering, filter, summary strip.
10. `inspector.js`: container detail pane.
11. `tree.js`: quadlet tree selection, server collapse, context menu, deletion.
12. `editor.js`: validate/save, dirty guard.

`main.js` ends as bootstrap plus the bridge.

Two dead globals surfaced during exploration: `monitoringChart` and
`healthHistoryChart` are referenced behind `typeof` guards at `main.js:661`, `673`
and `1798` but assigned nowhere in the repo. Delete them in whichever extraction
touches those lines.

## Follow-up issue

**Retire the window bridge (#392).** Convert the 45 inline handlers to delegated
`data-action` listeners inside their owning modules, one template group per PR,
shrinking the F3 bridge each time until it is empty. Also removes the need for
`unsafe-inline` script CSP.

## Verification

Per sub-issue, in order:

1. `venv/bin/pytest -m unit`: fast structural and unit suite.
2. `venv/bin/pytest`: full suite, including the 30 source-pattern tests. Compare
   pass/fail counts against the pre-change baseline; a new test passing while an
   old one breaks is the failure mode that matters here.
3. `venv/bin/pytest -m e2e`: Playwright. This is the only gate that catches a
   dead inline handler or a broken readiness signal. Mandatory for F3 and F4.
4. `npx eslint --config .codacy/tools-configs/eslint.config.mjs static/**/*.js`
   after F2, to confirm new files are actually covered.
5. Manual smoke on F3 only: load the dashboard, click through each nav tab, the
   theme toggle, the bottom-panel terminal and logs tabs, an editor save, and a
   tree context menu. The bridge test covers name presence, not that the function
   still does the right thing.

Work lands through pull requests against `main`, one per sub-issue, each with
`Fixes #N`. Parent #174 stays open until all sub-issues close.
