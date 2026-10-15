import pytest

from app.api.websocket.voice import _english_only_text


@pytest.mark.parametrize(
    "spoken, expected",
    [
        # medical text must survive untouched
        ("Ménétrier disease of the stomach", "Ménétrier disease of the stomach"),
        ("Sjögren syndrome", "Sjögren syndrome"),
        ("café-au-lait macules", "café-au-lait macules"),
        ("Gleason score 3 + 4 = 7, 5 µm sections", "Gleason score 3 + 4 = 7, 5 µm sections"),
        ("Tumor measures 2.5 × 1.0 cm", "Tumor measures 2.5 × 1.0 cm"),
        ("Angle of 45° noted", "Angle of 45° noted"),
        ("α-SMA positive", "α-SMA positive"),
        # decomposed accents (base letter + combining mark) are kept
        ("Café au lait", "Café au lait"),
        # other scripts are dropped
        ("hello مرحبا 你好 привет", "hello"),
        ("विकृति gross", "gross"),
    ],
)
def test_keeps_latin_greek_and_medical_symbols_drops_other_scripts(spoken, expected):
    assert _english_only_text(spoken) == expected


def test_collapses_whitespace_and_spacing_before_punctuation():
    assert _english_only_text("Specimen  is  a biopsy ,  antrum .") == "Specimen is a biopsy, antrum."
