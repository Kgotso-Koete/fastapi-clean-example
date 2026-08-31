"""
Generates docs/wiki/generated/dependency-graph.md: a Mermaid diagram of the
real import graph between this app's four Clean Architecture layers, built
from grimp.build_graph("app") -- the same import-walking library
`import-linter` itself uses to enforce the `layers` contract in
pyproject.toml. Regenerated on every `make wiki`/`make wiki-build`, so it can
never silently drift from what the code actually does, unlike a hand-drawn
diagram.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import grimp

LAYERS: tuple[str, ...] = ("main", "inbound", "outbound", "core")

_MERMAID_INIT = (
    '%%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, '
    '"flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, '
    '"subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%'
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_PATH = _REPO_ROOT / "docs" / "wiki" / "generated" / "dependency-graph.md"
_PYPROJECT_PATH = _REPO_ROOT / "pyproject.toml"
_LAYERS_CONTRACT_ID = "clean-architecture"


def load_ignored_imports(pyproject_path: Path = _PYPROJECT_PATH) -> set[tuple[str, str]]:
    """
    Reads the same `ignore_imports` list `pyproject.toml`'s `clean-architecture`
    `[[tool.importlinter.contracts]]` entry uses (e.g. the real, deliberate
    exception letting `outbound.persistence_sqla.alembic.env` reach `main.config`
    for DB settings) -- an import listed there is exempt from import-linter's
    own `layers` contract, so this generator must exempt it too, or it would
    render a "violation" edge that the actual enforced contract doesn't
    consider one.
    """
    data = tomllib.loads(pyproject_path.read_text())
    contracts = data.get("tool", {}).get("importlinter", {}).get("contracts", [])
    for contract in contracts:
        if contract.get("id") == _LAYERS_CONTRACT_ID:
            ignored = set()
            for entry in contract.get("ignore_imports", []):
                importer, imported = (part.strip() for part in entry.split("->"))
                ignored.add((importer, imported))
            return ignored
    return set()


def _layer_of(module: str) -> str | None:
    """
    Returns which of the four known layers a module belongs to, given its
    dotted name (e.g. "app.core.commands.create_user" -> "core"), or None if
    the module isn't a first-party module under one of those four layers
    (an external/third-party import, or "app" itself with no sub-layer).
    """
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "app":
        return None
    layer = parts[1]
    return layer if layer in LAYERS else None


def build_layer_edges(
    graph: grimp.ImportGraph,
    ignored_imports: frozenset[tuple[str, str]] | set[tuple[str, str]] = frozenset(),
) -> set[tuple[str, str]]:
    """
    Walks every direct import in the graph and reduces it to a
    (importer_layer, imported_layer) pair, deduplicated, dropping same-layer
    imports (not interesting at this granularity), anything involving a
    module outside the four known layers, and any exact (importer, imported)
    pair present in `ignored_imports` (see `load_ignored_imports`).
    """
    edges: set[tuple[str, str]] = set()
    for importer in graph.modules:
        importer_layer = _layer_of(importer)
        if importer_layer is None:
            continue
        for imported in graph.find_modules_directly_imported_by(importer):
            if (importer, imported) in ignored_imports:
                continue
            imported_layer = _layer_of(imported)
            if imported_layer is None or imported_layer == importer_layer:
                continue
            edges.add((importer_layer, imported_layer))
    return edges


def render_mermaid(edges: set[tuple[str, str]]) -> str:
    """
    Renders the given layer-to-layer edges as a complete wiki page fragment:
    a `!!! figure` admonition wrapping a `flowchart LR` Mermaid diagram, one
    node per layer (declared even if it has no edges, so the diagram always
    shows all four layers), one arrow per distinct edge found.
    """
    node_lines = [f'        {layer}["{layer}"]' for layer in LAYERS]
    edge_lines = [f"        {importer} --> {imported}" for importer, imported in sorted(edges)]
    style_lines = [f"        style {layer} stroke-width:1px,stroke:#333333" for layer in LAYERS]

    diagram_body = "\n".join([*node_lines, "", *edge_lines]) if edge_lines else "\n".join(node_lines)

    diagram_note = (
        "Every arrow above is a real, currently-existing import between two layers, discovered by walking the "
        "actual `app` package's import graph — not hand-drawn. It reflects exactly what "
        "[`import-linter`](https://github.com/seddonym/import-linter)'s own `layers` contract (see "
        "[Layer Dependencies & Import Rules](../content/architecture/layer-dependencies.md)) is built to "
        "police, so an illegal edge appearing here would mean that contract is already failing `make check`."
    )

    return f"""<!-- AUTO-GENERATED by scripts/wiki/dependency_graph.py -- do not edit by hand.
     Regenerated on every `make wiki`/`make wiki-build` from the real `app`
     package's import graph via `grimp.build_graph("app")`. -->

!!! figure "Real layer-to-layer import graph (generated from `grimp.build_graph(\\"app\\")`)"
    ```mermaid
    {_MERMAID_INIT}
    flowchart LR
{diagram_body}

        linkStyle default stroke-width:3px,stroke:#333333
{chr(10).join(style_lines)}
    ```

    > {diagram_note}
"""


def build_app_graph() -> grimp.ImportGraph:
    """
    Builds the real import graph with the same scan settings
    `pyproject.toml`'s `[tool.importlinter]` config uses for its own `layers`
    contract (`exclude_type_checking_imports = true`) -- a `TYPE_CHECKING`-only
    import never executes at runtime, so import-linter deliberately doesn't
    enforce the layering rule against it; this generator should see the exact
    same graph import-linter does, not a stricter or looser one.

    `cache_dir=None` disables grimp's on-disk cache (it would otherwise write
    to `./.grimp_cache` relative to the CWD): the `app`/`worker` containers
    bind-mount this repo over `/code` (see `docker-compose.yml`), which keeps
    the host's file ownership instead of the image's `runner` user, so a
    cache write there fails with a `PermissionError` under `make test-docker`.
    This runs once per `make wiki-generate` invocation anyway, so there's no
    real caching benefit to lose.
    """
    return grimp.build_graph("app", exclude_type_checking_imports=True, cache_dir=None)


def main() -> None:
    graph = build_app_graph()
    edges = build_layer_edges(graph, ignored_imports=load_ignored_imports())
    content = render_mermaid(edges)
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(content)
    print(f"Wrote {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
