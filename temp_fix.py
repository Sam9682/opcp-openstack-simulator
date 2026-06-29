#!/usr/bin/env python3
"""Temporary fix to ensure default user is available"""

import sys
import os
sys.path.insert(0, '/app')

from openstack_simulator.simulator import Simulator

def ensure_default_user():
    """Ensure default user exists"""
    simulator = Simulator()
    try:
        # Try to authenticate with default credentials
        token = simulator.auth_manager.authenticate("admin", "admin")
        print(f"Created default user with token: {token.id}")
        return True
    except Exception as e:
        print(f"Failed to create default user: {e}")
        return False

if __name__ == "__main__":
    ensure_default_user()