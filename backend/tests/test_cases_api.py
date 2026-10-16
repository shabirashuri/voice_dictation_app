import re

import pytest

from tests.conftest import create_case, signup

REPORT = {
    "patient": "John Doe",
    "specimen": "Gastric biopsy",
    "gross_description": "",
    "microscopic_description": "Chronic inactive gastritis.",
    "diagnosis": "Chronic inactive gastritis.",
    "comments": "Recommend clinical correlation.",
}


@pytest.mark.asyncio
async def test_create_and_list_cases_for_the_signed_in_doctor(client):
    headers, _ = await signup(client)
    first = await create_case(client, headers, "  John Doe  ", "MRN-1")
    second = await create_case(client, headers, "Jane Roe")

    assert re.fullmatch(r"C-\d{4}-\d{5}", first["case_number"])
    assert first["case_number"] != second["case_number"]
    assert first["patient_name"] == "John Doe" and first["patient_mrn"] == "MRN-1"
    assert first["status"] == "open" and first["report_id"] is None

    listing = (await client.get("/cases", headers=headers)).json()
    assert listing["total"] == 2
    assert [c["id"] for c in listing["cases"]] == [second["id"], first["id"]]  # newest first


@pytest.mark.asyncio
async def test_doctors_only_see_their_own_cases(client):
    alice, _ = await signup(client, email="alice@example.com")
    bob, _ = await signup(client, email="bob@example.com")
    case = await create_case(client, alice, "Alice's patient")

    assert (await client.get("/cases", headers=bob)).json()["total"] == 0
    assert (await client.get(f"/cases/{case['id']}", headers=bob)).status_code == 404
    assert (await client.get(f"/cases/{case['id']}/report", headers=bob)).status_code == 404
    res = await client.post(
        f"/cases/{case['id']}/report", json={"report": REPORT, "comment_source": "doctor"}, headers=bob
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_report_is_saved_to_its_case_and_case_becomes_reported(client):
    headers, _ = await signup(client)
    case = await create_case(client, headers)
    other = await create_case(client, headers, "Jane Roe")

    res = await client.post(
        f"/cases/{case['id']}/report",
        json={"session_id": "s1", "report": REPORT, "comment_source": "doctor"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    saved = res.json()
    assert saved["case_id"] == case["id"] and saved["case_number"] == case["case_number"]
    assert saved["status"] == "approved" and saved["approved_at"]
    assert {k: saved[k] for k in REPORT} == REPORT

    detail = (await client.get(f"/cases/{case['id']}", headers=headers)).json()
    assert detail["status"] == "reported" and detail["report"]["id"] == saved["id"]
    assert (await client.get(f"/cases/{case['id']}/report", headers=headers)).json() == saved

    # the other case is untouched
    other_detail = (await client.get(f"/cases/{other['id']}", headers=headers)).json()
    assert other_detail["status"] == "open" and other_detail["report"] is None
    assert (await client.get(f"/cases/{other['id']}/report", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_a_case_has_only_one_report(client):
    headers, _ = await signup(client)
    case = await create_case(client, headers)
    body = {"report": REPORT, "comment_source": "doctor"}
    first = await client.post(f"/cases/{case['id']}/report", json=body, headers=headers)
    second = await client.post(f"/cases/{case['id']}/report", json=body, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 409
    assert "already has an approved report" in second.json()["detail"]


@pytest.mark.asyncio
async def test_one_dictation_session_cannot_be_saved_to_two_cases(client):
    headers, _ = await signup(client)
    a = await create_case(client, headers)
    b = await create_case(client, headers, "Jane Roe")
    body = {"session_id": "same", "report": REPORT, "comment_source": "doctor"}
    assert (await client.post(f"/cases/{a['id']}/report", json=body, headers=headers)).status_code == 201
    res = await client.post(f"/cases/{b['id']}/report", json=body, headers=headers)
    assert res.status_code == 409 and "already saved" in res.json()["detail"]


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
async def test_invalid_reports_are_rejected(client, body):
    headers, _ = await signup(client)
    case = await create_case(client, headers)
    assert (await client.post(f"/cases/{case['id']}/report", json=body, headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_comment_source_cleared_when_comments_empty_and_fields_trimmed(client):
    headers, _ = await signup(client)
    case = await create_case(client, headers)
    res = await client.post(
        f"/cases/{case['id']}/report",
        json={"report": {**REPORT, "comments": "   ", "patient": "  Jane  "}, "comment_source": "ai"},
        headers=headers,
    )
    saved = res.json()
    assert saved["comment_source"] is None
    assert saved["comments"] == "" and saved["patient"] == "Jane"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"patient_name": ""}, {"patient_name": "   "}, {}, {"patient_name": "x" * 201}])
async def test_case_requires_a_patient_name(client, body):
    headers, _ = await signup(client)
    assert (await client.post("/cases", json=body, headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_missing_case_is_404(client):
    headers, _ = await signup(client)
    assert (await client.get("/cases/999", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_transcript_is_stored_with_the_report(client):
    headers, _ = await signup(client)
    case = await create_case(client, headers)
    lines = [{"text": "Specimen is a gastric biopsy.", "status": "applied"}, {"text": "uh", "status": "ignored"}]

    res = await client.post(
        f"/cases/{case['id']}/report",
        json={"report": REPORT, "comment_source": "doctor", "transcript": lines},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["transcript"] == lines
    assert (await client.get(f"/cases/{case['id']}/report", headers=headers)).json()["transcript"] == lines


@pytest.mark.asyncio
async def test_transcript_is_optional_and_validated(client):
    headers, _ = await signup(client)
    case = await create_case(client, headers)
    bad = await client.post(
        f"/cases/{case['id']}/report",
        json={"report": REPORT, "comment_source": "doctor", "transcript": [{"text": "x", "status": "bogus"}]},
        headers=headers,
    )
    assert bad.status_code == 422
    ok = await client.post(
        f"/cases/{case['id']}/report", json={"report": REPORT, "comment_source": "doctor"}, headers=headers
    )
    assert ok.status_code == 201 and ok.json()["transcript"] is None
