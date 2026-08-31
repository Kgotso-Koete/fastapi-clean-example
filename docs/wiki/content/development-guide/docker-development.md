# Docker Development Environment

!!! sourcefiles "Relevant Source Files/Folders"
    - [`docker-compose.yml`](../../../../docker-compose.yml) — the `app`/`worker`/`wiki` services' `volumes:` bind mounts, and every service definition
    - [`Dockerfile`](../../../../Dockerfile) — where dependencies actually get installed, and why that's baked into the image rather than the bind mount
    - [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh) — the `start` case's `--reload` flag, which is what makes live-reload work at all
    - [`Makefile`](../../../../Makefile) — `upd`/`up` always pass `--build --force-recreate`
    - [`pyproject.toml`](../../../../pyproject.toml) — the `uv` dependency groups that get baked into the image at build time

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

This page is about the day-to-day loop of editing code while the Docker stack is running: what updates instantly, what needs a rebuild, and how to get a shell inside a running container. For the architectural picture of these same three files — build stages, image layout, production hardening — see [Docker and Deployment → Docker Containers](../docker-deployment/docker-containers.md) and [Docker and Deployment → Multi-Stage Docker Build](../docker-deployment/multi-stage-build.md) instead; this page deliberately doesn't repeat that ground.

## The two things that can change, and what each one costs

Everything you do while developing against the Docker stack falls into one of two categories, with very different costs:

!!! figure "Dev inner loop: code edit vs. dependency edit"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph codepath["Code change — fast path, seconds"]
            edit["Edit a .py file on host"] --> mount["Bind mount<br/>volumes: .:/code"]
            mount --> watch["uvicorn --reload<br/>watches /code inside the container"]
            watch --> reload["App process reloads<br/>with the new code"]
        end

        subgraph deppath["Dependency change — rebuild path, longer"]
            editdep["Edit pyproject.toml / uv.lock"] --> baked["Dependencies are installed<br/>into the image at build time,<br/>not read from the bind mount"]
            baked --> rebuild["make upd / make up<br/>(docker compose up --build --force-recreate)"]
            rebuild --> restart["uv sync reruns during the build;<br/>container is recreated with the new deps"]
        end

        linkStyle default stroke-width:3px,stroke:#333333
        style codepath stroke-width:1px,stroke:#333333
        style deppath stroke-width:1px,stroke:#333333
    ```

    > Editing application code (anything under `src/app/`, tests, config) takes the fast path: no rebuild, no restart of the compose stack, just uvicorn's own reload. Editing `pyproject.toml` or `uv.lock` — anything that changes what's *installed* rather than what the code *does* — takes the slower path, because installed packages live inside the image's filesystem layers, not in the bind-mounted directory.

## Why code edits show up instantly: the bind mount

[`docker-compose.yml`](../../../../docker-compose.yml) mounts the entire repository into the `app`, `worker`, and `wiki` services at the same path the image itself was built from:

```yaml
volumes:
  - .:/code
```

This is a **bind mount**, not a copy: the container sees the exact same files as your host, live, with no sync delay and no rebuild. Combined with [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh)'s `start` case:

```shell
alembic upgrade head
exec uvicorn app.main.run:make_app --factory --host 0.0.0.0 --port "$PORT" --reload
```

the `--reload` flag makes `uvicorn` itself watch `/code` for `.py` changes and restart the ASGI (Asynchronous Server Gateway Interface — the standard interface async Python web servers like `uvicorn` use to talk to an app) app process when it sees one — entirely inside the running container, without Docker Compose ever being involved. Save a file on your host, and the reload happens within a second or two, the same experience as running `uvicorn --reload` locally (see [Quick Start Locally](../getting-started/quick-start-local.md)). The `worker` service uses the same bind mount, but Celery's own worker process does **not** auto-reload on code changes — restart it explicitly (`docker compose restart worker`) after editing anything the worker imports.

## Why dependency changes need a rebuild

The [`Dockerfile`](../../../../Dockerfile) installs dependencies as separate, cached `RUN` layers, before the rest of the source is even copied in:

```dockerfile
COPY pyproject.toml uv.lock README.md ./
RUN if [ "${ENVIRONMENT}" = "production" ]; then \
      uv sync --frozen --no-cache --no-dev --no-install-project; \
    else \
      uv sync --frozen --no-cache --dev --no-install-project; \
    fi
COPY . .
```

`UV_PROJECT_ENVIRONMENT=/usr/local` means these packages land in the image's own `/usr/local`, a location the bind mount never touches (the bind mount only replaces `/code`, the source tree). So if you add a dependency to `pyproject.toml` and only rely on the bind mount, the running container's Python environment never sees it — it's still running whatever was installed the last time the image was built.

This is why `make upd` and `make up` always pass `--build --force-recreate`, per [`Makefile`](../../../../Makefile):

```
upd: docker-env
	$(DOCKER_COMPOSE) up -d --build --force-recreate
```

Every time you start the stack this way, Docker re-evaluates the `Dockerfile`'s layers — if `pyproject.toml`/`uv.lock` haven't changed since the last build, the `uv sync` layer is served from cache and costs nothing; if they *have* changed, that layer (and everything after it) reruns. In practice this means: **just run `make upd` again after adding a dependency** — you don't need a separate "rebuild" command, because the ones you're already using for day-to-day startup already rebuild by default. The only case this doesn't cover is leaving the stack running continuously and wanting the new dependency without a restart at all — Docker has no mechanism for that; a container's installed packages are fixed for its lifetime.

## Attaching a shell to a running container

To poke around inside a running container — inspect the filesystem, run a one-off Python command, check an environment variable actually resolved the way you expect:

```shell
docker compose exec app bash
```

The base image (`ghcr.io/astral-sh/uv:python3.13-trixie-slim`) is Debian-based, so `bash` is available without installing anything extra. Swap `app` for `worker` or `wiki` to get a shell in either of those instead — all three share the same image. Since the repo is bind-mounted at `/code` (the `Dockerfile`'s `WORKDIR`), anything you see under `/code` in the shell is the exact same tree you're editing on your host.

A few things worth knowing once you're in:

- The process runs as the unprivileged `runner` user (`Dockerfile`'s `USER runner` — an intentional security choice: whoever created this reference project, not something to "fix"), not `root`. Most day-to-day poking around doesn't need root, but if a command genuinely does, `docker compose exec -u root app bash` overrides it for that one shell only.
- `uv`, `alembic`, `pytest`, and everything else in the `dev` dependency group are already on `PATH` (`UV_PROJECT_ENVIRONMENT=/usr/local`) — you don't need `uv run` prefix-ing every command the way you would outside a `uv sync`'d virtualenv, since there's no separate virtualenv here to activate.
- Exiting the shell (`exit` or `Ctrl+D`) does not stop the container — `bash` was a second process attached alongside the container's actual entrypoint command (`uvicorn`/`celery`), not a replacement for it.

## Where to go next

- **Want the architectural view of these same files** — build stages, image layout, why `ENVIRONMENT` is a build arg? [Docker and Deployment → Docker Containers](../docker-deployment/docker-containers.md) and [Docker and Deployment → Multi-Stage Docker Build](../docker-deployment/multi-stage-build.md).
- **Looking for the full command reference, not just the dev-loop commands mentioned here?** [Makefile Commands Reference](makefile-commands.md).
- **Prefer running `app` directly on your host instead of in a container?** [Quick Start Locally](../getting-started/quick-start-local.md) covers that path, where this rebuild-vs-reload distinction doesn't apply at all — `uv sync` on the host picks up new dependencies immediately.
