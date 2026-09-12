import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.phonetics.akshara import segment_aksharas
from src.alignment.align import align_aksharas


def tags(guru_text, learner_text):
    g = segment_aksharas(guru_text)
    l = segment_aksharas(learner_text)
    return [p.tag for p in align_aksharas(g, l)]


def test_alpaprana_mahaprana_confusion():
    t = tags("तट", "थट")
    assert "aspiration_error" in t


def test_sanyukta_confusion():
    t = tags("साद्व्यम्", "साध्व्यम्")
    assert "conjunct_error" in t or "aspiration_error" in t


def test_dvitva_confusion():
    t = tags("बुद्धः", "बुद्दः")
    assert "dvitva_error" in t


def test_anunasika_confusion():
    t1 = tags("गङ्गा", "गम्गा")
    t2 = tags("गङ्गा", "गन्गा")
    assert "anunasika_error" in t1
    assert "anunasika_error" in t2


def test_perfect_match():
    t = tags("गङ्गा", "गङ्गा")
    assert all(x == "match" for x in t)


def test_telugu_aspiration_confusion():
    t = tags("తట", "థట")
    assert "aspiration_error" in t


def test_telugu_geminate_confusion():
    t = tags("బుద్దః", "బుద్ధః")
    assert "dvitva_error" in t


def test_telugu_perfect_match():
    line = "జననుత కృష్ణద్వైపాయన"
    t = tags(line, line)
    assert all(x == "match" for x in t)


def test_newline_vs_space_not_an_error():
    guru = "राम च\nकृष्ण च"
    learner = "राम च कृष्ण च"
    t = tags(guru, learner)
    assert all(x == "match" for x in t), t


if __name__ == "__main__":
    test_alpaprana_mahaprana_confusion()
    test_sanyukta_confusion()
    test_dvitva_confusion()
    test_anunasika_confusion()
    test_perfect_match()
    test_telugu_aspiration_confusion()
    test_telugu_geminate_confusion()
    test_telugu_perfect_match()
    test_newline_vs_space_not_an_error()
    print("test_alignment.py: all tests passed")
