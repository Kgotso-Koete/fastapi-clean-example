from fastapi import APIRouter

router = APIRouter()


# Trailing slash like every other route, which
# tests/sanity/inbound/http/test_openapi_trailing_slashes.py enforces
# (docs/plans/15-upstream-autumn-2026.md, Step 5, item 10).
@router.get("/test-error/")
async def test_error() -> None:
    """Temporary endpoint to trigger 500 error for testing alerting.

    Remove this file after testing alerting functionality.
    """
    raise ValueError("Test error for alerting - this triggers a 500 and email alert")
