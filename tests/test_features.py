import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.phonetics.akshara import segment_aksharas
from src.phonetics import features as F


def test_aspiration_pair_devanagari():
    assert F.aspiration_partner("त", "devanagari") == "थ"
    assert F.is_alpaprana("त", "devanagari") and F.is_mahaprana("थ", "devanagari")


def test_aspiration_pair_telugu():
    assert F.aspiration_partner("త", "telugu") == "థ"
    assert F.is_alpaprana("త", "telugu") and F.is_mahaprana("థ", "telugu")


def test_anunasika_detection_devanagari():
    aks = segment_aksharas("गङ्गा")
    feats = [F.extract_features(a) for a in aks]
    assert feats[1].has_nasal_consonant is True  # ङ्गा contains nasal ङ
    assert feats[1].is_anunasika is True


def test_anunasika_detection_telugu():
    # గంగ (Telugu "Ganga") -- akshara with anusvara ం
    aks = segment_aksharas("గంగ")
    feats = [F.extract_features(a) for a in aks]
    assert any(f.has_anusvara for f in feats)
    assert any(f.is_anunasika for f in feats)


def test_geminate_vs_conjunct_devanagari():
    cc = segment_aksharas("च्च")[0]  # geminate
    ch = segment_aksharas("च्छ")[0]  # NOT geminate (different consonants)
    assert F.extract_features(cc).is_geminate is True
    assert F.extract_features(ch).is_geminate is False


def test_geminate_telugu():
    # ద్ద (dda, geminate) vs ద్ధ (ddha, conjunct of ద+ధ, not geminate)
    dd = segment_aksharas("ద్ద")[0]
    ddh = segment_aksharas("ద్ధ")[0]
    assert F.extract_features(dd).is_geminate is True
    assert F.extract_features(ddh).is_geminate is False


if __name__ == "__main__":
    test_aspiration_pair_devanagari()
    test_aspiration_pair_telugu()
    test_anunasika_detection_devanagari()
    test_anunasika_detection_telugu()
    test_geminate_vs_conjunct_devanagari()
    test_geminate_telugu()
    print("test_features.py: all tests passed")
