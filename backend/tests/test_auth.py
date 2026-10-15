import jwt
import pytest

from tests.conftest import TEST_JWT_SECRET, signup


@pytest.mark.asyncio
async def test_signup_returns_token_and_me_works(client):
    headers, body = await signup(client, email="Doc@Example.com")
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    assert body["user"]["email"] == "doc@example.com"  # normalized
    assert "password" not in body["user"] and "password_hash" not in body["user"]

    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["full_name"] == "Dr. House"


@pytest.mark.asyncio
async def test_duplicate_email_is_rejected_case_insensitively(client):
    await signup(client, email="doc@example.com")
    res = await client.post(
        "/auth/signup", json={"email": "DOC@example.com", "full_name": "Other", "password": "another-pass"}
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_login_with_correct_and_wrong_credentials(client):
    await signup(client, email="doc@example.com", password="correct-horse")
    ok = await client.post("/auth/login", json={"email": "doc@example.com", "password": "correct-horse"})
    assert ok.status_code == 200 and ok.json()["access_token"]

    wrong = await client.post("/auth/login", json={"email": "doc@example.com", "password": "wrong-horse"})
    unknown = await client.post("/auth/login", json={"email": "nobody@example.com", "password": "correct-horse"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]  # no account enumeration


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "full_name": "A", "password": "long-enough"},
        {"email": "a@example.com", "full_name": "A", "password": "short"},
        {"email": "a@example.com", "full_name": "   ", "password": "long-enough"},
        {"email": "a@example.com", "full_name": "A", "password": "x" * 73},
    ],
)
async def test_invalid_signup_payloads(client, body):
    assert (await client.post("/auth/signup", json=body)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    [None, "Bearer not-a-token", "Basic abc"],
)
async def test_protected_routes_require_a_valid_token(client, header):
    headers = {"Authorization": header} if header else {}
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
    assert (await client.get("/cases", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_expired_and_foreign_tokens_are_rejected(client):
    import time

    await signup(client)
    expired = jwt.encode({"sub": "1", "exp": int(time.time()) - 10}, TEST_JWT_SECRET, algorithm="HS256")
    forged = jwt.encode({"sub": "1", "exp": int(time.time()) + 600}, "some-other-secret-" + "y" * 32, algorithm="HS256")
    for token in (expired, forged):
        res = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_missing_jwt_secret_is_a_clear_server_error(client, monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    res = await client.post(
        "/auth/signup", json={"email": "a@example.com", "full_name": "A", "password": "long-enough"}
    )
    assert res.status_code == 500
    assert "JWT_SECRET" in res.json()["detail"]
