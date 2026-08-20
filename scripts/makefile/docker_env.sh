#!/bin/bash
# The script is called from Makefile
set -eu -o pipefail

{
  echo "# This .env file is generated automatically for DOCKER environment by Makefile."
  echo "# Do not edit it directly; edit env.example / .secrets and Makefile instead."
  echo
  cat env.example
  if [ -f .secrets ]; then
    echo
    echo "# --- secrets from .secrets (not committed) ---"
    cat .secrets
    echo # guarantee a trailing newline even if .secrets' last line lacks one
  fi
} > .env

# COMPOSE_PROFILES is derived from CELERY_ENABLED, not set independently --
# CELERY_ENABLED is the one setting that decides whether this deployment
# uses Celery at all. Appended last so it wins (.env parsing is
# last-value-wins) over anything set earlier in env.example/.secrets.
celery_enabled=$(grep -E '^CELERY_ENABLED=' .env | tail -1 | cut -d= -f2)
if [ "$celery_enabled" = "false" ]; then
  echo "COMPOSE_PROFILES=" >> .env
else
  echo "COMPOSE_PROFILES=celery" >> .env
fi
