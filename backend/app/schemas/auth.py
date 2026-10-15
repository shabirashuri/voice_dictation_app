from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

# bcrypt only looks at the first 72 bytes; reject longer passwords instead.
MAX_PASSWORD_BYTES = 72


class SignupRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=8)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("full_name is required")
        return value

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "UserOut":
        return cls(id=row.id, email=row.email, full_name=row.full_name, created_at=row.created_at)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
