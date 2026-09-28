#!/bin/sh
# Workflows and credentials are managed as code: re-imported and published on every start, then n8n starts.
set -eu
umask 077
node /bootstrap/render_credentials.js > /tmp/credentials.json
n8n import:credentials --input=/tmp/credentials.json
rm -f /tmp/credentials.json
n8n import:workflow --separate --input=/bootstrap/workflows
for wf in /bootstrap/workflows/*.json; do
  id=$(node -e 'process.stdout.write(require(process.argv[1]).id)' "$wf")
  n8n publish:workflow --id="$id"
done

# Create the instance owner once n8n is up, so the editor opens without a manual sign-up (no-op if one exists).
node /bootstrap/setup_owner.js &

exec /sbin/tini -- n8n start
