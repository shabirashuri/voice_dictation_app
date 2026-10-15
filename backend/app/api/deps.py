from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthConfigError, decode_access_token
from app.db.models.user import User
from app.db.session import get_db
from app.repositories.user import get_user

_bearer = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not signed in or session expired",
    headers={"WWW-Authenticate": "Bearer"},
)


def auth_config_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Server authentication is not configured (JWT_SECRET)",
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UNAUTHORIZED
    try:
        user_id = decode_access_token(credentials.credentials)
    except AuthConfigError:
        raise auth_config_error()
    if user_id is None:
        raise UNAUTHORIZED
    user = await get_user(db, user_id)
    if user is None:
        raise UNAUTHORIZED
    return user
