#!/bin/bash
set -e

TOKEN="$1"
if [ -z "$TOKEN" ]; then
  echo "Usage: bash add-windsurf-account.sh <windsurf-ott-token>"
  echo "Get token from: https://windsurf.com/show-auth-token"
  exit 1
fi

API_KEY=$(grep '^API_KEY=' /opt/WindsurfAPI/.env | cut -d= -f2)

python3 -c "
import json, urllib.request
data = json.dumps({'token': '$TOKEN'}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:3003/auth/login',
    data=data,
    headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $API_KEY',
    }
)
try:
    r = urllib.request.urlopen(req, timeout=60)
    print('OK:', r.read().decode()[:300])
except Exception as e:
    b = e.read().decode()[:300] if hasattr(e, 'read') else ''
    print('Error:', e, b)
    exit(1)
"
