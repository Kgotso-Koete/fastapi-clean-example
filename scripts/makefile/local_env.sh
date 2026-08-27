#!/bin/bash
# The script is called from Makefile
set -eu -o pipefail

{
  echo "# This .env file is generated automatically for LOCAL environment by Makefile."
  echo "# Do not edit it directly; edit env.example / .secrets and Makefile instead."
  echo
  sed \
    -e 's|^EXAMPLE_SERVICE_URL=.*|EXAMPLE_SERVICE_URL=http://127.0.0.1:51999|' \
    -e 's|^POSTGRES_HOST=.*|POSTGRES_HOST=127.0.0.1|' \
    -e 's|^REDIS_HOST=.*|REDIS_HOST=127.0.0.1|' \
    env.example
  if [ -f .secrets ]; then
    echo
    echo "# --- secrets from .secrets (not committed) ---"
    cat .secrets
    echo # guarantee a trailing newline even if .secrets' last line lacks one
  fi
} > .env

# COMPOSE_PROFILES is derived from CELERY_ENABLED and ENVIRONMENT, not set
# independently -- CELERY_ENABLED is the one setting that decides whether
# this deployment uses Celery at all. Appended last so it wins (.env parsing
# is last-value-wins) over anything set earlier in env.example/.secrets.
# "celery-development" additionally covers services that need both toggles at once
# (flower, redis-commander): a single service's profiles list is OR-matched
# against COMPOSE_PROFILES, so that AND has to be computed here instead.
celery_enabled=$(grep -E '^CELERY_ENABLED=' .env | tail -1 | cut -d= -f2)
environment=$(grep -E '^ENVIRONMENT=' .env | tail -1 | cut -d= -f2)
if [ "$environment" != "development" ] && [ "$environment" != "production" ]; then
  echo "ERROR: ENVIRONMENT must be exactly 'development' or 'production' (got: '$environment')" >&2
  exit 1
fi
profiles=""
[ "$celery_enabled" != "false" ] && profiles="${profiles}celery,"
[ "$environment" = "development" ] && profiles="${profiles}development,"
if [ "$celery_enabled" != "false" ] && [ "$environment" = "development" ]; then
  profiles="${profiles}celery-development,"
fi
echo "COMPOSE_PROFILES=${profiles%,}" >> .env

# Prometheus/Grafana have no native way to read env vars into their own
# mounted config files (unlike Promtail's -config.expand-env) -- so their
# real config is generated from a .template here, the same way .env itself
# is generated above. See the .template files' own header comment.
app_service_name=$(grep -E '^APP_SERVICE_NAME=' .env | tail -1 | cut -d= -f2)
sed "s|\${APP_SERVICE_NAME}|${app_service_name}|g" \
  observability/prometheus/prometheus.yml.template > observability/prometheus/prometheus.yml
sed "s|\${APP_SERVICE_NAME}|${app_service_name}|g" \
  observability/grafana/provisioning/dashboards/dashboards.yml.template > observability/grafana/provisioning/dashboards/dashboards.yml

# app-overview.json's PromQL queries reference metric names prefixed by
# AppSettings.SERVICE_NAME with hyphens replaced by underscores (see
# main/setup.py's Instrumentator(metric_namespace=...)) -- Prometheus metric
# names can't contain hyphens, so this needs the normalized form, unlike the
# raw value used for the dashboard's own title/tags above.
app_service_name_metric="${app_service_name//-/_}"
sed -e "s|\${APP_SERVICE_NAME_METRIC}|${app_service_name_metric}|g" \
    -e "s|\${APP_SERVICE_NAME}|${app_service_name}|g" \
  observability/grafana/provisioning/dashboards/app-overview.json.template > observability/grafana/provisioning/dashboards/app-overview.json
