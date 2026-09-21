import pytest

from maimai_updata.core.parser import InvalidCode, parse_codes


@pytest.mark.parametrize("value", ["", " \n\t "])
def test_empty(value):
    assert parse_codes(value) == []


@pytest.mark.parametrize("value", ["SGWCMAIDx", "SGWCMAID" + "A" * 100,
                                      "SGWCMAIDfuture-format_+/-="])
def test_candidates_do_not_invent_business_length_or_alphabet(value):
    assert parse_codes(" \n" + value + "\t") == [value]


def test_deduplicate_and_preserve_multiple_accounts_for_caller_rejection():
    assert parse_codes("SGWCMAIDx SGWCMAIDy SGWCMAIDx") == ["SGWCMAIDx", "SGWCMAIDy"]


@pytest.mark.parametrize("value", ["SGWCMAID", "sgwcmaidxxxx", "xxxx", "https://example.test/SGWCMAIDx",
                                      "上传成绩 SGWCMAIDx", "SGWCMAIDx hello", "SGWCMAIDx\x00",
                                      "SGWCMAIDx\u202e", None, "SGWCMAID\ud800"])
def test_invalid_or_mixed_content_is_not_silently_extracted(value):
    with pytest.raises(InvalidCode) as caught:
        parse_codes(value)
    assert "SGWCMAIDx" not in str(caught.value)


def test_input_budget():
    with pytest.raises(InvalidCode):
        parse_codes("SGWCMAID" + "x" * 4096)
