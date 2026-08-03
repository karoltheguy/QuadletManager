"""Tests that every form control in the app's templates has an accessible name.

Complements tests/test_settings_a11y.py (issue #221), which asserts a handful
of specific label associations. This module asserts the general contract
across every template that renders form controls:

- Each `<input>` (other than `type="hidden"`), `<select>` and `<textarea>`
  has a programmatic accessible name, via one of: an `id` referenced by some
  `<label for=...>`, an `aria-label`, an `aria-labelledby`, or a wrapping
  `<label>` (implicit association).
- No `<label>` is left dangling: a label either carries `for` or wraps its
  control. A visible `<label>` with neither names nothing, which is the
  case Sonar reports as Web:S6853.
- An `id` used for label association from inside a `{% for %}` loop
  interpolates a loop variable. A static `id` inside a loop is emitted once
  per iteration, so every label in the loop resolves to the first row's
  control. `settings_servers.html` already sets the precedent for the fixed
  form with `id="server-edit-row-{{ s[0] }}"`.
- `templates/dashboard.html`'s `<html>` element carries `lang` (Web:S5254),
  and its two sibling `<nav>` landmarks carry distinguishing accessible
  names (Web:S5255).

A placeholder is deliberately not accepted as an accessible name: it is not
exposed as one by assistive tech and disappears once the field has content.
"""
import os
import re
from html.parser import HTMLParser

import pytest

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

# Every template that renders form controls. Kept explicit rather than
# globbed so that adding a template is a deliberate decision to bring it
# under this contract.
TEMPLATES_WITH_CONTROLS = [
    "dashboard.html",
    "partials/editor_pane.html",
    "partials/modal_new.html",
    "partials/settings_admin.html",
    "partials/settings_servers.html",
    "partials/settings_themes.html",
    "partials/settings_users.html",
]

CONTROL_TAGS = {"input", "select", "textarea"}

_JINJA_BLOCK = re.compile(r"{%.*?%}", re.S)
_JINJA_EXPR = re.compile(r"{{.*?}}", re.S)


def _template_path(rel):
    return os.path.join(TEMPLATES_DIR, *rel.split("/"))


def _read(rel):
    with open(_template_path(rel), encoding="utf-8") as f:
        return f.read()


def _strip_jinja(src):
    """Render Jinja source parseable as HTML.

    Statement blocks are removed outright; expressions collapse to a token so
    that attribute values containing them stay syntactically intact.
    """
    src = _JINJA_BLOCK.sub("", src)
    return _JINJA_EXPR.sub("JINJA", src)


class _ControlCollector(HTMLParser):
    """Collects form controls, labels, and label nesting from a template."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls = []  # (tag, attrs dict, inside_label, line)
        self.labels = []  # (attrs dict, line, wraps_control)
        self._label_stack = []

    def handle_starttag(self, tag, attrs):
        attrs = {k: (v or "") for k, v in attrs}
        line = self.getpos()[0]
        if tag == "label":
            self._label_stack.append([attrs, line, False])
        elif tag in CONTROL_TAGS:
            inside = bool(self._label_stack)
            if inside:
                self._label_stack[-1][2] = True
            self.controls.append((tag, attrs, inside, line))
        if tag in ("input",) and self._label_stack and tag == "input":
            pass  # void element, no endtag bookkeeping needed

    def handle_endtag(self, tag):
        if tag == "label" and self._label_stack:
            self.labels.append(tuple(self._label_stack.pop()))


def _collect(rel):
    parser = _ControlCollector()
    parser.feed(_strip_jinja(_read(rel)))
    # Any label left unclosed still counts.
    while parser._label_stack:
        parser.labels.append(tuple(parser._label_stack.pop()))
    return parser


def _label_target_ids(parser):
    return {
        attrs["for"] for attrs, _line, _wraps in parser.labels if attrs.get("for")
    }


def _has_accessible_name(tag, attrs, inside_label, label_ids):
    if tag == "input" and attrs.get("type", "").lower() == "hidden":
        return True
    if attrs.get("aria-label") or attrs.get("aria-labelledby"):
        return True
    if inside_label:
        return True
    return bool(attrs.get("id") and attrs["id"] in label_ids)


def _describe(tag, attrs, line):
    name = attrs.get("name") or attrs.get("id") or attrs.get("class") or "?"
    return f"<{tag} {name!r}> at line {line}"


def _for_loop_regions(src):
    """Yield (start, end) character offsets of each `{% for %}` body."""
    regions = []
    stack = []
    for m in re.finditer(r"{%-?\s*(for|endfor)\b.*?%}", src, re.S):
        if m.group(1) == "for":
            stack.append(m.end())
        elif stack:
            regions.append((stack.pop(), m.start()))
    return regions


# =============================================================================
# Every control has an accessible name
# =============================================================================


class TestControlsHaveAccessibleNames:
    @pytest.mark.unit
    @pytest.mark.parametrize("rel", TEMPLATES_WITH_CONTROLS)
    def test_every_control_has_an_accessible_name(self, rel):
        parser = _collect(rel)
        label_ids = _label_target_ids(parser)
        unnamed = [
            _describe(tag, attrs, line)
            for tag, attrs, inside_label, line in parser.controls
            if not _has_accessible_name(tag, attrs, inside_label, label_ids)
        ]
        assert not unnamed, (
            f"{rel}: {len(unnamed)} form control(s) have no accessible name. "
            "Give each an id referenced by a <label for=...>, or an "
            "aria-label/aria-labelledby, or wrap it in its <label>. A "
            "placeholder does not count.\n  " + "\n  ".join(unnamed)
        )


# =============================================================================
# No dangling labels
# =============================================================================


class TestLabelsAreAssociated:
    @pytest.mark.unit
    @pytest.mark.parametrize("rel", TEMPLATES_WITH_CONTROLS)
    def test_no_label_without_for_or_wrapped_control(self, rel):
        parser = _collect(rel)
        dangling = [
            f"<label> at line {line} (text target unknown)"
            for attrs, line, wraps in parser.labels
            if not attrs.get("for") and not wraps
        ]
        assert not dangling, (
            f"{rel}: {len(dangling)} <label> element(s) name nothing. Add a "
            "`for` pointing at the control's id, or wrap the control. If the "
            "target is a group of radios rather than one control, it is not "
            "labelable: use a span plus role=\"radiogroup\" and "
            "aria-labelledby instead.\n  " + "\n  ".join(dangling)
        )


# =============================================================================
# Association ids inside loops must be loop-unique
# =============================================================================


class TestLoopScopedIdsAreUnique:
    @pytest.mark.unit
    @pytest.mark.parametrize("rel", TEMPLATES_WITH_CONTROLS)
    def test_ids_inside_for_loops_interpolate_a_loop_variable(self, rel):
        src = _read(rel)
        offenders = []
        for start, end in _for_loop_regions(src):
            body = src[start:end]
            for m in re.finditer(r"""\b(id|for)\s*=\s*["']([^"']*)["']""", body):
                if "{{" not in m.group(2):
                    line = src.count("\n", 0, start + m.start()) + 1
                    offenders.append(
                        f'{m.group(1)}="{m.group(2)}" at line {line}'
                    )
        assert not offenders, (
            f"{rel}: {len(offenders)} static id/for attribute(s) inside a "
            "{% for %} loop. These are emitted once per iteration, so every "
            "label resolves to the first row's control. Interpolate the loop "
            "key, e.g. id=\"server-edit-name-{{ s[0] }}\".\n  "
            + "\n  ".join(offenders)
        )


# =============================================================================
# dashboard.html document-level landmarks
# =============================================================================


class TestDashboardLandmarks:
    @pytest.mark.unit
    def test_html_element_declares_lang(self):
        src = _read("dashboard.html")
        m = re.search(r"<html\b([^>]*)>", src)
        assert m, "expected a <html> element in dashboard.html"
        assert re.search(r"\blang\s*=", m.group(1)), (
            "expected dashboard.html's <html> element to declare a `lang` "
            f"attribute, found: <html{m.group(1)}>"
        )

    @pytest.mark.unit
    def test_nav_landmarks_have_distinct_accessible_names(self):
        src = _strip_jinja(_read("dashboard.html"))
        navs = re.findall(r"<nav\b([^>]*)>", src)
        assert len(navs) >= 2, (
            f"expected dashboard.html to have at least 2 <nav> landmarks, "
            f"found {len(navs)}"
        )
        names = []
        for attrs in navs:
            m = re.search(
                r"""aria-label\s*=\s*["']([^"']+)["']""", attrs
            ) or re.search(r"""aria-labelledby\s*=\s*["']([^"']+)["']""", attrs)
            assert m, (
                "every <nav> landmark needs an aria-label or aria-labelledby "
                "so assistive tech can tell them apart, missing on: "
                f"<nav{attrs}>"
            )
            names.append(m.group(1))
        assert len(set(names)) == len(names), (
            f"<nav> landmark names must be distinct, found duplicates: {names}"
        )
