import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.phonetics.akshara import segment_aksharas
from src.alignment.align import align_aksharas


def tags(guru_text, learner_text):
    g = segment_aksharas(guru_text)
    l = segment_aksharas(learner_text)
    return [p.tag for p in align_aksharas(g, l)]


def test_alpaprana_mahaprana_confusion():
    # guru's example: त versus थ
    t = tags("तट", "थट")
    assert "aspiration_error" in t


def test_sanyukta_confusion():
    # guru's example: द्व्य being pronounced as ध्व्य
    t = tags("साद्व्यम्", "साध्व्यम्")
    assert "conjunct_error" in t or "aspiration_error" in t  # single-consonant-swap inside conjunct


def test_dvitva_confusion():
    # guru's example: द्ध being pronounced as द्द
    t = tags("बुद्धः", "बुद्दः")
    assert "dvitva_error" in t


def test_anunasika_confusion():
    # guru's flagship example: गङ्गा -> गम्गा / गन्गा
    t1 = tags("गङ्गा", "गम्गा")
    t2 = tags("गङ्गा", "गन्गा")
    assert "anunasika_error" in t1
    assert "anunasika_error" in t2


def test_perfect_match():
    t = tags("गङ्गा", "गङ्गा")
    assert all(x == "match" for x in t)


def test_telugu_aspiration_confusion():
    # త (ta, alpaprana) vs థ (tha, mahaprana) -- Telugu counterpart of त/थ
    t = tags("తట", "థట")
    assert "aspiration_error" in t


def test_telugu_geminate_confusion():
    # ద్ద (dda) vs ద్ధ (ddha) -- Telugu counterpart of guru's द्द/द्ध example
    t = tags("బుద్దః", "బుద్ధః")
    assert "dvitva_error" in t


def test_telugu_perfect_match():
    # opening line of Padyam 1
    line = "జననుత కృష్ణద్వైపాయన"
    t = tags(line, line)
    assert all(x == "match" for x in t)


if __name__ == "__main__":
    test_alpaprana_mahaprana_confusion()
    test_sanyukta_confusion()
    test_dvitva_confusion()
    test_anunasika_confusion()
    test_perfect_match()
    test_telugu_aspiration_confusion()
    test_telugu_geminate_confusion()
    test_telugu_perfect_match()
    print("test_alignment.py: all tests passed")
