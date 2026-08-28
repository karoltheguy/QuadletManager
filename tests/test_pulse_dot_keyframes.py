import pytest
"""
Tests for de-duplicating the `@keyframes pulse-dot` definition (Issue #204).

style.css currently defines `@keyframes pulse-dot` twice: once opacity-only
(intended for `.live-pulse::before`) and once with an added `scale()`
transform (intended for `.terminal-conn-tab::before`). Because CSS keyframes
resolve last-wins, both consumers currently animate with the scale variant.

The fix renames the scale variant to `@keyframes pulse-dot-scale` and
repoints `.terminal-conn-tab::before` at it, while `.live-pulse::before`
keeps using the (now single, opacity-only) `pulse-dot` keyframes. Both
selectors must remain listed in the prefers-reduced-motion media block.

Covers:
- @keyframes pulse-dot is defined exactly once
- that single pulse-dot block is opacity-only (no transform/scale)
- a distinct @keyframes pulse-dot-scale block exists and uses scale()
- .terminal-conn-tab::before animates pulse-dot-scale
- .live-pulse::before animates pulse-dot (not pulse-dot-scale)
- prefers-reduced-motion media block still covers both selectors
"""
import re

from tests.css_source import read_static_css


def _css():
    return read_static_css()


def _extract_rule_block(css, selector_regex):
    """Extract the declaration block `{ ... }` for the first rule whose
    selector matches selector_regex. Returns the block body (without braces)
    or None if not found."""
    m = re.search(selector_regex + r"\s*\{", css)
    if not m:
        return None
    start = m.end()
    end = css.index("}", start)
    return css[start:end]


def _extract_media_block(css, media_regex):
    """Extract the full text of a @media block (including nested rules) by
    brace-counting from its opening brace."""
    m = re.search(media_regex + r"\s*\{", css)
    if not m:
        return None
    depth = 1
    i = m.end()
    start = i
    while depth > 0 and i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    return css[start:i - 1]


def _extract_keyframes_block(css, name_regex):
    """Extract the body of the first `@keyframes <name_regex> { ... }` block
    by brace-counting from its opening brace. Returns the block body
    (without the outer braces) or None if not found."""
    m = re.search(r"@keyframes\s+" + name_regex + r"\s*\{", css)
    if not m:
        return None
    depth = 1
    i = m.end()
    start = i
    while depth > 0 and i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    return css[start:i - 1]


class TestPulseDotKeyframesDefinedOnce:
    def setup_method(self):
        self.css = _css()

    @pytest.mark.unit
    def test_pulse_dot_defined_exactly_once(self):
        # Word boundary after "pulse-dot" excludes "pulse-dot-scale".
        matches = re.findall(r"@keyframes\s+pulse-dot\b(?!-scale)", self.css)
        assert len(matches) == 1, (
            f"Expected exactly one @keyframes pulse-dot definition, found "
            f"{len(matches)}"
        )

    @pytest.mark.unit
    def test_pulse_dot_block_is_opacity_only(self):
        block = _extract_keyframes_block(self.css, r"pulse-dot(?!-scale)\b")
        assert block is not None, "@keyframes pulse-dot block not found"
        assert "transform" not in block, (
            "pulse-dot keyframes should be opacity-only but contains "
            "'transform'"
        )
        assert "scale" not in block, (
            "pulse-dot keyframes should be opacity-only but contains "
            "'scale'"
        )


class TestPulseDotScaleKeyframesExist:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_keyframes_block(self.css, r"pulse-dot-scale")

    @pytest.mark.unit
    def test_pulse_dot_scale_block_exists(self):
        assert self.block is not None, (
            "Expected a distinct @keyframes pulse-dot-scale block"
        )

    @pytest.mark.unit
    def test_pulse_dot_scale_block_uses_scale(self):
        assert self.block is not None
        assert "scale(" in self.block


class TestConsumersReferenceCorrectKeyframes:
    def setup_method(self):
        self.css = _css()
        self.terminal_conn_tab_block = _extract_rule_block(
            self.css, r"\.terminal-conn-tab::before"
        )
        self.live_pulse_block = _extract_rule_block(
            self.css, r"\.live-pulse::before"
        )

    @pytest.mark.unit
    def test_terminal_conn_tab_before_animates_pulse_dot_scale(self):
        assert self.terminal_conn_tab_block is not None
        assert re.search(
            r"animation:[^;]*pulse-dot-scale", self.terminal_conn_tab_block
        ), (
            "Expected .terminal-conn-tab::before to animate pulse-dot-scale"
        )

    @pytest.mark.unit
    def test_live_pulse_before_animates_pulse_dot_not_scale(self):
        assert self.live_pulse_block is not None
        assert re.search(
            r"animation:[^;]*pulse-dot\b(?!-scale)", self.live_pulse_block
        ), "Expected .live-pulse::before to animate pulse-dot"
        assert "pulse-dot-scale" not in self.live_pulse_block, (
            "Expected .live-pulse::before to NOT animate pulse-dot-scale"
        )


class TestPrefersReducedMotionStillCoversBothSelectors:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_media_block(
            self.css, r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)"
        )

    @pytest.mark.unit
    def test_media_block_exists(self):
        assert self.block is not None

    @pytest.mark.unit
    def test_covers_live_pulse_before(self):
        assert self.block is not None
        assert ".live-pulse::before" in self.block

    @pytest.mark.unit
    def test_covers_terminal_conn_tab_before(self):
        assert self.block is not None
        assert ".terminal-conn-tab::before" in self.block
