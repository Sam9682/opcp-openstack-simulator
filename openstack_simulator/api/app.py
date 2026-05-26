"""Flask application factory for the OpenStack Simulator API."""

from __future__ import annotations

from flask import Flask

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

    # Root discovery endpoint
    @app.route("/", methods=["GET"])
    def root():
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
