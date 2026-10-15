import pytest
from pydantic import ValidationError

from app.graph.state import FieldUpdate, LangGraphState, Report


def _u(section, content, op="append"):
    return FieldUpdate(target_section=section, operation=op, content=content)


def test_append_to_empty_field_sets_content():
    report = Report()
    assert report.apply_update(_u("diagnosis", "Chronic gastritis")) is True
    assert report.diagnosis == "Chronic gastritis"


@pytest.mark.parametrize(
    "current, added, expected",
    [
        ("Chronic gastritis", "No H. pylori", "Chronic gastritis. No H. pylori"),
        ("Chronic gastritis.", "No H. pylori", "Chronic gastritis. No H. pylori"),
        ("Is it benign?", "Yes", "Is it benign? Yes"),
    ],
)
def test_append_separates_sentences(current, added, expected):
    report = Report(microscopic_description=current)
    assert report.apply_update(_u("microscopic_description", added)) is True
    assert report.microscopic_description == expected


def test_append_skips_content_already_present():
    report = Report(specimen="Gastric biopsy. Two fragments")
    assert report.apply_update(_u("specimen", "Two fragments")) is False
    assert report.specimen == "Gastric biopsy. Two fragments"


def test_replace_overwrites_and_reports_no_change_when_equal():
    report = Report(specimen="Gastric biopsy")
    assert report.apply_update(_u("specimen", "Kidney biopsy", "replace")) is True
    assert report.specimen == "Kidney biopsy"
    assert report.apply_update(_u("specimen", "Kidney biopsy", "replace")) is False


def test_empty_content_is_a_no_op():
    report = Report(diagnosis="Gastritis")
    assert report.apply_update(_u("diagnosis", "   ")) is False
    assert report.apply_update(_u("diagnosis", "", "replace")) is False
    assert report.diagnosis == "Gastritis"


def test_update_only_touches_its_target_field():
    report = Report(patient="John Doe", diagnosis="Gastritis")
    report.apply_update(_u("specimen", "Gastric biopsy"))
    assert (report.patient, report.diagnosis) == ("John Doe", "Gastritis")


def test_field_update_strips_content_and_defaults_to_append():
    update = FieldUpdate(target_section="patient", content="  John Doe  ")
    assert update.content == "John Doe"
    assert update.operation == "append"


@pytest.mark.parametrize(
    "raw",
    [
        {"target_section": "not_a_field", "content": "x"},
        {"target_section": "patient", "operation": "delete", "content": "x"},
        {"target_section": "patient"},
    ],
)
def test_field_update_rejects_invalid_input(raw):
    with pytest.raises(ValidationError):
        FieldUpdate(**raw)


def test_apply_updates_records_only_changed_fields():
    state = LangGraphState(report=Report(specimen="Gastric biopsy"))
    state.apply_updates([_u("specimen", "Gastric biopsy"), _u("diagnosis", "Gastritis")])
    assert [u.target_section for u in state.updated_fields] == ["diagnosis"]
