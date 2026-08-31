# Multi-Stage Docker Build

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Dockerfile`](../../../../Dockerfile) — the single build this page walks through
    - [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh) — what the image's `ENTRYPOINT` hands off to at runtime
    - [`pyproject.toml`](../../../../pyproject.toml) — the `dev` dependency group (`[dependency-groups]`) that `--no-dev`/`--dev` includes or excludes

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## A note on the name, grounded in the actual file

Worth being precise about up front: [`Dockerfile`](../../../../Dockerfile) has exactly **one** `FROM` instruction — it is not "multi-stage" in the strict Docker sense of multiple `FROM ... AS <stage>` blocks with a final `COPY --from=<stage>`. What it *does* do is split into distinct **phases** within that single stage — a dependency-install phase before the source is even copied in, and an application-install phase after — plus an `ENVIRONMENT` build argument that changes which dependency group gets installed. That two-phase structure, not a literal multi-stage `FROM` chain, is what the rest of this page explains.

## The build pipeline

!!! figure "Every instruction in Dockerfile, in the order it actually runs"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        base["FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim"] --> guard{"ENVIRONMENT arg is\n'development' or 'production'?"}
        guard -->|no| fail(["hard error — build stops"])
        guard -->|yes| envsetup["Set ENV: UV_PROJECT_ENVIRONMENT=/usr/local,\nUV_LINK_MODE=copy, PYTHONUNBUFFERED=1, ..."]

        subgraph depslayer["Dependency layer (cache-friendly)"]
            envsetup --> copymanifests["COPY pyproject.toml uv.lock README.md ./"]
            copymanifests --> synccheck1{"ENVIRONMENT?"}
            synccheck1 -->|production| syncprod1["uv sync --no-dev --no-install-project"]
            synccheck1 -->|development| syncdev1["uv sync --dev --no-install-project"]
        end

        subgraph applayer["Application layer"]
            syncprod1 --> copysrc["COPY . ."]
            syncdev1 --> copysrc
            copysrc --> synccheck2{"ENVIRONMENT?"}
            synccheck2 -->|production| syncprod2["uv sync --no-dev"]
            synccheck2 -->|development| syncdev2["uv sync --dev"]
        end

        subgraph runtimeuser["Runtime hardening"]
            syncprod2 --> nonroot["groupadd/useradd runner\nchown -R runner:root /code\nchmod -R g=u /code"]
            syncdev2 --> nonroot
            nonroot --> userstep["USER runner"]
        end

        userstep --> entrypoint["ENTRYPOINT docker-entrypoint.sh"]

        linkStyle default stroke-width:3px,stroke:#333333
        style depslayer stroke-width:1px,stroke:#333333
        style applayer stroke-width:1px,stroke:#333333
        style runtimeuser stroke-width:1px,stroke:#333333
    ```

    > Reading this top to bottom against the real file:
    >
    > 1. **Base image** — `ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-trixie-slim` (`PYTHON_VERSION` defaults to `3.13`). This is an official `uv`-maintained image: Python plus the `uv` package manager already installed, on a slim Debian ("trixie") base — nothing to separately `pip install uv` for.
    > 2. **The `ENVIRONMENT` guard** — a `RUN` that hard-fails the build (`exit 1`) unless the `ENVIRONMENT` build arg is exactly `development` or `production`. This is the same fail-fast validation `scripts/makefile/docker_env.sh` and `AppSettings.ENVIRONMENT` both independently enforce — a misspelled value is caught here too, not silently treated as production or ignored.
    > 3. **Environment setup** — `PYTHONDONTWRITEBYTECODE=1`/`PYTHONUNBUFFERED=1` (standard container Python hygiene: no stray `.pyc` files, unbuffered stdout so `docker logs` shows output immediately), `UV_HTTP_TIMEOUT=300` (a generous package-download timeout), `UV_LINK_MODE=copy` (copy packages into place instead of hardlinking — avoids link errors across filesystem boundaries in a container build), and `UV_PROJECT_ENVIRONMENT=/usr/local` (installs straight into the system Python's site-packages rather than creating a `.venv` — there's no separate venv to activate anywhere downstream, in `docker-entrypoint.sh` or otherwise).
    > 4. **Dependency layer** — `COPY pyproject.toml uv.lock README.md ./` copies *only* the dependency manifests, deliberately before the rest of the source tree. The following `uv sync --frozen --no-cache --no-install-project` (with `--no-dev` in production, `--dev` in development) installs every third-party dependency but explicitly skips installing this project's own code (`--no-install-project`), since it hasn't been copied in yet.
    > 5. **Application layer** — `COPY . .` now copies the full repository in, and a second `uv sync --frozen --no-cache` (again `--no-dev`/`--dev`) runs — this time without `--no-install-project`, so it installs the project itself on top of the dependencies already in place.
    > 6. **Runtime hardening** — a dedicated `runner` group and user are created, and `/code` is `chown`ed/`chmod`ed (`g=u`, giving the group the same permissions as the owner) so the container never runs as `root` at runtime. `USER runner` switches to it for every instruction after.
    > 7. **`ENTRYPOINT`** — `["/code/docker-entrypoint.sh"]`. The image itself doesn't hardcode a single command; [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh) dispatches on its first argument (`start`, `worker`, `pytest`, or anything else via a plain `exec "$@"` fallback) — which is exactly how `app`, `worker`, and `wiki` share this one image but run three different things (see [Docker Containers](docker-containers.md)).

## Why the split exists

!!! figure "What Docker's layer cache actually re-runs on each kind of edit"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph editcode["Edit only src/app/*.py"]
            c1["COPY manifests — cache HIT"] --> c2["dependency uv sync — cache HIT, skipped"]
            c2 --> c3["COPY . . — invalidated"]
            c3 --> c4["uv sync (project) — reruns"]
        end

        subgraph editmanifest["Edit pyproject.toml / uv.lock"]
            m1["COPY manifests — invalidated"] --> m2["dependency uv sync — reruns"]
            m2 --> m3["COPY . . — invalidated"]
            m3 --> m4["uv sync (project) — reruns"]
        end

        linkStyle default stroke-width:3px,stroke:#333333
        style editcode stroke-width:1px,stroke:#333333
        style editmanifest stroke-width:1px,stroke:#333333
    ```

    > Two independent reasons this Dockerfile is shaped the way it is, both visible directly in the diagrams above:
    >
    > - **Layer-cache-friendly ordering.** Docker caches each instruction's result and only re-runs an instruction (and everything after it) once something it depends on changes. Copying `pyproject.toml`/`uv.lock`/`README.md` *before* the rest of the source means editing application code (the overwhelmingly common case) never invalidates the dependency-install layer — only the much cheaper "copy full source + install this project" layer reruns. Editing a dependency manifest is the one case that busts the cache all the way back, which is correct: the dependency set actually changed.
    > - **One Dockerfile, two different final images.** The `ENVIRONMENT` build arg — not a separate Dockerfile, not a separate `docker-compose.yml` service definition — decides whether `uv sync` runs with `--dev` or `--no-dev` (both times, dependency layer and application layer alike). A production image never has `pytest`, `mypy`, `ruff`, `mkdocs`, or `radon` installed at all (see the `dev` group in [`pyproject.toml`](../../../../pyproject.toml)) — smaller image, smaller attack surface — while a development image (what `app`/`worker`/`wiki` build as by default, and what `make test-docker` exercises) has the full toolchain available inside the same running container. See [Production Deployment](production-deployment.md) for what else this same `ENVIRONMENT` value changes beyond just this build.
    > - **Non-root user as its own late step.** Deferring `USER runner` until after both `uv sync` calls means the installs themselves (which may need to write into `/usr/local`) run with sufficient privilege, while the actual running container — the thing exposed to the network — never runs as `root`.

## Where to go next

- [Docker Containers](docker-containers.md) — which three services (`app`, `worker`, `wiki`) actually build this image, and what each runs via `docker-entrypoint.sh`.
- [Production Deployment](production-deployment.md) — the full list of what changes, beyond just this build, when `ENVIRONMENT=production`.
- [Container Orchestration & Profiles](container-orchestration.md) — how the same `ENVIRONMENT` value also decides which *containers* start, not just what's inside the ones that do.
