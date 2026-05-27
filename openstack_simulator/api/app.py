"""Flask application factory for the OpenStack Simulator API."""

from __future__ import annotations

import os
from pathlib import Path

import markdown
from flask import Flask, request

from openstack_simulator.simulator import Simulator
from openstack_simulator.api.identity import identity_bp
from openstack_simulator.api.compute import compute_bp
from openstack_simulator.api.network import network_bp
from openstack_simulator.api.volume import volume_bp


def create_app(config: dict | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        config: Optional simulator configuration overrides.

    Returns:
        Configured Flask app with all OpenStack API blueprints registered.
    """
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Create a single Simulator instance shared across all requests
    simulator = Simulator(config)
    app.config["SIMULATOR"] = simulator

    # Fake project/domain IDs used throughout responses
    app.config["PROJECT_ID"] = "fake-project-id-00000000001"
    app.config["DOMAIN_ID"] = "default"
    app.config["DOMAIN_NAME"] = "Default"
    app.config["REGION"] = "RegionOne"

    # Register blueprints for each OpenStack service
    app.register_blueprint(identity_bp)
    app.register_blueprint(compute_bp)
    app.register_blueprint(network_bp)
    app.register_blueprint(volume_bp)

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

    html_body = markdown.markdown(
        md_content,
        extensions=["tables", "fenced_code", "codehilite", "toc"],
    )

    return _HTML_TEMPLATE.replace("{{content}}", html_body)


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
        }
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
</body>
</html>"""
