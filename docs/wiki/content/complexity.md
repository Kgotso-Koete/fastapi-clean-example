# Complexity

!!! sourcefiles "Relevant Source Files/Folders"
    - [`scripts/wiki/complexity_report.py`](../../../scripts/wiki/complexity_report.py) — the generator this page transcludes the output of
    - [`src/app/`](../../../src/app/) — the real, current source tree this report is computed from

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## Why this page is generated, not hand-written

This page has no content of its own below this point — it transcludes `docs/wiki/generated/complexity.md`, which [`scripts/wiki/complexity_report.py`](../../../scripts/wiki/complexity_report.py) regenerates on every `make wiki`/`make wiki-build`, computed directly from [`radon`](https://radon.readthedocs.io/)'s Python API (`radon.complexity.cc_visit`, `radon.metrics.mi_visit`) against the real, current contents of `src/app` — never hand-maintained, so it can't quietly drift from what the code actually looks like today. Same single-sourcing principle as [Changelog](changelog.md)/[Roadmap](roadmap.md), and the same "generate it from the real code" principle behind the [generated import graph](architecture/layer-dependencies.md#the-real-import-graph-generated-from-the-code-itself) on the Layer Dependencies page.

A high complexity or low maintainability-index score here is a place to look, not an automatic verdict — a router with many mapped exception types, or a composition-root file wiring dozens of providers, is inherently more "complex" by these metrics without necessarily being badly written.

---

{% include-markdown "../generated/complexity.md" %}

---

## Where to go next

- [Layer Dependencies & Import Rules](architecture/layer-dependencies.md) — the generated dependency graph, same "computed from real code" principle.
- [Testing → Code Quality Tools](testing/code-quality-tools.md) — where `radon` sits relative to the rest of the `make check`/`make lint` pipeline (it isn't part of it today — this report is wiki-only).
- [Roadmap](roadmap.md) — the still-open "close unit-test coverage gaps" and "add automated coverage gating" items this report is a natural companion to.
