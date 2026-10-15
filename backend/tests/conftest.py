import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import auth as auth_routes
from app.api.routes import cases as cases_routes
from app.api.websocket import voice as voice_ws
from app.db.models.report import Base
from app.db.session import get_db, get_session_factory

TEST_JWT_SECRET = "test-secret-" + "x" * 32


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")  # fast hashing in tests


@pytest_asyncio.fixture
async def session_factory():
    """Fresh in-memory SQLite database per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def app(session_factory):
    async def _get_db():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(cases_routes.router)
    app.include_router(voice_ws.router)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    return app


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def signup(client, email="doc@example.com", name="Dr. House", password="correct-horse"):
    res = await client.post("/auth/signup", json={"email": email, "full_name": name, "password": password})
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}, res.json()


async def create_case(client, headers, patient_name="John Doe", patient_mrn=None):
    res = await client.post("/cases", json={"patient_name": patient_name, "patient_mrn": patient_mrn}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()
