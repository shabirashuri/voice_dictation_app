import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import reports as reports_routes
from app.db.models.report import Base
from app.db.session import get_db

REPORT = {
    "patient": "John Doe",
    "specimen": "Gastric biopsy",
    "gross_description": "",
    "microscopic_description": "Chronic inactive gastritis.",
    "diagnosis": "Chronic inactive gastritis.",
    "comments": "Recommend clinical correlation.",
}


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(reports_routes.router)
    app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_approved_report_and_read_it_back(client):
    res = await client.post(
        "/reports",
        json={"session_id": "s1", "case_number": "S26-0001", "report": REPORT, "comment_source": "doctor"},
    )
    assert res.status_code == 201, res.text
    saved = res.json()
    assert saved["status"] == "approved" and saved["approved_at"]
    assert saved["comment_source"] == "doctor"
    assert saved["case_number"] == "S26-0001"
    assert {k: saved[k] for k in REPORT} == REPORT

    got = await client.get(f"/reports/{saved['id']}")
    assert got.status_code == 200
    assert got.json() == saved

    listing = (await client.get("/reports")).json()
    assert listing["total"] == 1 and listing["reports"][0]["id"] == saved["id"]


@pytest.mark.asyncio
async def test_same_session_cannot_be_saved_twice(client):
    body = {"session_id": "s2", "report": REPORT, "comment_source": "ai"}
    first = await client.post("/reports", json=body)
    assert first.status_code == 201
    second = await client.post("/reports", json=body)
    assert second.status_code == 409
    assert f"#{first.json()['id']}" in second.json()["detail"]


@pytest.mark.asyncio
async def test_reports_without_session_id_are_independent(client):
    body = {"report": REPORT, "comment_source": "doctor"}
    assert (await client.post("/reports", json=body)).status_code == 201
    assert (await client.post("/reports", json=body)).status_code == 201


@pytest.mark.asyncio
async def test_case_is_reused_by_case_number(client):
    body = {"case_number": "S26-0002", "report": REPORT, "comment_source": "doctor"}
    a = (await client.post("/reports", json=body)).json()
    b = (await client.post("/reports", json=body)).json()
    assert a["case_number"] == b["case_number"] == "S26-0002"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"report": {**REPORT, "comments": "Note."}},  # comment without provenance
        {"report": {k: "  " for k in REPORT}, "comment_source": None},  # empty report
        {"report": REPORT, "comment_source": "someone"},  # unknown source
        {"report": {**REPORT, "diagnosis": "x" * 20_001}, "comment_source": "doctor"},  # too long
    ],
)
async def test_invalid_payloads_are_rejected(client, body):
    res = await client.post("/reports", json=body)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_comment_source_cleared_when_comments_empty_and_fields_trimmed(client):
    res = await client.post(
        "/reports",
        json={"report": {**REPORT, "comments": "   ", "patient": "  Jane  "}, "comment_source": "ai"},
    )
    assert res.status_code == 201
    saved = res.json()
    assert saved["comment_source"] is None
    assert saved["comments"] == "" and saved["patient"] == "Jane"


@pytest.mark.asyncio
async def test_missing_report_returns_404(client):
    assert (await client.get("/reports/999")).status_code == 404
