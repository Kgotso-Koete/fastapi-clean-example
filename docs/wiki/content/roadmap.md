# Roadmap

!!! sourcefiles "Relevant Source Files/Folders"
    - [`docs/plans/0-production-readiness-roadmap.md`](../../../docs/plans/0-production-readiness-roadmap.md) — the real, single-sourced file this page transcludes below
    - [`README.md`](../../../README.md) — its own TODO checklist mirrors this same file and is kept in sync with it by hand (this wiki page and the include below need no such manual sync — see the note below)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## Why this page is just a transclusion

This page has no content of its own below this point — it pulls in the repo root's real `docs/plans/0-production-readiness-roadmap.md` verbatim, via `mkdocs-include-markdown-plugin`, every time the wiki builds. This is the same single-sourcing principle [Changelog](changelog.md) follows: the roadmap is a living, frequently-updated tracking document, not something to snapshot into a second copy here that can silently fall out of date. `README.md` maintains its own condensed checklist version of this same file by hand, kept in sync manually on every change — this page instead includes the real thing directly, so there is nothing to keep in sync at all.

---

{% include-markdown "../../../docs/plans/0-production-readiness-roadmap.md" %}

---

## Where to go next

- **Want to see what's already shipped, not just what's outstanding?** [Changelog](changelog.md).
- **Curious about the reasoning behind a specific gap called out here?** Some map to a real callout elsewhere in this wiki — e.g. the `redis` double-`make down` quirk, mentioned on both [Quick Start with Docker](getting-started/quick-start-docker.md) and [Quick Start Locally](getting-started/quick-start-local.md).
