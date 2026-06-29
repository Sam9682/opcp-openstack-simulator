#!/bin/bash

# Test script to verify the correct authentication format

echo "Testing OpenStack authentication with correct JSON format..."

# Clear any existing proxy settings temporarily
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

# Test with the correct JSON structure for application credential authentication
curl -v --noproxy "*" -X POST http://localhost:5000/identity/v3/auth/tokens \
  -H "Content-Type: application/json" \
  -d '{
    "auth": {
      "identity": {
        "application_credential": {
          "id": "simulator-app-credential",
          "secret": "simulator-secret"
        }
      }
    }
  }'

echo ""
echo ""
echo "Testing with different JSON structure (password-based):"
curl -v --noproxy "*" -X POST http://localhost:5000/identity/v3/auth/tokens \
  -H "Content-Type: application/json" \
  -d '{
    "auth": {
      "identity": {
        "password": {
          "user": {
            "name": "simulator-user",
            "password": "simulator-password"
          }
        }
      }
    }
  }'