#!/bin/bash
set -e

# Initialize default user credentials
python init_default_user.py

# Start the application
exec "$@"