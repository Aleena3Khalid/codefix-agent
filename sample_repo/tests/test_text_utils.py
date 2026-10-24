from text_utils import slugify, truncate, word_count

def test_slugify():
    assert slugify("  Hello World ") == "hello-world"


def test_word_count_simple():
    assert word_count("one two three") == 3


def test_word_count_extra_spaces():
    assert word_count("one  two   three ") == 3


def test_truncate_short_text_unchanged():
    assert truncate("hi", 10) == "hi"


def test_truncate_long_text():
    assert truncate("abcdefghij", 6) == "abc..."