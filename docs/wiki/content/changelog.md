# Changelog

!!! sourcefiles "Relevant Source Files/Folders"
    - [`CHANGELOG.md`](../../../CHANGELOG.md) — the real, single-sourced file this page transcludes below

    > This link resolves when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows it straight to the file) — it 404s in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## Why this page is just a transclusion

This page has no content of its own below this point — it pulls in the repo root's real `CHANGELOG.md` verbatim, via `mkdocs-include-markdown-plugin`, every time the wiki builds. That's deliberate, and it's the same principle every other page in this wiki follows: **the plain files are the source of truth, MkDocs is optional rendering on top of them.** Copy-pasting the changelog's content into a second, wiki-only file would create exactly the kind of drift this wiki otherwise avoids by generating diagrams from real code (`import-linter`'s dependency graph) instead of hand-drawing them once — a second copy that's edited in only one of the two places it lives.

---

{% include-markdown "../../../CHANGELOG.md" %}

---

## Where to go next

- **Curious what's still incomplete, not just what's already shipped?** [Roadmap](roadmap.md) tracks that separately.
- **Want the story behind a specific change, not just its one-line entry?** Most entries correspond to a numbered plan under `docs/plans/` — e.g. see [Core Patterns → Domain Events & the Transactional Outbox](core-patterns/domain-events-outbox.md) for the reasoning behind the transactional-outbox entries.
