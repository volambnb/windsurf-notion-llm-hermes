#!/bin/bash
set -e

TOKEN_V2="$1"
USER_ID="$2"

if [ -z "$TOKEN_V2" ] || [ -z "$USER_ID" ]; then
  echo "Usage: bash update-notion-token.sh <token_v2> <user_id>"
  echo "Get from browser DevTools > Application > Cookies > notion.so"
  exit 1
fi

ACCOUNTS_FILE="/opt/notion2api/accounts.json"

python3 -c "
import json

with open('$ACCOUNTS_FILE', 'r') as f:
    accounts = json.load(f)

accounts[0]['token_v2'] = '$TOKEN_V2'
accounts[0]['user_id'] = '$USER_ID'

with open('$ACCOUNTS_FILE', 'w') as f:
    json.dump(accounts, f, indent=2)

print('Updated token_v2 and user_id in', '$ACCOUNTS_FILE')
"

systemctl restart notion2api
echo "notion2api restarted"
