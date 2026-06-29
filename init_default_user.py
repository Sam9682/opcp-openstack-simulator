#!/usr/bin/env python3
"""Initialize default user credentials for the OpenStack Simulator."""

import os
from openstack_simulator.simulator import Simulator

def init_default_user():
    """Initialize default user credentials."""
    # Create a simulator instance
    simulator = Simulator()
    
    # Set default credentials if they're not already set
    default_username = os.getenv("DEFAULT_USERNAME", "admin")
    default_password = os.getenv("DEFAULT_PASSWORD", "admin")
    
    print(f"Initializing default user: {default_username}")
    
    # Try to authenticate with default credentials
    try:
        token = simulator.auth_manager.authenticate(default_username, default_password)
        print(f"Default user initialized with token ID: {token.id}")
    except Exception as e:
        print(f"Failed to initialize default user: {e}")
        raise

if __name__ == "__main__":
    init_default_user()