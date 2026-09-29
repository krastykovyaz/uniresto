import pytest

from orderability_engine.identity import canonical_identity, normalize_contact_email, normalize_phone


@pytest.mark.parametrize(
    "email, expected",
    [
        ("name@uni.lu", "name@uni.lu"),
        ("  Name@Uni.LU ", "name@uni.lu"),
        ("name+shop@uni.lu", "name@uni.lu"),
        ("name@student.uni.lu", "name@student.uni.lu"),
        ("Name+x@student.uni.lu", "name@student.uni.lu"),
        ("someone@gmail.com", "someone@gmail.com"),
        ("someone+tag@gmail.com", "someone@gmail.com"),
        ("not-an-email", "not-an-email"),
        ("", ""),
        (None, ""),
    ],
)
def test_canonical_identity(email, expected):
    assert canonical_identity(email) == expected


def test_different_people_stay_different():
    assert canonical_identity("anna@uni.lu") != canonical_identity("anne@uni.lu")
    assert canonical_identity("a@uni.lu") != canonical_identity("a@gmail.com")


@pytest.mark.parametrize(
    "email", ["Me@Gmail.com", "me+shop@gmail.com", "m.e@gmail.com", "M.E+x@googlemail.com", "me@gmail.com"]
)
def test_gmail_aliases_normalise_to_one_contact_email(email):
    assert normalize_contact_email(email) == "me@gmail.com"


def test_dots_only_matter_outside_gmail():
    assert normalize_contact_email("a.b@example.org") != normalize_contact_email("ab@example.org")


@pytest.mark.parametrize(
    "phone", ["+352 621 123 456", "00352621123456", "621 123 456", "621-123-456", "(621) 123456", " 621123456 "]
)
def test_luxembourg_phone_formats_normalise_to_one_number(phone):
    assert normalize_phone(phone) == "621123456"


def test_a_foreign_number_is_not_folded_onto_a_local_one():
    assert normalize_phone("+33 6 12 34 56 78") == "33612345678"
    assert normalize_phone("+33 6 12 34 56 78") != normalize_phone("612345678")


@pytest.mark.parametrize("bad", ["", None, "abc", "12345", "1234567890123456", "621 123 abc", "621#123456"])
def test_implausible_phone_numbers_are_rejected(bad):
    assert normalize_phone(bad) is None
