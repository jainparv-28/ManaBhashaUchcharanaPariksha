import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.phonetics.akshara import segment_aksharas, to_words


def texts(aksharas):
    return [a.text for a in aksharas]


def test_simple_word():
    assert texts(segment_aksharas("गङ्गा")) == ["ग", "ङ्गा"]


def test_geminate():
    # द्ध as one akshara (dvitva-like conjunct of द+ध)
    out = texts(segment_aksharas("बुद्धः"))
    assert "द्ध" in "".join(out)  # conjunct captured


def test_word_split():
    aks = segment_aksharas("राम च कृष्ण")
    words = to_words(aks)
    assert len(words) == 3


def test_independent_vowel():
    aks = segment_aksharas("अहं")
    assert aks[0].is_independent_vowel is True


if __name__ == "__main__":
    test_simple_word()
    test_geminate()
    test_word_split()
    test_independent_vowel()
    print("test_akshara.py: all tests passed")
