async def validation_router(update_result: dict) -> dict:
    """Route based on validation success or failure (placeholder)."""
    if isinstance(update_result, dict) and update_result.get("error"):
        return {"route": "repair", "detail": update_result}
    return {"route": "merge", "detail": update_result}
