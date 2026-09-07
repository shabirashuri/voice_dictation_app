from pydantic import BaseModel

class UpdateEvent(BaseModel):
    updates: list

class ValidationErrorEvent(BaseModel):
    error: dict
