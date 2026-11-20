"""Flask application factory for the OpenStack Simulator API."""

from __future__ import annotations

import os
import re
from pathlib import Path

import markdown
from flask import Flask, request

from openstack_simulator.environments import EnvironmentRegistry
from openstack_simulator.api.identity import identity_bp
from openstack_simulator.api.compute import compute_bp
from openstack_simulator.api.network import network_bp
from openstack_simulator.api.volume import volume_bp
from openstack_simulator.api.baremetal import baremetal_bp
from openstack_simulator.api.image import image_bp
from openstack_simulator.api.sim_control import sim_control_bp
from openstack_simulator.api.helpers import register_error_handlers


def create_app(config: dict | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        config: Optional simulator configuration overrides applied to every
            credential environment.

    Returns:
        Configured Flask app with all OpenStack API blueprints registered.
    """
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # One isolated simulator environment per application credential.
    registry = EnvironmentRegistry(config)
    app.config["ENVIRONMENTS"] = registry
    # Default environment, kept as ``SIMULATOR`` for tooling and tests.
    simulator = registry.default
    app.config["SIMULATOR"] = simulator

    # Fake project/domain IDs used throughout responses
    app.config["PROJECT_ID"] = simulator.project_id
    app.config["PROJECT_NAME"] = simulator.project_name
    app.config["DOMAIN_ID"] = "default"
    app.config["DOMAIN_NAME"] = "Default"
    app.config["REGION"] = "RegionOne"

    register_error_handlers(app)

    # Register blueprints for each OpenStack service
    app.register_blueprint(identity_bp)
    app.register_blueprint(compute_bp)
    app.register_blueprint(network_bp)
    app.register_blueprint(volume_bp)
    app.register_blueprint(baremetal_bp)
    app.register_blueprint(image_bp)
    app.register_blueprint(sim_control_bp)

    # Health check endpoint
    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok"}

    # Root endpoint: serve README as HTML for browsers, JSON for API clients
    @app.route("/", methods=["GET"])
    def root():
        accept = request.headers.get("Accept", "")
        if "text/html" in accept:
            return _render_readme()

        return {
            "versions": {
                "values": [
                    {
                        "id": "v3.0",
                        "status": "stable",
                        "links": [{"rel": "self", "href": "/identity/v3/"}],
                    }
                ]
            }
        }

    return app


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenStack Simulator</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #24292e;
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem;
            background: #f6f8fa;
        }
        .container {
            background: #fff;
            border: 1px solid #e1e4e8;
            border-radius: 6px;
            padding: 2rem 3rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        h1 { color: #0366d6; border-bottom: 2px solid #0366d6; padding-bottom: 0.5rem; }
        h2 { color: #24292e; border-bottom: 1px solid #e1e4e8; padding-bottom: 0.3rem; margin-top: 2rem; }
        h3 { color: #586069; margin-top: 1.5rem; }
        code {
            background: #f6f8fa;
            border: 1px solid #e1e4e8;
            border-radius: 3px;
            padding: 0.2em 0.4em;
            font-size: 0.9em;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        }
        pre {
            background: #1e1e1e;
            color: #d4d4d4;
            border-radius: 6px;
            padding: 1rem 1.5rem;
            overflow-x: auto;
            line-height: 1.4;
        }
        pre code {
            background: none;
            border: none;
            padding: 0;
            color: inherit;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        }
        .code-block { position: relative; }
        .code-block pre { margin: 1rem 0; }
        .copy-btn {
            position: absolute;
            top: 0.5rem;
            right: 0.5rem;
            padding: 0.2rem 0.6rem;
            font-size: 0.75rem;
            line-height: 1.4;
            color: #fff;
            background: rgba(30, 30, 30, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.4);
            border-radius: 4px;
            cursor: pointer;
            opacity: 0;
            transition: opacity 0.15s;
        }
        .code-block:hover .copy-btn,
        .copy-btn:focus,
        .copy-btn.copied { opacity: 1; }
        @media (hover: none) {
            .copy-btn { opacity: 0.8; }
        }
        .copy-btn.copied { background: rgba(40, 167, 69, 0.9); }
        .code-comment { font-size: 0.85em; font-style: italic; color: #6a9955; }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 1rem 0;
        }
        th, td {
            border: 1px solid #e1e4e8;
            padding: 0.5rem 0.75rem;
            text-align: left;
        }
        th { background: #f6f8fa; font-weight: 600; }
        tr:nth-child(even) { background: #f9fafb; }
        a { color: #0366d6; text-decoration: none; }
        a:hover { text-decoration: underline; }
        blockquote {
            border-left: 4px solid #0366d6;
            margin: 1rem 0;
            padding: 0.5rem 1rem;
            background: #f1f8ff;
            color: #586069;
        }
        .footer {
            text-align: center;
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid #e1e4e8;
            color: #586069;
            font-size: 0.85rem;
        }
    </style>
</head>
<body>
    <div class="container">
        {{content}}
        <div class="footer">
            OpenStack Simulator &mdash; In-memory training environment
        </div>
    </div>
    <script>
    (function () {
        function fallbackCopy(text) {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.top = '-1000px';
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); } catch (e) {}
            document.body.removeChild(ta);
        }
        function showCopied(btn) {
            btn.textContent = 'Copied';
            btn.classList.add('copied');
            setTimeout(function () {
                btn.textContent = 'Copy';
                btn.classList.remove('copied');
            }, 1500);
        }
        document.addEventListener('click', function (event) {
            var btn = event.target.closest ? event.target.closest('.copy-btn') : null;
            if (!btn) { return; }
            var pre = btn.parentElement.querySelector('pre');
            if (!pre) { return; }
            var text = pre.textContent;
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(function () {
                    showCopied(btn);
                }, function () {
                    fallbackCopy(text);
                    showCopied(btn);
                });
            } else {
                fallbackCopy(text);
                showCopied(btn);
            }
        });
    })();
    </script>
</body>
</html>"""

_FENCE_OPEN_RE = re.compile(r"^([ \t]+)(`{3,}|~{3,})(.*)$")


def _dedent_fences(md: str) -> str:
    """Remove indentation from indented fenced code blocks.

    Fences opened with leading whitespace (e.g. inside list items) are
    emitted at column 0, with their content dedented by the same amount,
    and a blank line is ensured before the opening fence.
    """
    out: list[str] = []
    in_fence = False
    indent = ""
    marker = ""
    for line in md.split("\n"):
        if not in_fence:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                indent, marker = m.group(1), m.group(2)
                in_fence = True
                if out and out[-1].strip() != "":
                    out.append("")
                out.append(marker + m.group(3))
            else:
                out.append(line)
            continue
        if line.strip() == "":
            out.append(line)
            continue
        if line.startswith(indent):
            stripped = line[len(indent):]
        else:
            stripped = line.lstrip(" \t")
        if line.lstrip(" \t").startswith(marker):
            in_fence = False
            out.append(stripped)
            continue
        out.append(stripped)
    return "\n".join(out)


_PRE_BLOCK_RE = re.compile(r"<pre\b.*?</pre>", re.DOTALL)
_PRE_PARTS_RE = re.compile(
    r"^(<pre\b[^>]*>(?:<span></span>)?(?:<code\b[^>]*>)?)(.*?)((?:</code>)?</pre>)$",
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_COPY_BUTTON = '<button type="button" class="copy-btn" aria-label="Copy code">Copy</button>'


def _wrap_comment_line(line: str) -> str:
    """Wrap a line whose visible text starts with '#' in span.code-comment.

    Highlighter spans inside the line are kept and nested. Lines with
    unbalanced <span> tags (a span crossing lines) are left untouched so the
    result stays well-formed.
    """
    if line.count("<span") != line.count("</span>"):
        return line
    if not _TAG_RE.sub("", line).lstrip(" \t").startswith("#"):
        return line
    content = line.lstrip(" \t")
    indent = line[: len(line) - len(content)]
    if content.startswith("<") and not content.startswith("<span"):
        return line
    return f'{indent}<span class="code-comment">{content}</span>'


def _decorate_code_blocks(html: str) -> str:
    """Mark '#' comment lines and add a copy button wrapper around each <pre>."""

    def _decorate(match: re.Match) -> str:
        block = match.group(0)
        parts = _PRE_PARTS_RE.match(block)
        if parts:
            head, body, tail = parts.groups()
            body = "\n".join(_wrap_comment_line(l) for l in body.split("\n"))
            block = head + body + tail
        return f'<div class="code-block">{_COPY_BUTTON}{block}</div>'

    return _PRE_BLOCK_RE.sub(_decorate, html)


def _render_readme() -> str:
    """Render README.md as a styled HTML page."""
    # Look for README.md relative to the project root
    readme_path = Path(__file__).resolve().parent.parent.parent / "README.md"
    if not readme_path.exists():
        # Fallback: look in /app (Docker container)
        readme_path = Path("/app/README.md")

    if readme_path.exists():
        md_content = readme_path.read_text(encoding="utf-8")
    else:
        md_content = "# OpenStack Simulator\n\nREADME.md not found."

    # Replace localhost URLs with the actual server URL
    # Get the base URL from the current request
    base_url = f"{request.scheme}://{request.host}"
    # Add port if it's not the standard port for the scheme
    #if (request.scheme == "http" and request.environ.get('SERVER_PORT') != "80") or \
    #   (request.scheme == "https" and request.environ.get('SERVER_PORT') != "443"):
    #    base_url += f":{request.environ.get('SERVER_PORT')}"
    # The auth_url in the "Application Credentials" table must show the HTTP port
    # of the backend-component container (published as HTTP_PORT by docker-compose).
    http_port = os.environ.get("HTTP_PORT")
    backend_url = base_url
    if http_port:
        backend_url = f"{request.scheme}://{request.host.split(':')[0]}:{http_port}"
        md_content = md_content.replace(
            "| `auth_url`                      | `http://localhost:5000/identity/v3` |",
            f"| `auth_url`                      | `{backend_url}/identity/v3` |",
        )
    # The OS_AUTH_URL export must show the same value as auth_url in the table.
    auth_base = backend_url if http_port else base_url
    md_content = md_content.replace(
        "export OS_AUTH_URL=http://localhost:5000/identity/v3",
        f"export OS_AUTH_URL={auth_base}/identity/v3",
    )
    md_content = md_content.replace("http://localhost:5000", base_url)

    md_content = _dedent_fences(md_content)

    html_body = markdown.markdown(
        md_content,
        extensions=["tables", "fenced_code", "codehilite", "toc"],
    )
    html_body = _decorate_code_blocks(html_body)

    return _HTML_TEMPLATE.replace("{{content}}", html_body)
