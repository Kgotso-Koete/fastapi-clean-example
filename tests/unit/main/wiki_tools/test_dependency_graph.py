import grimp

from scripts.wiki.dependency_graph import (
    LAYERS,
    build_app_graph,
    build_layer_edges,
    load_ignored_imports,
    render_mermaid,
)


def _fixture_graph() -> grimp.ImportGraph:
    graph = grimp.ImportGraph()
    # main -> inbound (allowed, adjacent)
    graph.add_import(importer="app.main.run", imported="app.inbound.http.root_router")
    # inbound -> outbound (allowed, adjacent)
    graph.add_import(importer="app.inbound.http.users.router", imported="app.outbound.adapters.sqla_user_reader")
    # outbound -> core (allowed, adjacent)
    graph.add_import(
        importer="app.outbound.adapters.sqla_user_reader",
        imported="app.core.queries.ports.user_reader",
    )
    # main -> core (allowed, skip-level)
    graph.add_import(importer="app.main.ioc.core", imported="app.core.commands.create_user")
    # intra-core import: same layer, must not appear as a layer-to-layer edge
    graph.add_import(importer="app.core.commands.create_user", imported="app.core.common.services.user")
    # an import outside the four known layers (e.g. a third-party/root module): must be ignored
    graph.add_import(importer="app.core.commands.create_user", imported="pydantic.BaseModel")
    return graph


def test_build_layer_edges_extracts_cross_layer_edges_only() -> None:
    edges = build_layer_edges(_fixture_graph())

    assert edges == {
        ("main", "inbound"),
        ("inbound", "outbound"),
        ("outbound", "core"),
        ("main", "core"),
    }


def test_build_layer_edges_ignores_modules_outside_the_four_layers() -> None:
    graph = grimp.ImportGraph()
    graph.add_import(importer="app.core.commands.create_user", imported="pydantic.BaseModel")
    graph.add_import(importer="somethingelse.module", imported="app.core.commands.create_user")

    edges = build_layer_edges(graph)

    assert edges == set()


def test_load_ignored_imports_finds_the_real_alembic_exception() -> None:
    """
    Confirms the real pyproject.toml still carves out the known, deliberate
    outbound -> main exception for alembic's env.py needing DB settings --
    if this ever disappears from pyproject.toml, this test should fail loudly
    rather than the generator silently starting to render a "violation" edge
    that used to be an accepted exception.
    """
    ignored = load_ignored_imports()

    assert ("app.outbound.persistence_sqla.alembic.env", "app.main.config.loader") in ignored
    assert ("app.outbound.persistence_sqla.alembic.env", "app.main.config.settings") in ignored


def test_build_layer_edges_matches_the_real_app_graph_direction() -> None:
    """
    A second, independent check on the same layering invariant `import-linter`'s
    own `layers` contract already enforces (see pyproject.toml's
    [[tool.importlinter.contracts]] `clean-architecture` id) -- core must never
    import outward, and no layer may import main.
    """
    real_graph = build_app_graph()

    edges = build_layer_edges(real_graph, ignored_imports=load_ignored_imports())

    forbidden = {
        ("core", "outbound"),
        ("core", "inbound"),
        ("core", "main"),
        ("outbound", "inbound"),
        ("outbound", "main"),
        ("inbound", "main"),
    }
    assert edges.isdisjoint(forbidden)


def test_render_mermaid_produces_a_fenced_block_naming_every_layer_with_an_edge() -> None:
    markdown = render_mermaid({("main", "inbound"), ("inbound", "core")})

    assert markdown.count("```mermaid") == 1
    assert markdown.count("```") == 2
    assert "main" in markdown
    assert "inbound" in markdown
    assert "core" in markdown


def test_render_mermaid_with_no_edges_still_produces_a_valid_fence() -> None:
    markdown = render_mermaid(set())

    assert "```mermaid" in markdown
    for layer in LAYERS:
        assert layer in markdown
