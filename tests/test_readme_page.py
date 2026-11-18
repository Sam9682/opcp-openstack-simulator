"""Test that the root endpoint renders README.md as HTML."""

from openstack_simulator.api.app import create_app


def test_root_html():
    app = create_app()
    client = app.test_client()
    resp = client.get("/", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    data = resp.data.decode()
    assert "<!DOCTYPE html>" in data
    assert "OpenStack Simulator" in data
    assert "<table>" in data
    print(f"HTML page rendered: {len(data)} chars")


def test_root_json():
    app = create_app()
    client = app.test_client()
    resp = client.get("/", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "versions" in data


# ---------------------------------------------------------------------------
# Bug condition exploration: indented fenced blocks must render as code blocks
# with copy buttons. Validates: Requirements 1.1-1.5, 2.1-2.5
# ---------------------------------------------------------------------------
import html as _html
import re

_PRE_RE = re.compile(r"<pre\b.*?</pre>", re.DOTALL)
_WRAPPED_PRE_RE = re.compile(
    r'<div class="code-block">\s*<button[^>]*class="copy-btn"[^>]*>.*?</button>\s*<pre\b.*?</pre>\s*</div>',
    re.DOTALL,
)

_SYNTHETIC_MD = (
    "# Title\n\n"
    "1. Install:\n\n"
    "    ```bash\n"
    "    pip install foo\n"
    "    ```\n\n"
    "2. Configure:\n\n"
    "    ```bash\n"
    "    # Set the cloud\n"
    "    export A=1\n"
    "    export B=2\n"
    "    ```\n"
)


def _readme_html():
    client = create_app().test_client()
    resp = client.get("/", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    return resp.data.decode()


def _check_expected_behavior(page):
    """Return list of expectedBehavior violations for the rendered HTML."""
    failures = []
    pres = _PRE_RE.findall(page)

    h1s = re.findall(r"<h1\b[^>]*>(.*?)</h1>", page, re.DOTALL)
    if any("Authenticate and list servers" in h for h in h1s):
        failures.append(f"<h1> generated from comment line: {h1s}")
    if "```" in page:
        failures.append("literal ``` present in HTML")
    if not any(
        "export OS_REGION_NAME=RegionOne\nexport OS_INTERFACE=public" in _html.unescape(re.sub(r"<[^>]+>", "", p))
        for p in pres
    ):
        failures.append("no <pre> contains consecutive export lines on separate lines")
    codes = re.findall(r"<code\b[^>]*>(.*?)</code>", page, re.DOTALL)
    if any(c.lstrip().startswith("bash") for c in codes):
        failures.append(f"<code> starts with 'bash': {[c for c in codes if c.lstrip().startswith('bash')]}")
    if len(_WRAPPED_PRE_RE.findall(page)) != len(pres) or not pres:
        failures.append(
            f"{len(pres)} <pre> blocks, {len(_WRAPPED_PRE_RE.findall(page))} wrapped in div.code-block with button.copy-btn"
        )
    comment_missing = [
        line
        for p in pres
        for line in _html.unescape(re.sub(r"<[^>]+>", "", p)).split("\n")
        if line.strip().startswith("#")
    ]
    # every '#' line in a <pre> must appear inside a span.code-comment
    spans = re.findall(r'<span class="code-comment">(.*?)</span>', page, re.DOTALL)
    if comment_missing and len(spans) < len(comment_missing):
        failures.append(f"{len(comment_missing)} '#' lines in <pre>, only {len(spans)} span.code-comment")
    if not comment_missing:
        failures.append("no '#' comment lines found inside any <pre>")
    return failures


def test_bug_condition_readme_cli_section():
    failures = _check_expected_behavior(_readme_html())
    assert not failures, "Counterexamples:\n- " + "\n- ".join(failures)


def test_bug_condition_synthetic_indented_fence(monkeypatch):
    from pathlib import Path

    orig = Path.read_text

    def fake_read_text(self, *a, **kw):
        if self.name == "README.md":
            return _SYNTHETIC_MD
        return orig(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    page = _readme_html()
    failures = []
    if re.search(r"<h1\b[^>]*>\s*Set the cloud", page):
        failures.append("'# Set the cloud' rendered as <h1>")
    if "```" in page:
        failures.append("literal ``` present")
    if not any("export A=1\nexport B=2" in _html.unescape(re.sub(r"<[^>]+>", "", p)) for p in _PRE_RE.findall(page)):
        failures.append("export lines not on separate lines inside <pre>")
    assert not failures, "Counterexamples:\n- " + "\n- ".join(failures)


# ---------------------------------------------------------------------------
# Preservation: behaviour that must be identical before and after the fix.
# These pass on UNFIXED code. Validates: Requirements 3.1-3.6
# ---------------------------------------------------------------------------
import markdown as _markdown
from contextlib import contextmanager
from pathlib import Path as _Path

from hypothesis import given, settings, strategies as st

_EXTS = ["tables", "fenced_code", "codehilite", "toc"]
_WRAP_OPEN_RE = re.compile(r'<div class="code-block">\s*<button\b[^>]*class="copy-btn"[^>]*>.*?</button>\s*', re.DOTALL)
_WRAP_CLOSE_RE = re.compile(r"(</pre>)\s*</div>")
_COMMENT_SPAN_RE = re.compile(r'<span class="code-comment">(.*?)</span>', re.DOTALL)


def _normalise(page):
    """Strip the copy-button wrapper and comment spans (the only allowed diffs)."""
    # Remove only the wrapper's own closing </div> (not codehilite's) by matching whole blocks.
    page = re.sub(
        _WRAP_OPEN_RE.pattern + r"(<pre\b.*?</pre>)\s*</div>",
        r"\1",
        page,
        flags=re.DOTALL,
    )
    return _unwrap_comment_spans(page)


def _unwrap_comment_spans(page):
    """Remove span.code-comment wrappers (which may enclose nested Pygments spans)."""
    open_tag = '<span class="code-comment">'
    out, i = [], 0
    while True:
        j = page.find(open_tag, i)
        if j < 0:
            out.append(page[i:])
            return "".join(out)
        out.append(page[i:j])
        k, depth = j + len(open_tag), 1
        while depth:
            nxt_open, nxt_close = page.find("<span", k), page.find("</span>", k)
            if nxt_close < 0:
                raise AssertionError("unbalanced code-comment span")
            if 0 <= nxt_open < nxt_close:
                depth += 1
                k = nxt_open + 5
            else:
                depth -= 1
                k = nxt_close + 7
                if depth == 0:
                    out.append(_unwrap_comment_spans(page[j + len(open_tag):nxt_close]))
        i = k


@contextmanager
def _fake_readme(md):
    orig = _Path.read_text

    def fake(self, *a, **kw):
        return md if self.name == "README.md" else orig(self, *a, **kw)

    _Path.read_text = fake
    try:
        yield
    finally:
        _Path.read_text = orig


def _top_level_blocks(page):
    """Return unescaped text of <pre> blocks that contain only top-level (non-CLI-step) content."""
    return [_html.unescape(re.sub(r"<[^>]+>", "", p)) for p in _PRE_RE.findall(_normalise(page))]


def test_preserve_top_level_fences_render_as_pre_code():
    page = _normalise(_readme_html())
    blocks = _PRE_RE.findall(page)
    assert blocks and all("<code" in b for b in blocks)
    texts = [_html.unescape(re.sub(r"<[^>]+>", "", b)) for b in blocks]
    assert any("docker compose up -d" in t and "docker compose down" in t for t in texts)
    assert any("clouds:" in t and "simulator:" in t and "identity_api_version: 3" in t for t in texts)


def test_preserve_headings_and_tables():
    page = _readme_html()
    for h2 in ("Features", "Installation", "Docker Deployment (Recommended)", "API Endpoints"):
        assert re.search(r"<h2\b[^>]*>\s*" + re.escape(h2) + r"\s*</h2>", page), h2
    for h3 in ("Configuring the OpenStack CLI", "Application Credentials"):
        assert re.search(r"<h3\b[^>]*>\s*" + re.escape(h3) + r"\s*</h3>", page), h3
    assert re.search(r"<h1\b[^>]*>\s*OPCP OpenStack Simulator\s*</h1>", page)
    assert page.count("<table>") >= 3
    assert "<th>" in page and "<td><code>application_credential_id</code></td>" in page


def test_preserve_os_auth_url_matches_auth_url(monkeypatch):
    monkeypatch.setenv("HTTP_PORT", "18080")
    client = create_app().test_client()
    page = client.get("/", headers={"Accept": "text/html", "Host": "example.test:9999"}).data.decode()
    m = re.search(r"<td><code>auth_url</code></td>\s*<td><code>(.*?)</code></td>", page, re.DOTALL)
    assert m, "auth_url table row missing"
    auth_url = m.group(1)
    assert auth_url == "http://example.test:18080/identity/v3"
    assert f"export OS_AUTH_URL={auth_url}" in _html.unescape(re.sub(r"<[^>]+>", "", page))


def test_preserve_json_without_html_accept():
    client = create_app().test_client()
    for accept in ("application/json", "*/*", ""):
        resp = client.get("/", headers={"Accept": accept} if accept else {})
        assert resp.status_code == 200
        assert resp.is_json
        assert "versions" in resp.get_json()


def test_preserve_ordered_steps_with_text_and_start_values():
    page = _readme_html()
    texts = [
        "Install the OpenStack CLI:",
        "Copy the provided",
        "Set the environment variables:",
        "Use the simulator:",
    ]
    pos = [page.find(t) for t in texts]
    assert all(p >= 0 for p in pos), pos
    assert pos == sorted(pos)
    section = page[pos[0] - 200 : pos[-1] + 200]
    # Step 1 starts a list; later steps either continue it or carry start="N".
    assert "<ol" in section
    starts = [int(s) for s in re.findall(r'<ol\s+start="(\d+)"', section)]
    assert all(s in (2, 3, 4) for s in starts)
    assert starts == sorted(starts)


_word = st.text(alphabet="abcdefghij klmno_=-.#", min_size=0, max_size=20)
_body_line = _word.filter(lambda s: "```" not in s and "~~~" not in s)
_para = st.text(alphabet="abcdefghij klmno", min_size=1, max_size=30).map(str.strip).filter(bool)
_heading = st.tuples(st.sampled_from(["#", "##", "###"]), _para).map(lambda t: f"{t[0]} {t[1]}")
_fence = st.tuples(
    st.sampled_from(["", "bash", "yaml", "python"]),
    st.lists(_body_line, min_size=1, max_size=5),
).map(lambda t: "```" + t[0] + "\n" + "\n".join(t[1]) + "\n```")
_row = st.tuples(_para, _para).map(lambda t: f"| {t[0]} | {t[1]} |")
_table = st.lists(_row, min_size=1, max_size=3).map(
    lambda rows: "| A | B |\n|---|---|\n" + "\n".join(rows)
)
_block = st.one_of(_heading, _para, _fence, _table)
_md = st.lists(_block, min_size=1, max_size=6).map(lambda bs: "\n\n".join(bs) + "\n")


@settings(max_examples=40, deadline=None)
@given(md=_md)
def test_preserve_column0_markdown_renders_identically(md):
    """**Validates: Requirements 3.1, 3.2, 3.3, 3.5**"""
    with _fake_readme(md):
        page = _readme_html()
    expected = _markdown.markdown(md, extensions=_EXTS)
    assert _normalise(expected) in _normalise(page)


if __name__ == "__main__":
    test_root_html()
    test_root_json()
    print("All tests passed!")


# ---------------------------------------------------------------------------
# Helper unit tests, property test and integration checks (task 3.4).
# Validates: Requirements 2.1-2.5, 3.6
# ---------------------------------------------------------------------------
from openstack_simulator.api.app import _decorate_code_blocks, _dedent_fences


def _text(fragment):
    return _html.unescape(re.sub(r"<[^>]+>", "", fragment))


def test_dedent_bash_info_string():
    md = "1. Step\n    ```bash\n    echo hi\n    ```\n"
    assert _dedent_fences(md) == "1. Step\n\n```bash\necho hi\n```\n"


def test_dedent_tilde_fences():
    assert _dedent_fences("text\n  ~~~\n  a\n  b\n  ~~~\n") == "text\n\n~~~\na\nb\n~~~\n"


def test_dedent_tab_indent():
    assert _dedent_fences("x\n\n\t```\n\ta\n\t\tb\n\t```") == "x\n\n```\na\n\tb\n```"


def test_dedent_blank_lines_inside_block():
    out = _dedent_fences("    ```\n    a\n\n    b\n    ```")
    assert out == "```\na\n\nb\n```"


def test_dedent_unclosed_fence():
    out = _dedent_fences("para\n  ```\n  a\n  b")
    assert out == "para\n\n```\na\nb"


def test_dedent_column0_unchanged():
    md = "# T\n\n```bash\n# c\necho a\n```\n\n~~~\nx\n~~~\n    indented code\n"
    assert _dedent_fences(md) == md


def test_dedent_inline_backticks_untouched():
    md = "text with ```inline``` ticks\n    - item `a`\n"
    assert _dedent_fences(md) == md


def test_decorate_comment_wrapped():
    out = _decorate_code_blocks("<pre><code># hello\n</code></pre>")
    assert '<span class="code-comment"># hello</span>' in out


def test_decorate_non_comment_untouched_and_inline_hash():
    out = _decorate_code_blocks("<pre><code>echo a # b\nls\n</code></pre>")
    assert "code-comment" not in out
    assert "echo a # b\nls\n" in out


def test_decorate_one_wrapper_and_button_per_pre():
    src = "<pre><code>a\n</code></pre><p>x</p><pre><code># c\nb</code></pre>"
    out = _decorate_code_blocks(src)
    assert out.count('<div class="code-block">') == 2
    assert out.count('class="copy-btn"') == 2
    assert len(_WRAPPED_PRE_RE.findall(out)) == 2


_pb_chars = "abcdefghij klmno_=-.#<&"
_pb_line = (
    st.text(alphabet=_pb_chars, min_size=1, max_size=20)
    .map(lambda s: s.strip())
    .filter(bool)
)
_pb_body = st.lists(_pb_line, min_size=1, max_size=6)


@settings(max_examples=40, deadline=None)
@given(
    body=_pb_body,
    depth=st.integers(0, 2),
    indent=st.integers(1, 8),
    info=st.sampled_from(["", "bash", "yaml", "python", "sh"]),
    fence=st.sampled_from(["```", "~~~"]),
)
def test_property_indented_fences_render_as_code(body, depth, indent, info, fence):
    """**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**"""
    prefix = "# Title\n\n"
    for d in range(depth + 1):
        prefix += "    " * d + "1. Step\n\n"
    pad = " " * indent
    md = prefix + pad + fence + info + "\n" + "\n".join(pad + l for l in body) + "\n" + pad + fence + "\n"
    with _fake_readme(md):
        page = _readme_html()
    assert re.findall(r"<h1\b[^>]*>(.*?)</h1>", page, re.DOTALL) == ["Title"]
    assert "```" not in page and "~~~" not in page
    pres = _PRE_RE.findall(page)
    assert len(pres) == 1
    assert len(_WRAPPED_PRE_RE.findall(page)) == 1
    # Round trip: text content of <pre> equals the original body.
    assert _text(pres[0]).strip("\n") == "\n".join(body)


def test_integration_page_has_script_css_and_buttons():
    page = _readme_html()
    assert "<script>" in page
    assert ".copy-btn" in page and ".code-block" in page and ".code-comment" in page
    pres = _PRE_RE.findall(page)
    assert pres
    assert page.count('class="copy-btn"') == len(pres)


def test_integration_full_readme_structure():
    page = _readme_html()
    h1s = [_text(h).strip() for h in re.findall(r"<h1\b[^>]*>(.*?)</h1>", page, re.DOTALL)]
    assert h1s == ["OPCP OpenStack Simulator"]
    texts = [
        "Install the OpenStack CLI:",
        "Copy the provided",
        "Set the environment variables:",
        "Use the simulator:",
    ]
    pos = [page.find(t) for t in texts] + [None]
    assert all(p >= 0 for p in pos[:-1]), pos
    for i in range(4):
        end = pos[i + 1] if pos[i + 1] is not None else len(page)
        assert "<pre" in page[pos[i] : end], f"step {i + 1} has no code block"
