from typing import Any

from tests.sanity.inbound.http.request_body_examples import collect_request_body_examples

# Each test runs once per app (conftest.py's openapi_document fixture). The
# first three are the original author's; the last is added here
# (docs/plans/15-upstream-autumn-2026.md, Step 5, item 10).


def test_every_request_body_example_is_valid_against_its_schema(openapi_document: dict[str, Any]) -> None:
    examples = collect_request_body_examples(openapi_document)

    assert examples.invalid == []


def test_every_request_body_example_uses_only_schema_fields(openapi_document: dict[str, Any]) -> None:
    examples = collect_request_body_examples(openapi_document)

    assert examples.with_unknown_fields == []


def test_every_request_body_has_an_example_with_all_schema_fields(openapi_document: dict[str, Any]) -> None:
    examples = collect_request_body_examples(openapi_document)

    assert examples.operations_without_complete_example == []


def test_every_request_body_declares_an_example(openapi_document: dict[str, Any]) -> None:
    # Without this, the three checks above pass on a route with no example
    # at all: they only judge examples that exist.
    examples = collect_request_body_examples(openapi_document)

    assert examples.operations_without_example == []
