[![Mentioned in Awesome FastAPI](https://awesome.re/mentioned-badge.svg)](https://github.com/mjhea0/awesome-fastapi?tab=readme-ov-file#best-practices)

Stay tuned. Refactor in progress, see [`legacy-2025`](https://github.com/ivan-borovets/fastapi-clean-example/tree/legacy-2025) branch for architecture docs

TODO:
- [x] Write tests
- [ ] Explain code and patterns in new README
- [ ] Make template project

Prerequisites
```shell
uv sync
source .venv/bin/activate
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Start in Docker
```shell
make upd
```

Start locally
```shell
make upd-local
alembic upgrade head
uvicorn app.main.run:make_app --host 0.0.0.0 --port 8000 --reload
# or `src/app/main/run.py` in IDE
```
Full API access:
- create user via sign up
- set its role to `super_admin` manually in DB
- log in as super admin

### Database Management (Adminer)

To inspect and manage the PostgreSQL database visually, open a separate terminal and run Adminer (version 4 is recommended for network compatibility):
```shell
docker run --rm -p 8080:8080 --network fastapi-clean-example_default -e ADMINER_DEFAULT_SERVER=db_pg adminer:4
```
Access it at **http://localhost:8080** with the following credentials:
- **System**: PostgreSQL
- **Server**: `db_pg` (or `fastapi-clean-example-db_pg-1`)
- **Username**: `postgres`
- **Password**: `password`
- **Database**: `clean-example`

Stop
```shell
make down
```

Test (light paths)
```shell
make check
```
*Generates unit test coverage report. View in browser at `htmlcov/index.html`*

Test (all paths)
```shell
make test-docker
```
*Generates full integration test coverage report. View in browser at `htmlcov-docker/index.html`*

Generate a migration
```shell
make migration msg=<msg>
```

See [Makefile](Makefile) for more commands

## How to Commit

This project uses [pre-commit hooks](.pre-commit-config.yaml) that automatically run linting, type checking, vulnerability scanning, and formatting checks before every commit. Committing directly to `main` or `master` is blocked by the `no-commit-to-branch` hook.

### Commit Protocol

**1. Create a feature branch**
```shell
git checkout -b feature/<short-description>
```

**2. Stage and commit your changes using [Conventional Commits](https://www.conventionalcommits.org/)**
```shell
git add .
git commit -m "feat(scope): brief description (vX.Y.Z)"
```

Common prefixes: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`

**3. Switch back to master and merge**
```shell
git checkout master
git merge feature/<short-description>
```

**4. Delete the feature branch (cleanup)**
```shell
git branch -d feature/<short-description>
```

### Pre-commit Hooks Summary

| Hook | Stage | What it does |
|------|-------|-------------|
| `code-check` | pre-commit | Runs linter, formatter, and type checker (`make check`) |
| `pip-audit` | pre-commit | Scans dependencies for known security vulnerabilities |
| `test-docker` | pre-push | Runs the full integration test suite before pushing |
| `no-commit-to-branch` | pre-commit | Blocks direct commits to `main` / `master` |
| `typos` | pre-commit | Catches common spelling mistakes in code and docs |

Thanks for your patience and support

[Acknowledgements](https://github.com/ivan-borovets/fastapi-clean-example/tree/legacy-2025?tab=readme-ov-file#acknowledgements)
