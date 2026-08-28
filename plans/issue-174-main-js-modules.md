# Decomposition plan for issue #174: split `static/main.js` into ES modules and `static/style.css` into per-concern sheets

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

`static/style.css` is the same problem one layer down: **2,939 lines** in a
single sheet covering design tokens, the app shell grid, every component and
every view. Point 4 of issue #174 asks for it too, and this plan treats it as in
scope for closing the parent. Exploration found it carries two of the four
constraints above in the same shape:

5. **18 test files read `static/style.css` as text**, 71 hardcoded references in
   all, with no shared fixture. That is constraint 2 again, and `tests/js_source.py`
   from F1 is the model for the fix.
6. **`@import` would bypass cache busting.** `asset_url` (`api/routes.py:96`)
   versions each file it is called on, but a sheet pulled in by `@import` from
   inside another sheet never passes through it. The JS side solved the
   equivalent problem with an import map at `api/routes.py:108`. CSS has no such
   mechanism, so the split must use one `<link>` per sheet in
   `templates/dashboard.html:28`.

Unlike the JS side there is no CSS lint gate to widen: `tests/test_code_quality.py`
covers JavaScript and Python only. Adding one is optional scope, not a
prerequisite.

## Progress

Status as of 2026-08-27. Update this section whenever a sub-issue closes. It is
the only place that shows how much of #174 is left.

- **JS foundation:** complete. #388, #389, #390 and #391 are all closed.
- **JS extractions:** complete. #399 landed `dom.js` and `color.js`, #420
  landed `theme.js`, #422 landed `toast.js`, #424 landed `modals.js`, #426
  landed `panel.js`, #428 landed `logs.js`, #430 landed `terminal.js`, #432
  landed `charts.js`, #435 landed `editor.js`, #437 landed `stats.js`, #439
  landed `monitor.js`, #441 landed `inspector.js`, #443 landed `tree.js`, #445
  landed `sse.js`. The monitor pane was not in the original numbered sequence;
  #437 left `applyContainerFilter`, `applyMonitorFilter` and
  `updateMonitoringView` behind for it, so it became an extraction of its own.
  `static/main.js` is down to 623 lines, and is now bootstrap, tab and settings
  navigation, the delegated-action tables, session persistence and the window
  bridge.

  #445 took the `_statsReceived` / `_statsWaitTimeout` pair with it. The flags
  are written by `handleStatsUpdate` and read by the 15s "no stats received
  yet" placeholder timeout, so the timeout moved too, behind an exported
  `startStatsWaitTimeout()` called from `DOMContentLoaded`. Putting the flags
  on `state.js` was the alternative and would have spent shared state on
  something only this cluster reads.

  #445 hit the byte-window trap once more, in a new shape.
  `tests/test_toast_module.py` searched `main.js` alone for
  `addEventListener('file_changed'`, and the handler moved into `sse.js`. A
  comment naming the moved handler would have kept it green, which is a test
  held up by a comment; it now reads `read_static_js()` instead. Before moving
  a listener, grep the test suite for its event name, not just for the function
  names.

  **The extraction order below is wrong from here on, and #432 already
  departed from it.** `sse.js` is listed sixth but cannot go next:
  `handleStatsUpdate` calls `applyStatusDots`, `updateInspectorStatsCard` and
  `updateMonitoringView`, all of which stay in `main.js` until `stats.js`,
  `inspector.js` and the monitor pane land. Extracting it now would make
  `sse.js` import `main.js`, the cycle the whole sequence exists to avoid.
  `sse.js` is a dispatcher, so it must come after everything it dispatches to.
  Remaining order: `sse.js` last. #435 took
  `editor.js` out of turn: that cluster has no inbound coupling, so it could
  move whenever.

  #443 took `applyStatusDots` along with the tree rather than leaving it for
  `sse.js`: `setActiveServer` calls it and it only paints `.status-dot`
  elements in the tree, so leaving it behind would have made `tree.js` import
  `main.js`. `showFileContextMenu` had the opposite problem, calling `switchTab`
  which stays in `main.js`. It now dispatches a `qm:switch-tab` event that
  `main.js` listens for, rather than growing the window bridge that #392 exists
  to shrink.

  #443 also hit a new variant of the byte-window trap.
  `tests/test_static_js_imports.py` and `tests/test_context_menu_actions.py`
  both match against the concatenated JS *text*, so a comment naming a moved
  symbol keeps a stale assertion passing. Two stranded imports and one dead
  assertion were hidden that way. Grep for a moved name in comments, not just
  in code.

  #437 left `applyContainerFilter`, `applyMonitorFilter` and
  `updateMonitoringView` in `main.js` rather than moving them with the stats
  cluster. `applyContainerFilter` calls `updateMonitoringView`, so taking them
  along would have made `stats.js` import `main.js`. All three belong to the
  monitor pane and move when it does.

  #437 also hit a variant of the byte-window trap. Four test files
  (`test_monitor_a11y.py`, `test_monitor_server_totals.py`,
  `test_monitor_stopped_units.py`, `test_monitor_unit_state.py`) end a function
  region at the next `\nfunction `, which an `export function ` declaration does
  not match, so regions ran to the end of the concatenated source or failed to
  match at all. Grep for `\nfunction ` alongside `\nwindow.` before moving a
  function.

  #441 hit the stranded-import trap directly rather than two modules away:
  `updateInspectorActivityLog` held the last `getRelativeTime` call in
  `main.js`, so the name had to leave the `@qm/dom` clause in the same change.

  Extracting a function can strand an import two modules away: once
  `renderContainerRow` moved, `main.js` no longer used `applySwatchState`, and
  `tests/test_charts_module.py` asserts `main.js` imports exactly its list from
  `@qm/charts`. Check the previous module's import contract when a caller
  leaves `main.js`.

  #432 also deleted the dead `monitoringChart` global. `healthHistoryChart` was
  already gone, so both dead globals named in this plan are now retired.

  #430 deleted `hideTerminalSection` rather than moving it: empty body, dead
  since terminals stopped auto-closing on deselect. Session persistence
  (`saveActiveSessionsToStorage`, `_beforeunloadHandler`, the reconnect banner)
  spans terminals and logs both, so it stayed in `main.js` rather than being
  split across two modules. It needs a home of its own eventually.

  `terminal.js` opens with `/* global Terminal */`. The vendored xterm bundle
  supplies `Terminal` outside the module graph, and the eslint gate skips
  locally (its config is generated by the Codacy CLI and is not in the repo)
  but runs in CI, so a missing header would only surface after merge. Any
  later extraction touching `Chart`, `htmx`, `require` or `monitoringChart`
  needs the same treatment: check the header at `static/main.js:1`.

  #428 also produced `units.js`, which is not in the numbered sequence.
  `tailLogsFromPanel` calls `unitNameFor`, so leaving that helper in `main.js`
  would have made `main.js` import `logs.js` while `logs.js` imported
  `main.js`. `unitNameFor` and `stemFromUnitName` are pure leaves, so they got
  their own module rather than a cycle. `tree.js` will import them too.
  `refreshSessionsStripVisibility` moved into `panel.js` for the same reason.

  #428 also hit the byte-window trap the `toast.js` section warns about.
  `tests/test_frontend_unit_naming.py` sliced source from a function to the
  next `\nwindow.` line; once `tailLogsFromPanel` moved to a file with no such
  line after it, the slice ran to the end of the concatenated source. It now
  brace-matches the body instead. Later extractions should expect more of
  these: grep for `\\nwindow.` before moving a function.
- **Window bridge (#392):** 7 template groups converted (#401, #404, #409, #412,
  #414, #416, #418), plus `setupModalDismissal` dropped by #424 as a dead entry
  no template referenced. The bridge at `static/main.js:2868` still lists 29
  names. `openBottomPanel` looks equally dead but must stay: two e2e tests reach
  it through `page.evaluate`.
- **CSS foundation:** not started. C1 and C2 are unfiled.
- **CSS split:** not started.

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
  The CSS split repeats this with its own helper before a single rule moves.
- **One `<link>` per stylesheet, no `@import`.** Every sheet goes through
  `asset_url` in the template, which is the only path that produces a `?v=`
  value. This costs a few extra requests over HTTP/2 and buys correct cache
  invalidation, which `@import` cannot give us.
- **CSS split by view and concern, not by cascade order.** The sheets are linked
  in a fixed order that preserves today's cascade, so no rule changes specificity
  or wins a different tiebreak than it does now.

## JS foundation sub-issues

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

## JS extraction sequence (file each when its turn comes)

File these as sub-issues one at a time, not upfront, because each one's scope depends on
the shape `state.js` actually takes. Record the order as a checklist comment on
#174. Ordered lowest-tangle first, so the pattern is proven on cheap modules:

1. `dom.js` + `color.js` (#399, done): leaf utilities. `el()`, `hexToRgba`,
   `getRelativeTime`, `setStatText`, `sendNotification`; WCAG math (`linearize`,
   `relativeLuminance`, `contrastRatio`, `onPrimaryFor`). Pure functions, zero
   inbound coupling.
2. `toast.js` (#422, done): one `showToast(message, kind)` helper replacing three
   near-identical render blocks. See the section below; this one had a test trap
   the others do not.
3. `theme.js` (#420, done): theme/density/editor-theme toggles, theme preview,
   `applyChartTheme`, `applyEditorTheme`.
4. `modals.js` (#424, done): `bindModalDismissal`, `setupModalDismissal`, and
   the htmx auto-setup listener behind an exported `initModalDismissal()` so
   importing the module registers nothing. A leaf.
5. `panel.js` (#426, done): bottom-panel chrome and the four resize handles.
   The resize block was already a named `initResizableHandles()` called from
   `DOMContentLoaded`, so only the Ctrl+1/Ctrl+2 listener needed an
   `initPanel()` wrapper. The sessions strip named here turned out to be
   template and CSS only, with no JS.
6. `logs.js`: the `/ws/logs` client.
7. `terminal.js`: xterm + `/ws/exec` client.
8. `sse.js`: the `EventSource` subscription, dispatch, poll health.
9. `charts.js`: CPU/mem time-series charts.
10. `stats.js`: stats table rendering, filter, summary strip.
11. `inspector.js`: container detail pane.
12. `tree.js`: quadlet tree selection, server collapse, context menu, deletion.
13. `editor.js`: validate/save, dirty guard.

`main.js` ends as bootstrap plus the bridge.

Two dead globals surfaced during exploration: `monitoringChart` and
`healthHistoryChart` are referenced behind `typeof` guards at `main.js:661`, `673`
and `1798` but assigned nowhere in the repo. Delete them in whichever extraction
touches those lines.

### Extraction 2 in detail: `toast.js`

Called out in the first comment on #174 and easy to lose, because it is a
deduplication rather than a move. Four near-identical blocks build the same toast
markup today:

- `static/main.js:404` and `:437`: the `htmx:responseError` danger toast (#220)
  and the `user-updated` success toast (#222).
- `static/main.js:1503`: the `file_changed` SSE warning toast.
- `static/main.js:2886`: the soft-refresh path, which reparses a server-rendered
  toast out of an htmx swap.

Extract `showToast(message, kind)` covering the first three. The fourth takes
markup from the server rather than a message string, so fold it in only if it
comes out cleanly; leave it alone otherwise.

**The trap.** Two tests bound their assertions to a byte window rather than to a
function. `tests/test_settings_form_error_handling.py:140` and
`tests/test_user_mutation_guardrails.py:207` each slice 1500 characters after the
listener registration and assert `status-toast`, `textContent` and the absence of
`innerHTML` inside that slice. Moving the render into `showToast` empties the
window and the assertions fail while the behavior is identical. Rewrite them to
assert the listener calls `showToast`, and assert the DOM properties against the
helper itself. Do this in the same PR as the extraction.

**Done when:** one toast renderer exists, both test files assert through the
helper, and the full suite is green.

## CSS foundation sub-issues

Two, mirroring F1 and F2. Both are unfiled. File them in order; C1 has to land
before any rule moves, for the same reason F1 had to land before any function did.

### C1. Shared CSS-source fixture for structural style tests
`size: moderate` · `type: enhancement` · `prio: could-have`

Add `tests/css_source.py` alongside `tests/js_source.py`, same shape: a
`static_css_files()` that globs every non-vendor `static/**/*.css` sorted, and an
`lru_cache`d `read_static_css()` that concatenates them. Migrate all 18
source-reading test files, 71 hardcoded references in total, onto it.

Files: `tests/test_design_lint_style.py`, `tests/test_settings_flat_data_soft_chrome.py`,
`tests/test_settings_layout_unified.py`, `tests/test_theme_on_primary_contrast.py`,
`tests/test_brand_teal_contrast.py`, `tests/test_sessions_strip_empty_state.py`,
`tests/test_density_toggle.py`, `tests/test_settings_actions_spacing.py`,
`tests/test_border_b_utility.py`, `tests/test_pulse_dot_keyframes.py`,
`tests/test_poll_health_ui.py`, `tests/test_unhealthy_salience.py`,
`tests/test_settings_a11y.py`, `tests/test_bottom_panel_align.py`,
`tests/test_monitor_unit_state.py`, `tests/test_stats_monitoring_dedup.py`,
`tests/test_static_asset_cache_busting.py`, and
`tests/e2e/test_settings_flat_data_soft_chrome_e2e.py`.

Two of those need care. `tests/test_static_asset_cache_busting.py` asserts on the
loader rather than the source, so it belongs to C2, not here. Any test that
brace-matches a rule block out of the full text has to keep working under
concatenation; check before assuming a plain string swap is enough.

**Done when:** no test hardcodes `static/style.css` for source reading, and the
full suite is green with `style.css` unchanged.

### C2. Load the dashboard's styles as multiple versioned sheets
`size: straightforward` · `type: enhancement` · `prio: could-have`

`templates/dashboard.html:28` links one `asset_url('style.css')`. Make the
template emit one `<link>` per sheet, in an explicit order, each through
`asset_url`. Drive it from a list so adding a sheet is a one-line change, and do
not use `@import`, which bypasses versioning entirely.

Extend `tests/test_static_asset_cache_busting.py` to assert every linked sheet
carries a `?v=` value, the way it already does for the JS modules. Only
`templates/dashboard.html` links `style.css`; `templates/login.html:24` and
`templates/change_password.html:24` inline their own copy of the design tokens
and are out of scope here.

**Done when:** the dashboard loads its styles from more than one file, every one
of them versioned, with no visual change.

## CSS split sequence (file each when its turn comes)

Same discipline as the JS side: one sub-issue at a time, each a pure move of
whole rule blocks with no rewriting, no consolidation of near-duplicate rules,
and no specificity changes. The link order in `dashboard.html` must reproduce
today's source order exactly, since several later blocks deliberately override
earlier ones (the light-theme status dot tweaks at `style.css:2001` are one
example).

Proposed sheets, in link order, with their current line ranges:

1. `tokens.css`: default and light-theme design tokens, OS preference block,
   density tokens (`style.css:1` to `:231`).
2. `layout.css`: app shell, content wrapper, view control classes, the Containers
   grid, resize handles, raised panel chrome (`:232` to `:437`, `:1559` to `:1744`).
3. `components.css`: typography utilities, buttons, status outputs, context menu,
   modals, toast, status dots, form inputs (`:617` to `:959`, `:1695` to `:1783`).
4. `monitor.css`: monitoring pane, glance bar, per-container table, time-series
   charts, health history (`:438` to `:616`, `:960` to `:1097`).
5. `inspector.css`: container stats card (`:1098` to `:1213`).
6. `terminal.css`: xterm styling, bottom panel, terminal and log tab strips
   (`:1214` to `:1336`, `:2219` to `:2684`).
7. `settings.css`: settings sidenav, sections, tables, panes (`:256` to `:390`,
   `:1745` to `:1930`).
8. `tree.css`: quadlet tree buttons, scope labels, server rows, collapse toggle
   (`:1931` to `:2005`, `:2685` to `:2745`).
9. `overview.css`: overview pane, stat tiles, server cards, container lists,
   empty state (`:2006` to `:2218`).
10. `theme_customization.css`: the theme editor surfaces (`:2746` to end),
    including the reduced-motion block, which must stay last.

Treat the ranges as a starting point, not a contract. Confirm each block's real
boundaries when its turn comes; the file interleaves concerns in places, and a
range that splits a media query is wrong.

## Follow-up issue

**Retire the window bridge (#392).** Convert the 45 inline handlers to delegated
`data-action` listeners inside their owning modules, one template group per PR,
shrinking the F3 bridge each time until it is empty. Also removes the need for
`unsafe-inline` script CSP.

The first group (#401, PR #402) established the dispatch and surfaced the trap
every later group will hit. Dropping a name from the bridge is only safe if
nothing inside `main.js` calls it as `window.NAME`; `switchTab` had two such
internal call sites, and removing it from the bridge left bootstrap throwing, so
`appReady` never fired and all 137 e2e tests failed while the unit suite stayed
green. `tests/test_delegated_handlers.py::test_internal_window_calls_stay_on_the_bridge`
now fails on that condition directly. Convert internal `window.NAME(...)` calls
to direct calls in the same PR that unbridges the name.

The dispatch itself lives at `static/main.js:1634`: one `delegatedActions` lookup
plus one document-level click listener. Later groups add a key, not a listener.
Guard the lookup with `Object.hasOwn` before indexing, or
`tests/test_code_quality.py::test_no_eslint_object_injection` fails.

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

For the CSS sub-issues, add:

6. Diff the computed stylesheet, not just the test result. A pure move can still
   change the cascade if link order slips, and no unit test in this repo would
   see it. Load the dashboard before and after, and compare computed styles on a
   sample from each pane.
7. `venv/bin/pytest -m e2e` is mandatory for C2 and for any split that touches
   the Containers grid or the bottom panel, since layout regressions surface as
   element-not-visible failures there and nowhere else.

Work lands through pull requests against `main`, one per sub-issue, each with
`Fixes #N`.

## Close condition for #174

The parent closes when all of the following are true. Nothing here is optional;
if one becomes undesirable, drop it from this list explicitly rather than closing
around it.

- All 13 JS extractions have landed and `static/main.js` is bootstrap plus the
  bridge.
- The two dead globals `monitoringChart` and `healthHistoryChart` are gone.
- C1 and C2 have landed and the CSS split sequence is complete.
- No test hardcodes `static/main.js` or `static/style.css` as a source path.

Retiring the window bridge (#392) is deliberately **not** on this list. It is a
follow-up that outlives the split, and holding #174 open for it would keep the
parent open indefinitely. Adding a CSS lint gate is likewise out of scope; file
it separately if it is wanted.
