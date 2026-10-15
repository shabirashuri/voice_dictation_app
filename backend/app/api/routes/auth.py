from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import auth_config_error, get_current_user
from app.core.security import AuthConfigError, burn_password_check, create_access_token, verify_password
from app.db.models.user import User
from app.db.session import get_db
from app.repositories import user as users
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_BAD_LOGIN = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")


def _token_response(user: User) -> TokenResponse:
    try:
        token, expires_in = create_access_token(user.id)
    except AuthConfigError:
        raise auth_config_error()
    return TokenResponse(access_token=token, expires_in=expires_in, user=UserOut.from_row(user))


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await users.create_user(db, body.email, body.full_name, body.password)
    except users.EmailTakenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await users.get_user_by_email(db, body.email)
    if user is None:
        burn_password_check(body.password)  # same timing as a wrong password
        raise _BAD_LOGIN
    if not verify_password(body.password, user.password_hash):
        raise _BAD_LOGIN
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.from_row(user)
