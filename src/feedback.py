"""Turns the alignment into a short, ranked list of things to practise."""
from __future__ import annotations
from typing import List
from .alignment.align import AlignedPair

_LABEL = {
    "aspiration_error": "Aspiration (alpaprana / mahaprana)",
    "anunasika_error": "Nasal sounds (anunasika)",
    "dvitva_error": "Doubled consonants (dvitva)",
    "conjunct_error": "Conjuncts (sanyukta)",
    "vowel_length_error": "Vowel length (short / long)",
    "vowel_error": "Wrong vowel",
    "visarga_error": "Visarga (ः)",
    "substitution": "Other sound changes",
    "missing": "Skipped syllables",
    "extra": "Extra syllables",
}
_ADVICE = {
    "aspiration_error": "Feel the puff of air on mahaprana sounds (ख घ छ झ ठ ढ थ ध फ भ); keep alpaprana sounds unaspirated.",
    "anunasika_error": "Match the nasal to the following consonant's place (ङ before क-varga, ञ before च-varga ...).",
    "dvitva_error": "Hold the closure of a doubled consonant slightly longer before release.",
    "conjunct_error": "Slow down on consonant clusters and sound every consonant in them.",
    "vowel_length_error": "Make short vowels clearly short and long vowels clearly long.",
    "vowel_error": "Check the vowel sign against the text; listen to the guru for the exact vowel.",
    "visarga_error": "Finish the syllable with a light breath where the text shows ः.",
    "substitution": "Compare these syllables with the guru's audio and repeat them slowly.",
    "missing": "Re-read the verse; some syllables were skipped.",
    "extra": "Avoid adding sounds that are not in the text.",
}


def practice_points(alignment: List[AlignedPair], limit: int = 5) -> List[dict]:
    buckets = {}
    for p in alignment:
        if p.cost <= 0 or p.tag == "match":
            continue
        b = buckets.setdefault(p.tag, {"count": 0, "weight": 0.0, "examples": []})
        b["count"] += 1
        b["weight"] += p.cost
        if len(b["examples"]) < 3:
            b["examples"].append(f"{p.guru.text if p.guru else '-'} \u2192 {p.learner.text if p.learner else '-'}")
    out = []
    for tag, b in sorted(buckets.items(), key=lambda kv: -kv[1]["weight"])[:limit]:
        out.append({"category": _LABEL.get(tag, tag), "type": tag, "count": b["count"],
                    "examples": b["examples"], "advice": _ADVICE.get(tag, "")})
    return out