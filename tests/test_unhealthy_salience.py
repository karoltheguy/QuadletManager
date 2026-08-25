import pytest
"""
Tests for unhealthy container visual salience treatment (Issue #190).
Covers:
- .overview-health-unhealthy uses a solid danger fill, not a low-contrast tint
- .stat-badge.unhealthy uses a solid danger fill, not a low-contrast tint
- a new @keyframes attention-unhealthy block exists
- both unhealthy badges reference attention-unhealthy in an animation declaration
- .stat-badge.starting exists using the warning/amber color
- getHealthBadgeInfo() in main.js handles a 'starting' health value
- prefers-reduced-motion media block disables motion for all animated selectors
"""
import os
import re

from tests.js_source import read_static_js

CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")


def _js():
    return read_static_js()


def _css():
    with open(CSS_PATH, encoding="utf-8") as f:
        return f.read()


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


class TestOverviewHealthUnhealthySolidFill:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(self.css, r"\.overview-health-unhealthy")

    @pytest.mark.unit
    def test_rule_exists(self):
        assert self.block is not None

    @pytest.mark.unit
    def test_uses_solid_danger_background(self):
        assert self.block is not None
        assert re.search(r"background-color:\s*var\(--danger", self.block)

    @pytest.mark.unit
    def test_does_not_use_low_contrast_tint(self):
        assert self.block is not None
        assert "rgba(239, 68, 68, 0.12)" not in self.block


class TestStatBadgeUnhealthySolidFill:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(self.css, r"\.stat-badge\.unhealthy")

    @pytest.mark.unit
    def test_rule_exists(self):
        assert self.block is not None

    @pytest.mark.unit
    def test_uses_solid_danger_background(self):
        assert self.block is not None
        assert re.search(r"background(-color)?:\s*var\(--danger", self.block)

    @pytest.mark.unit
    def test_does_not_use_low_contrast_tint(self):
        assert self.block is not None
        assert "color-mix(in srgb, var(--danger) 15%, transparent)" not in self.block


class TestAttentionUnhealthyKeyframes:
    def setup_method(self):
        self.css = _css()

    @pytest.mark.unit
    def test_keyframes_block_exists(self):
        assert re.search(r"@keyframes\s+attention-unhealthy\s*\{", self.css)


class TestUnhealthyBadgesAnimateAttention:
    def setup_method(self):
        self.css = _css()
        self.overview_block = _extract_rule_block(self.css, r"\.overview-health-unhealthy")
        self.stat_badge_block = _extract_rule_block(self.css, r"\.stat-badge\.unhealthy")

    @pytest.mark.unit
    def test_overview_health_unhealthy_animates_attention_unhealthy(self):
        assert self.overview_block is not None
        assert re.search(r"animation:[^;]*attention-unhealthy", self.overview_block)

    @pytest.mark.unit
    def test_stat_badge_unhealthy_animates_attention_unhealthy(self):
        assert self.stat_badge_block is not None
        assert re.search(r"animation:[^;]*attention-unhealthy", self.stat_badge_block)


class TestStatBadgeStarting:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(self.css, r"\.stat-badge\.starting")

    @pytest.mark.unit
    def test_rule_exists(self):
        assert self.block is not None

    @pytest.mark.unit
    def test_uses_warning_amber_color(self):
        # Mirror the existing .overview-health-starting rule, which uses
        # rgba(251, 191, 36, 0.12) and var(--warning, #f59e0b).
        assert self.block is not None
        assert "rgba(251, 191, 36, 0.12)" in self.block or "var(--warning" in self.block


class TestGetHealthBadgeInfoStarting:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_function_has_starting_branch(self):
        m = re.search(r"function getHealthBadgeInfo\s*\([^)]*\)\s*\{", self.js)
        assert m, "getHealthBadgeInfo function not found"
        start = m.end()
        depth = 1
        i = start
        while depth > 0 and i < len(self.js):
            if self.js[i] == "{":
                depth += 1
            elif self.js[i] == "}":
                depth -= 1
            i += 1
        body = self.js[start:i - 1]

        pattern = (
            r"h\s*===\s*['\"]starting['\"][\s\S]{0,120}"
            r"badgeClass['\"]?\s*:\s*['\"]starting['\"]"
        )
        assert re.search(pattern, body), (
            "Expected a branch handling health === 'starting' that yields "
            "badgeClass 'starting'"
        )


class TestPrefersReducedMotion:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_media_block(
            self.css, r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)"
        )

    @pytest.mark.unit
    def test_media_block_exists(self):
        assert self.block is not None

    @pytest.mark.unit
    def test_disables_animation(self):
        assert self.block is not None
        assert "animation: none" in self.block

    @pytest.mark.unit
    def test_covers_dot_running(self):
        assert self.block is not None
        assert ".status-dot.dot-running" in self.block

    @pytest.mark.unit
    def test_covers_dot_failed(self):
        assert self.block is not None
        assert ".status-dot.dot-failed" in self.block

    @pytest.mark.unit
    def test_covers_live_pulse_before(self):
        assert self.block is not None
        assert ".live-pulse::before" in self.block

    @pytest.mark.unit
    def test_covers_terminal_conn_tab_before(self):
        assert self.block is not None
        assert ".terminal-conn-tab::before" in self.block

    @pytest.mark.unit
    def test_covers_overview_health_unhealthy(self):
        assert self.block is not None
        assert ".overview-health-unhealthy" in self.block

    @pytest.mark.unit
    def test_covers_stat_badge_unhealthy(self):
        assert self.block is not None
        assert ".stat-badge.unhealthy" in self.block
