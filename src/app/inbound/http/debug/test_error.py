from fastapi import APIRouter

router = APIRouter()


@router.get("/test-error", tags=["Debug"])
async def test_error() -> None:
    """Temporary endpoint to trigger 500 error for testing alerting.

    Remove this file after testing alerting functionality.
    """
    raise ValueError("Test error for alerting - this triggers a 500 and email alert")
