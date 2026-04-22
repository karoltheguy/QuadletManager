"""
Tests for auto-hiding empty scope headings in quadlet_tree.html (Issue #116).
Empty scopes must produce no heading and no list; non-empty scopes render normally.
"""
import os
from jinja2 import Environment, FileSystemLoader

PARTIALS_DIR = os.path.join(os.path.dirname(__file__), "..", "templates", "partials")


def _render(data, server_id=1):
    env = Environment(loader=FileSystemLoader(PARTIALS_DIR))
    tmpl = env.get_template("quadlet_tree.html")
    return tmpl.render(data=data, server_id=server_id)


class TestEmptyScopeHidden:
    def test_empty_global_scope_hides_heading(self):
        html = _render({"global": [], "user": [{"name": "app.container", "path": "/u/app.container"}]})
        assert "global Scope" not in html

    def test_empty_user_scope_hides_heading(self):
        html = _render({"global": [{"name": "app.container", "path": "/g/app.container"}], "user": []})
        assert "user Scope" not in html

    def test_empty_global_scope_hides_no_files_found(self):
        html = _render({"global": [], "user": [{"name": "app.container", "path": "/u/app.container"}]})
        assert "No files found" not in html

    def test_both_empty_renders_nothing(self):
        html = _render({"global": [], "user": []})
        assert "Scope" not in html
        assert "No files found" not in html
        assert "quadlet-tree-btn" not in html


class TestNonEmptyScopeVisible:
    def test_global_scope_heading_shown_when_files_present(self):
        html = _render({"global": [{"name": "db.container", "path": "/g/db.container"}], "user": []})
        assert "global Scope" in html

    def test_user_scope_heading_shown_when_files_present(self):
        html = _render({"global": [], "user": [{"name": "app.container", "path": "/u/app.container"}]})
        assert "user Scope" in html

    def test_both_scopes_shown_when_both_have_files(self):
        html = _render({
            "global": [{"name": "db.container", "path": "/g/db.container"}],
            "user": [{"name": "app.container", "path": "/u/app.container"}],
        })
        assert "global Scope" in html
        assert "user Scope" in html

    def test_file_button_rendered_for_non_empty_scope(self):
        html = _render({"global": [{"name": "db.container", "path": "/g/db.container"}], "user": []})
        assert "quadlet-tree-btn" in html
        assert "db.container" in html
