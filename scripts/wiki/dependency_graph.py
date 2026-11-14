"""
Generates docs/wiki/generated/dependency-graph.md: a Mermaid diagram of the
real import graph between this app's four Clean Architecture layers, and
docs/wiki/generated/unit-graph.md: the same graph between its units (base,
shared and each module; docs/plans/16-modular-monolith.md, Step 7). Both are
built from grimp.build_graph("app") -- the same import-walking library
`import-linter` itself uses to enforce the `layers` contract in
pyproject.toml. Regenerated on every `make wiki`/`make wiki-build`, so it can
never silently drift from what the code actually does, unlike a hand-drawn
diagram.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
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
_UNIT_OUTPUT_PATH = _REPO_ROOT / "docs" / "wiki" / "generated" / "unit-graph.md"
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
    dotted name, or None if the module isn't a first-party module under one of
    those four layers (an external/third-party import, "app" itself, or a
    unit's own package with no layer below it, such as "app.modules.organizations").
    Every unit keeps the same four layers (docs/plans/16-modular-monolith.md,
    Decision 17), so the layer is read in each one:
    - base and shared, at the third name: "app.base.core.commands.create_user"
      -> "core", "app.shared.outbound.adapters.console_email_sender" -> "outbound";
    - a module, one name deeper, after the module's own name:
      "app.modules.organizations.core.commands.create_organization" -> "core".
    """
    parts = module.split(".")
    if parts[:2] in (["app", "base"], ["app", "shared"]):
        layer_position = 2
    elif parts[:2] == ["app", "modules"]:
        layer_position = 3
    else:
        return None
    # A unit's own package (e.g. "app.shared" or "app.modules.organizations")
    # has no name at the layer's position, so it belongs to no layer.
    if len(parts) <= layer_position:
        return None
    layer = parts[layer_position]
    return layer if layer in LAYERS else None


# The unit graph's name for base's main/: the composition root, the one place
# that imports every unit to register it, so the graph draws it apart from the
# rest of base (docs/plans/16-modular-monolith.md, Step 7).
_COMPOSITION_ROOT = "base/main"


def _unit_of(module: str) -> str | None:
    """
    Returns which unit a module belongs to, as the unit graph names it, or None
    if the module isn't in a unit (an external/third-party import, or "app" and
    "app.modules" themselves):
    - "app.base.main..." -> "base/main", the composition root (see above);
    - the rest of "app.base..." -> "base";
    - "app.shared..." -> "shared";
    - "app.modules.<name>..." -> "<name>", e.g. "organizations".
    """
    parts = module.split(".")
    if parts[:3] == ["app", "base", "main"]:
        return _COMPOSITION_ROOT
    if parts[:2] in (["app", "base"], ["app", "shared"]):
        return parts[1]
    if parts[:2] == ["app", "modules"] and len(parts) > 2:
        return parts[2]
    return None


def _edges_between(
    graph: grimp.ImportGraph,
    group_of: Callable[[str], str | None],
    ignored_imports: frozenset[tuple[str, str]] | set[tuple[str, str]],
) -> set[tuple[str, str]]:
    """
    Walks every direct import in the graph and reduces it to an
    (importer_group, imported_group) pair, where `group_of` names a module's
    group (its layer, or its unit), deduplicated. It drops imports inside one
    group (not interesting at this granularity), anything involving a module
    `group_of` puts in no group, and any exact (importer, imported) pair
    present in `ignored_imports` (see `load_ignored_imports`).
    """
    edges: set[tuple[str, str]] = set()
    for importer in graph.modules:
        importer_group = group_of(importer)
        if importer_group is None:
            continue
        for imported in graph.find_modules_directly_imported_by(importer):
            if (importer, imported) in ignored_imports:
                continue
            imported_group = group_of(imported)
            if imported_group is None or imported_group == importer_group:
                continue
            edges.add((importer_group, imported_group))
    return edges


def build_layer_edges(
    graph: grimp.ImportGraph,
    ignored_imports: frozenset[tuple[str, str]] | set[tuple[str, str]] = frozenset(),
) -> set[tuple[str, str]]:
    """The layer-to-layer edges, e.g. ("inbound", "core"), across every unit (see `_layer_of`)."""
    return _edges_between(graph, _layer_of, ignored_imports)


def build_unit_edges(
    graph: grimp.ImportGraph,
    ignored_imports: frozenset[tuple[str, str]] | set[tuple[str, str]] = frozenset(),
) -> set[tuple[str, str]]:
    """The unit-to-unit edges, e.g. ("notifications", "organizations") (see `_unit_of`)."""
    return _edges_between(graph, _unit_of, ignored_imports)


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


def _mermaid_id(unit: str) -> str:
    """A unit's Mermaid node id: its name, with "/" (which Mermaid can't parse in an id) as "_"."""
    return unit.replace("/", "_")


def render_unit_mermaid(edges: set[tuple[str, str]]) -> str:
    """
    Renders the given unit-to-unit edges as a complete wiki page fragment, in
    the same shape as `render_mermaid`: a `!!! figure` admonition wrapping a
    `flowchart TB` Mermaid diagram (top to bottom, so base/main sits above the
    units and base below them), one node per unit that has an arrow, one arrow
    per distinct edge found. Unlike the four layers, the units aren't a fixed
    list: they are whatever the edges name, so a new module appears on its own.
    """
    units = sorted({unit for edge in edges for unit in edge})
    node_lines = [f'        {_mermaid_id(unit)}["{unit}"]' for unit in units]
    edge_lines = [
        f"        {_mermaid_id(importer)} --> {_mermaid_id(imported)}" for importer, imported in sorted(edges)
    ]
    style_lines = [f"        style {_mermaid_id(unit)} stroke-width:1px,stroke:#333333" for unit in units]

    diagram_body = "\n".join([*node_lines, "", *edge_lines]) if edge_lines else "\n".join(node_lines)

    diagram_note = (
        "Every arrow above is a real, currently-existing import from one unit to another, discovered by walking "
        "the actual `app` package's import graph — not hand-drawn. `base/main` is base's composition root, the one "
        "place that imports every unit to register it. The rest of `base` imports no unit, modules depend on each "
        "other one way only, and only `base/main` imports `shared`: rules that "
        "[`import-linter`](https://github.com/seddonym/import-linter)'s `unit-order`, `module-order` and "
        "`shared-internals` contracts (see "
        "[Layer Dependencies & Import Rules](../content/architecture/layer-dependencies.md)) enforce in `make check`."
    )

    return f"""<!-- AUTO-GENERATED by scripts/wiki/dependency_graph.py -- do not edit by hand.
     Regenerated on every `make wiki`/`make wiki-build` from the real `app`
     package's import graph via `grimp.build_graph("app")`. -->

!!! figure "Real unit-to-unit import graph (generated from `grimp.build_graph(\\"app\\")`)"
    ```mermaid
    {_MERMAID_INIT}
    flowchart TB
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
    ignored_imports = load_ignored_imports()
    edges = build_layer_edges(graph, ignored_imports=ignored_imports)
    content = render_mermaid(edges)
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(content)
    print(f"Wrote {_OUTPUT_PATH}")
    # The unit graph, on its own page (docs/plans/16-modular-monolith.md, Step 7).
    _UNIT_OUTPUT_PATH.write_text(render_unit_mermaid(build_unit_edges(graph, ignored_imports=ignored_imports)))
    print(f"Wrote {_UNIT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
