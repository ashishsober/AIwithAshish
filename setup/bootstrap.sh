#!/usr/bin/env bash
# One-time setup on the Mac for Qwen Chat history (chat-api). Safe to re-run. Prints no secret values.
#   1. creates the chat_db database and its tables (sql/001_chat_db.sql)
#   2. creates the MySQL user chat_api (only SELECT/INSERT/UPDATE/DELETE on chat_db) with a new random password
#   3. creates the Kubernetes Secret chat-secrets (CHAT_DB_HOST/USER/PASSWORD) and restarts chat-api
# Asks once for the MySQL admin password. Needs auth-api set up first (it reuses auth-secrets' DB host).
# Use another MySQL admin user with: MYSQL_ADMIN=<user> setup/bootstrap.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
MYSQL_ADMIN="${MYSQL_ADMIN:-root}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

kubectl get secret auth-secrets >/dev/null || { echo "auth-secrets is missing: set up auth-api first"; exit 1; }

umask 077
tmp_sql="$(mktemp)"; tmp_env="$(mktemp)"
trap 'rm -f "$tmp_sql" "$tmp_env"' EXIT

pw="$(openssl rand -hex 16)"
{
  cat "$REPO/sql/001_chat_db.sql"
  echo "CREATE USER IF NOT EXISTS 'chat_api'@'%' IDENTIFIED BY '$pw';"
  echo "ALTER USER 'chat_api'@'%' IDENTIFIED BY '$pw';"
  echo "GRANT SELECT, INSERT, UPDATE, DELETE ON chat_db.* TO 'chat_api'@'%';"
} > "$tmp_sql"
echo "MySQL: creating chat_db and the chat_api user (password for MySQL user '$MYSQL_ADMIN'):"
mysql -u "$MYSQL_ADMIN" -p < "$tmp_sql"
echo "MySQL: done"

db_host="$(kubectl get secret auth-secrets -o jsonpath='{.data.AUTH_DB_HOST}' | base64 -d)"
printf 'CHAT_DB_HOST=%s\nCHAT_DB_USER=chat_api\nCHAT_DB_PASSWORD=%s\n' "$db_host" "$pw" > "$tmp_env"
kubectl delete secret chat-secrets --ignore-not-found >/dev/null
kubectl create secret generic chat-secrets --from-env-file="$tmp_env" >/dev/null
echo "Kubernetes: chat-secrets created"

# Running pods read Secrets only at start
if kubectl get deployment chat-api >/dev/null 2>&1; then
  kubectl rollout restart deployment/chat-api >/dev/null && echo "Restarted chat-api (new DB login)"
fi
echo "Setup done."
