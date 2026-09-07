from pydantic import ValidationError

async def validate_update(update: dict, schema_model):
    try:
        validated = schema_model(**update)
        return validated
    except ValidationError as e:
        return {"error": e.errors()}
