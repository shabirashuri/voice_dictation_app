async def merge_state(state, validated_update: dict):
    """Merge validated update into the report state (placeholder)."""
    state.merge_updates([validated_update])
    return state
