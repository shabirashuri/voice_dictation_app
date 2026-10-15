import pytest

from app.graph.grounding import check_dropped_negation, check_grounding


@pytest.mark.parametrize(
    "source, content",
    [
        ("The margins are clear, 2 mm from the edge.", "Margins are clear; 2 mm from the edge"),
        ("Two tan-white fragments.", "2 tan-white fragments"),  # number word vs digit
        ("It consists of 2 fragments.", "two fragments"),
        ("5 micron sections.", "5 µm sections"),  # micron is µm
        ("Sections at 45 degrees.", "45° angle"),
        ("Gleason three plus four equals seven.", "Gleason 3 + 4 = 7"),
        ("Twenty five millimetres.", "25 mm"),
        ("Two point five centimetres.", "2.5 cm"),
        ("Left kidney biopsy.", "left kidney biopsy"),
        ("Margins are negative for tumour.", "No tumour at margins"),  # negative ≡ no
        ("Chronic gastritis.", "Chronic gastritis."),
    ],
)
def test_faithful_content_passes(source, content):
    assert check_grounding(source, content) == []


@pytest.mark.parametrize(
    "source, content, expected_fragment",
    [
        ("Tumour is present in the sample.", "Tumour measures 2.5 cm.", "'cm' is not in the dictation"),
        ("The lesion measures 2.5 millimetres.", "2.5 cm", "'cm' is not in the dictation"),
        ("The lesion measures 2.5.", "2.5 cm", "'cm' is not in the dictation"),
        ("Gastric biopsy.", "Biopsy measures 7 mm.", "'mm' is not in the dictation"),
        ("The mass is 3 cm.", "Mass is 4 cm", "measurement with unit 'cm' is not in the dictation"),
        ("Left kidney biopsy.", "Right kidney biopsy", "'right' is not in the dictation"),
        ("Atypia present.", "No atypia", "a negation is not in the dictation"),
        ("Gastric biopsy.", "Gastric biopsy. No H. pylori.", "a negation is not in the dictation"),
    ],
)
def test_invented_or_changed_content_is_flagged(source, content, expected_fragment):
    problems = check_grounding(source, content, label="gross_description")
    assert problems, "expected a problem"
    assert any(expected_fragment in p for p in problems)
    assert all(p.startswith("gross_description:") for p in problems)


def test_problem_messages_do_not_echo_dictated_text():
    problems = check_grounding("Gastric biopsy.", "Secret phrase with 9 mm lesion")
    assert problems
    assert "Secret phrase" not in " ".join(problems)


def test_dropped_negation_is_flagged_when_no_update_keeps_it():
    assert check_dropped_negation("No atypia. Margins 2 mm.", ["Margins 2 mm"]) == [
        "a negation in the dictation was not captured"
    ]


def test_dropped_negation_is_not_flagged_when_one_update_keeps_it():
    assert check_dropped_negation("No atypia. Margins 2 mm.", ["No atypia", "Margins 2 mm"]) == []


def test_no_negation_in_dictation_means_nothing_to_drop():
    assert check_dropped_negation("Margins 2 mm.", ["Margins 2 mm"]) == []
