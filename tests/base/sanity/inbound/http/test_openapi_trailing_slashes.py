from typing import Any


def test_all_public_routes_have_trailing_slash(openapi_document: dict[str, Any]) -> None:
    # Every documented route path ends in "/", this codebase's convention
    # (/api/v1/users/, /livez/). A client calling the other form gets a
    # redirect, and some clients drop the auth header or the POST body when
    # following it (the original author's test;
    # docs/plans/15-upstream-autumn-2026.md, Step 5, item 10).
    paths = openapi_document["paths"]

    without_trailing_slash = sorted(path for path in paths if not path.endswith("/"))

    assert without_trailing_slash == []
