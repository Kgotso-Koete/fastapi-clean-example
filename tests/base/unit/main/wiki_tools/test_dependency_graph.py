import grimp

from scripts.wiki.dependency_graph import (
    LAYERS,
    build_app_graph,
    build_layer_edges,
    build_unit_edges,
    load_ignored_imports,
    render_mermaid,
    render_unit_mermaid,
)


def _fixture_graph() -> grimp.ImportGraph:
    graph = grimp.ImportGraph()
    # main -> inbound (allowed, adjacent)
    graph.add_import(importer="app.base.main.run", imported="app.base.inbound.http.root_router")
    # inbound -> outbound (allowed, adjacent)
    graph.add_import(
        importer="app.base.inbound.http.users.router", imported="app.base.outbound.adapters.sqla_user_reader"
    )
    # outbound -> core (allowed, adjacent)
    graph.add_import(
        importer="app.base.outbound.adapters.sqla_user_reader",
        imported="app.base.core.queries.ports.user_reader",
    )
    # main -> core (allowed, skip-level)
    graph.add_import(importer="app.base.main.ioc.core", imported="app.base.core.commands.create_user")
    # intra-core import: same layer, must not appear as a layer-to-layer edge
    graph.add_import(importer="app.base.core.commands.create_user", imported="app.base.core.common.services.user")
    # an import outside the four known layers (e.g. a third-party/root module): must be ignored
    graph.add_import(importer="app.base.core.commands.create_user", imported="pydantic.BaseModel")
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
    graph.add_import(importer="app.base.core.commands.create_user", imported="pydantic.BaseModel")
    graph.add_import(importer="somethingelse.module", imported="app.base.core.commands.create_user")

    edges = build_layer_edges(graph)

    assert edges == set()


def test_build_layer_edges_reads_the_layer_in_every_unit() -> None:
    # Every unit keeps the same four layers (docs/plans/16-modular-monolith.md,
    # Decision 17): base's at app.base.<layer>, shared's at app.shared.<layer>,
    # and each module's one level deeper, at app.modules.<name>.<layer>. Each
    # import below crosses two layers, inside one unit or across two, so each
    # must come back as an edge.
    graph = grimp.ImportGraph()
    # Inside a module: Organizations' route calls its own use case.
    graph.add_import(
        importer="app.modules.organizations.inbound.http.private_api.create_organization",
        imported="app.modules.organizations.core.commands.create_organization",
    )
    # Inside a module: Notifications' registration names its own handler.
    graph.add_import(
        importer="app.modules.notifications.main.module",
        imported="app.modules.notifications.core.common.events.handlers.send_welcome_email",
    )
    # Across units: an adapter in shared importing a port in base's core.
    graph.add_import(
        importer="app.shared.outbound.adapters.console_email_sender",
        imported="app.base.core.common.ports.email_sender",
    )

    edges = build_layer_edges(graph)

    assert edges == {("inbound", "core"), ("main", "core"), ("outbound", "core")}


def test_build_unit_edges_reduces_each_import_to_the_two_units_it_joins() -> None:
    # The unit graph (docs/plans/16-modular-monolith.md, Step 7) shows which
    # units depend on which. base's main/ is its own node, "base/main": it is the
    # composition root, the one place that imports every unit to register it,
    # and the rest of base never imports a unit (unit-order). Drawn as a single
    # "base" node, base and each module would seem to point at each other.
    graph = grimp.ImportGraph()
    # The composition root registers a module and shared, and wires up base.
    graph.add_import(importer="app.base.main.modules", imported="app.modules.organizations.main.module")
    graph.add_import(importer="app.base.main.modules", imported="app.shared.main.module")
    graph.add_import(importer="app.base.main.run", imported="app.base.inbound.http.root_router")
    # A module uses base's core, and another module's public API.
    graph.add_import(
        importer="app.modules.notifications.core.common.events.handlers.send_welcome_email",
        imported="app.base.core.common.ports.email_sender",
    )
    graph.add_import(importer="app.modules.notifications.main.module", imported="app.modules.organizations.core.api")
    # Inside one unit: no edge.
    graph.add_import(
        importer="app.modules.organizations.inbound.http.private_api.create_organization",
        imported="app.modules.organizations.core.commands.create_organization",
    )
    # Outside the app: no edge.
    graph.add_import(importer="app.shared.outbound.adapters.smtp_email_sender", imported="smtplib")
    # Alembic's env.py reads the registry: an exception the clean-architecture
    # contract lists in ignore_imports, so it is no edge here either.
    graph.add_import(importer="app.base.outbound.persistence_sqla.alembic.env", imported="app.base.main.modules")

    edges = build_unit_edges(
        graph,
        ignored_imports={("app.base.outbound.persistence_sqla.alembic.env", "app.base.main.modules")},
    )

    assert edges == {
        ("base/main", "organizations"),
        ("base/main", "shared"),
        ("base/main", "base"),
        ("notifications", "base"),
        ("notifications", "organizations"),
    }


def test_load_ignored_imports_finds_the_real_alembic_exception() -> None:
    """
    Confirms the real pyproject.toml still carves out the known, deliberate
    outbound -> main exception for alembic's env.py needing DB settings --
    if this ever disappears from pyproject.toml, this test should fail loudly
    rather than the generator silently starting to render a "violation" edge
    that used to be an accepted exception.
    """
    ignored = load_ignored_imports()

    assert ("app.base.outbound.persistence_sqla.alembic.env", "app.base.main.config.loader") in ignored
    assert ("app.base.outbound.persistence_sqla.alembic.env", "app.base.main.config.settings") in ignored


def test_build_layer_edges_matches_the_real_app_graph_direction() -> None:
    """
    A second, independent check on the same layering invariant `import-linter`'s
    own `layers` contract already enforces (see pyproject.toml's
    [[tool.importlinter.contracts]] `clean-architecture` id) -- core must never
    import outward, and no layer may import main.
    """
    real_graph = build_app_graph()

    edges = build_layer_edges(real_graph, ignored_imports=load_ignored_imports())

    # The edges must not come back empty: with none at all, the isdisjoint()
    # check below would pass without checking anything. These three exist in
    # the real code today: main wires up the routes, the routes call core use
    # cases, and the adapters implement core ports.
    assert {("main", "inbound"), ("inbound", "core"), ("outbound", "core")} <= edges

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


def test_render_unit_mermaid_draws_every_unit_and_every_arrow() -> None:
    # The unit graph's page (docs/wiki/generated/unit-graph.md): one node per
    # unit that has an arrow, one arrow per edge. Mermaid can't use "/" in a
    # node's id, so the composition root's id is base_main, and only its label
    # reads "base/main".
    markdown = render_unit_mermaid(
        {("base/main", "organizations"), ("notifications", "organizations"), ("organizations", "base")}
    )

    assert markdown.count("```mermaid") == 1
    assert markdown.count("```") == 2
    for node in (
        'base_main["base/main"]',
        'base["base"]',
        'notifications["notifications"]',
        'organizations["organizations"]',
    ):
        assert node in markdown
    for arrow in ("base_main --> organizations", "notifications --> organizations", "organizations --> base"):
        assert arrow in markdown
