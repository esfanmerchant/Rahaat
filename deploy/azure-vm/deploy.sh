#!/bin/sh
# Run on the VM from the repo root's deploy/azure-vm folder:
#   cd ~/rahat/deploy/azure-vm && ./deploy.sh
# Pulls the latest code, rebuilds the image and restarts the stack.
set -eu
cd "$(dirname "$0")"
[ -f .env ] || { echo "Missing deploy/azure-vm/.env (copy ../../.env.example and fill it)"; exit 1; }
git -C ../.. pull --ff-only
docker compose build
docker compose up -d
docker image prune -f
sleep 5
docker compose ps
