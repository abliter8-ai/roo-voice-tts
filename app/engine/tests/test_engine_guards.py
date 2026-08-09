#!/usr/bin/env python3
"""Unit tests for the text normalizer and the greedy-derail guard.

    python3 -m unittest discover -s app/engine/tests -v

Pure-Python: no model, no llama-server, no espeak, no numpy needed for the
normalizer half. The engine half imports roo_engine.engine, which imports numpy
only at module scope, so it runs anywhere the engine's own deps are installed.

The normalizer cases below are anchored to MEASURED espeak-ng en-GB behaviour
(recorded in normalize.py's header). Two classes of test matter equally:
  * REPAIRS  — espeak gets it wrong, we must rewrite it.
  * HANDS-OFF — espeak gets it RIGHT, so we must NOT touch it. These are the
    regressions that shipped in the first cut of this feature; each one here is
    a real defect that reached review.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from roo_engine.normalize import _normalize, normalize          # noqa: E402
from roo_engine.engine import (                                  # noqa: E402
    DERAIL_TAIL, DRONE_MIN_KEEP, MAX_CODES_PER_CHUNK,
    drone_onset, is_derailed, trim_drone,
)


class TestNormalizerRepairs(unittest.TestCase):
    """Cases where espeak measurably fails and we must intervene."""

    def test_iso_date(self):
        self.assertEqual(_normalize("On 2024-03-14 we shipped"),
                         "On the 14th of March 2024 we shipped")

    def test_iso_timestamp(self):
        self.assertEqual(_normalize("At 2024-03-14T09:45:00Z we shipped"),
                         "At the 14th of March 2024 at 9 45 we shipped")

    def test_iso_timestamp_offset_tz(self):
        self.assertEqual(_normalize("2024-03-14T09:45+01:00"),
                         "the 14th of March 2024 at 9 45")

    def test_numeric_range(self):
        self.assertEqual(_normalize("The score was 3-2"), "The score was 3 to 2")
        self.assertEqual(_normalize("He said 50-50"), "He said 50 to 50")

    def test_year_range_is_a_range_not_a_serial(self):
        self.assertEqual(_normalize("the 2024-2025 season"),
                         "the 2024 to 2025 season")

    def test_phone_number_is_spelled_digit_by_digit(self):
        self.assertEqual(_normalize("Call 555-1234"), "Call 5 5 5 1 2 3 4")
        self.assertEqual(_normalize("tel 01-234-5678"), "tel 0 1 2 3 4 5 6 7 8")

    def test_alphanumeric_id_code(self):
        self.assertEqual(_normalize("Ticket 8837-XZ"), "Ticket 8 8 3 7 X Z")

    def test_currency_order_and_plural(self):
        self.assertEqual(_normalize("It cost $1,200"), "It cost 1,200 dollars")
        self.assertEqual(_normalize("It cost £5"), "It cost 5 pounds")
        self.assertEqual(_normalize("It cost £1"), "It cost 1 pound")
        self.assertEqual(_normalize("We raised €1.2 million"),
                         "We raised 1.2 million euros")

    def test_quarter(self):
        self.assertEqual(_normalize("Q3 revenue rose"), "quarter 3 revenue rose")

    def test_clock_times_are_unglued(self):
        # Justified by the LIBRARY phonemizer, not the espeak CLI: with
        # preserve_punctuation=True, "09:45" -> `zˈiəɹəʊ nˈaɪn:fˈɔːti fˈaɪv`,
        # i.e. the hour reads "zero nine" and a bare ':' is glued into the
        # phoneme stream. Splitting the pair fixes both.
        self.assertEqual(_normalize("Meet at 09:45"), "Meet at 9 45")
        self.assertEqual(_normalize("Meet at 13:45"), "Meet at 13 45")
        self.assertEqual(_normalize("Meet at 9:05"), "Meet at 9 05")
        self.assertEqual(_normalize("Meet at 09:00"), "Meet at 9 o'clock")
        self.assertEqual(_normalize("Meet at 09:45:30"), "Meet at 9 45")

    def test_non_time_digit_colon_pairs_are_unglued(self):
        self.assertEqual(_normalize("ratio 16:9 here"), "ratio 16 9 here")
        self.assertEqual(_normalize("at 25:00"), "at 25 00")

    def test_prose_colons_are_left_alone(self):
        # Prose punctuation IS the trained form (preserve_punctuation=True) —
        # only the glued digit:digit form is out of distribution.
        for s in ["Here's the thing: we left early", "One thing; another thing"]:
            self.assertEqual(_normalize(s), s, s)

    def test_abbreviations_espeak_mangles(self):
        for src, want in [("Prof. Lee", "Professor Lee"),
                          ("Ms. Kim", "Miz Kim"),
                          ("Mt. Doom", "Mount Doom"),
                          ("A vs. B", "A versus B"),
                          ("approx. 5", "approximately 5"),
                          ("No. 7", "number 7"),
                          ("Acme Inc. is here", "Acme Incorporated is here"),
                          ("John Jr. and I", "John Junior and I"),
                          ("Sgt. Pepper", "Sergeant Pepper"),
                          ("see Fig. 3", "see Figure 3"),
                          ("Jan. 5", "January 5")]:
            self.assertEqual(_normalize(src), want, src)

    def test_sentence_ending_abbreviation_keeps_its_full_stop(self):
        # "...Acme Inc. Q3 rose..." is two sentences. Dropping the period here
        # welds them together and loses the pause.
        self.assertEqual(_normalize("of Acme Inc. Q3 rose"),
                         "of Acme Incorporated. quarter 3 rose")
        self.assertEqual(_normalize("Acme Ltd. Then we left"),
                         "Acme Limited. Then we left")
        self.assertEqual(_normalize("this, that, etc."), "this, that, et cetera.")

    def test_mid_sentence_abbreviation_drops_its_full_stop(self):
        self.assertEqual(_normalize("Acme Ltd. is great"), "Acme Limited is great")
        self.assertEqual(_normalize("John Jr. and John Sr."),
                         "John Junior and John Senior.")
        self.assertEqual(_normalize("a Ph.D. holder"), "a P H D holder")

    def test_currency_does_not_swallow_a_following_comma(self):
        self.assertEqual(_normalize("It cost $1,200,000, then more"),
                         "It cost 1,200,000 dollars, then more")

    def test_safe_abbreviations_expanded_for_chunker_safety(self):
        # espeak reads these correctly; we expand them anyway so the trailing
        # period cannot act as a sentence end and hand the model a fragment.
        self.assertEqual(_normalize("Dr. Smith"), "Doctor Smith")
        self.assertEqual(_normalize("e.g. this"), "for example this")
        self.assertNotIn(".", _normalize("Dr. Smith met Mr. Jones"))


class TestNormalizerHandsOff(unittest.TestCase):
    """espeak already reads these correctly. Rewriting them WAS the regression —
    each assertion below is a defect caught in review of the first cut."""

    def test_plain_prose_is_untouched(self):
        prose = ("Right, so here's where we are. The forecast looks grand, "
                 "which means the cliff walk is back on. Bring the good jacket.")
        self.assertEqual(_normalize(prose), prose)

    def test_integers_of_any_size_untouched(self):
        for s in ["He owes 7 pounds", "Exactly 1200 units", "Some 1,200 units",
                  "Order 1234567890123 shipped",
                  "The number is 12345678901234567890."]:
            self.assertEqual(_normalize(s), s, s)

    def test_decimals_and_versions_untouched(self):
        self.assertEqual(_normalize("It is 1.2 metres"), "It is 1.2 metres")
        self.assertEqual(_normalize("Version 2.0.0 shipped"),
                         "Version 2.0.0 shipped")

    def test_ordinals_untouched(self):
        self.assertEqual(_normalize("She came 1st, he came 22nd"),
                         "She came 1st, he came 22nd")

    def test_percent_and_symbols_untouched(self):
        for s in ["Up 27.4%", "R&D spending", "A/B testing", "meet @ noon",
                  "3 + 4 = 7", "item #5"]:
            self.assertEqual(_normalize(s), s, s)

    def test_letter_first_hyphenated_names_untouched(self):
        # espeak: "covid nineteen", "GPT four", "Claude three". Spelling these
        # out letter-by-letter is strictly worse.
        for s in ["COVID-19 cases", "GPT-4 wins", "Claude-3 beat the RTX-5060",
                  "a well-known state-of-the-art fact"]:
            self.assertEqual(_normalize(s), s, s)


class TestNormalizerRobustness(unittest.TestCase):
    """It is a cosmetic front-end. It must never be able to break generation."""

    def test_invalid_dates_do_not_crash_and_are_left_alone(self):
        for s in ["2024-13-01", "2024-00-10", "2024-12-99", "9999-99-99"]:
            out = normalize(s)
            self.assertIsInstance(out, str)
            self.assertTrue(out.strip())

    def test_huge_numbers_do_not_crash(self):
        self.assertTrue(normalize("id " + "9" * 40).strip())

    def test_normalize_never_raises(self):
        for s in ["", "   ", "$", "-", "---", "Q", "2024-", ":", "£-",
                  "\x00\x01", "1-", "-1", "a" * 5000, "€", "T09:45Z"]:
            try:
                out = normalize(s)
            except Exception as e:                       # pragma: no cover
                self.fail(f"normalize({s!r}) raised {e!r}")
            self.assertIsInstance(out, str)

    def test_never_returns_empty_for_speakable_input(self):
        for s in ["hello", "$5", "Q3", "2024-03-14"]:
            self.assertTrue(normalize(s).strip(), s)

    def test_falls_back_to_raw_text_on_internal_error(self):
        import roo_engine.normalize as N
        original = N._normalize
        N._normalize = lambda t: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.assertEqual(N.normalize("hello there"), "hello there")
        finally:
            N._normalize = original


class TestIsDerailed(unittest.TestCase):
    """Both conditions must hold: cut off by the length cap AND a collapsed tail."""

    def test_natural_stop_is_never_a_derail(self):
        self.assertFalse(is_derailed(list(range(500)), capped=False))
        # even a collapsed tail is fine if the model chose to stop
        self.assertFalse(is_derailed(list(range(300)) + [7] * 200, capped=False))

    def test_capped_but_diverse_is_not_a_derail(self):
        self.assertFalse(is_derailed(list(range(MAX_CODES_PER_CHUNK)), capped=True))

    def test_capped_and_collapsed_is_a_derail(self):
        self.assertTrue(is_derailed(list(range(824)) + [7] * 200, capped=True))

    def test_threshold_boundary(self):
        base = list(range(824))
        self.assertTrue(is_derailed(base + (list(range(19)) * 11)[:200], capped=True))
        self.assertFalse(is_derailed(base + (list(range(20)) * 10)[:200], capped=True))

    def test_uses_stop_reason_not_length(self):
        # The bug this replaces: complete() drops non-speech tokens, so a capped
        # generation can return 1023 codes. A length-based check misses it.
        codes = list(range(823)) + [7] * 200
        self.assertEqual(len(codes), MAX_CODES_PER_CHUNK - 1)
        self.assertTrue(is_derailed(codes, capped=True))

    def test_too_short_to_judge(self):
        self.assertFalse(is_derailed([7] * (DERAIL_TAIL - 1), capped=True))


class TestTrimDrone(unittest.TestCase):

    def test_cuts_at_the_true_onset_keeping_all_speech(self):
        codes = list(range(800)) + [7] * 224
        self.assertEqual(drone_onset(codes), 800)
        self.assertEqual(trim_drone(codes), list(range(800)))

    def test_cyclic_drone_onset(self):
        # a real drone cycles through a few codes rather than holding one
        codes = list(range(700)) + [3, 4, 5] * 108
        self.assertEqual(drone_onset(codes), 700)
        self.assertEqual(len(trim_drone(codes)), 700)

    def test_clean_codes_are_untouched(self):
        codes = list(range(1024))
        self.assertIsNone(drone_onset(codes))
        self.assertEqual(trim_drone(codes), codes)

    def test_drone_from_the_start_leaves_nothing_worth_keeping(self):
        # must NOT return the full 1024-code tone: that is the 20 s screech
        kept = trim_drone([7] * 1024)
        self.assertLess(len(kept), DRONE_MIN_KEEP)

    def test_early_derail_is_below_the_keep_threshold(self):
        kept = trim_drone(list(range(5)) + [7] * 1019)
        self.assertLess(len(kept), DRONE_MIN_KEEP)

    def test_short_input_is_safe(self):
        for n in (0, 1, 10, 99):
            self.assertEqual(trim_drone([1] * n), [1] * n)


class _StubLlama:
    """Returns a scripted (codes, capped) per call, so the guard's decision logic
    can be tested without a model."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def complete(self, prompt):
        self.calls.append(prompt)
        return self.script.pop(0) if self.script else (list(range(300)), False)


class _StubDecoder:
    def decode(self, codes):
        import numpy as np
        return np.zeros(len(codes), dtype=np.float32)


def _engine(script):
    from roo_engine.engine import Engine
    eng = Engine(_StubLlama(script), _StubDecoder(), lambda t: t)
    return eng


CLEAN = (list(range(400)), False)
TRUNCATED = (list(range(MAX_CODES_PER_CHUNK)), True)          # capped, diverse tail
DERAILED = (list(range(824)) + [7] * 200, True)               # capped, collapsed tail
TOTAL_DRONE = ([7] * MAX_CODES_PER_CHUNK, True)

LONG = ("The quarterly figures came in ahead of forecast across every region. "
        "The underlying cost base has not moved at all this year. "
        "That is the number I keep coming back to whenever I look at it.")


class TestGuardDecisions(unittest.TestCase):

    def test_healthy_chunk_ships_untouched(self):
        eng = _engine([CLEAN])
        pieces = eng._audio_for("hello there")
        self.assertEqual(len(pieces), 1)
        self.assertEqual(len(eng.llama.calls), 1)
        self.assertEqual(eng.guard_events, [])

    def test_truncated_chunk_is_resplit_and_regenerated(self):
        # The pre-existing bug: a capped-but-healthy chunk was shipped with its
        # tail silently missing. It must be re-split so each piece gets its own
        # code budget.
        eng = _engine([TRUNCATED, CLEAN, CLEAN, CLEAN])
        eng._audio_for(LONG)
        self.assertGreater(len(eng.llama.calls), 1, "should have regenerated")
        self.assertEqual(eng.guard_events[0]["action"], "resplit")
        self.assertEqual(eng.guard_events[0]["reason"], "truncated")

    def test_derailed_chunk_is_resplit(self):
        eng = _engine([DERAILED, CLEAN, CLEAN, CLEAN])
        eng._audio_for(LONG)
        self.assertEqual(eng.guard_events[0]["action"], "resplit")
        self.assertEqual(eng.guard_events[0]["reason"], "derail")

    def test_unsplittable_derail_is_trimmed_not_shipped_as_tone(self):
        eng = _engine([DERAILED])
        eng._audio_for("short")          # no sentence structure to re-split
        self.assertEqual(eng.guard_events[-1]["action"], "trimmed")
        self.assertEqual(eng.guard_events[-1]["kept"], 824)

    def test_total_drone_becomes_silence_not_twenty_seconds_of_tone(self):
        from roo_engine.engine import SAMPLE_RATE, SENTENCE_JOIN_SILENCE_S
        eng = _engine([TOTAL_DRONE])
        pieces = eng._audio_for("short")
        self.assertEqual(eng.guard_events[-1]["action"], "dropped")
        # exactly the join gap: silence, never a decoded tone
        self.assertEqual(len(pieces[0]), int(SENTENCE_JOIN_SILENCE_S * SAMPLE_RATE))
        self.assertTrue((pieces[0] == 0).all())

    def test_unsplittable_truncation_keeps_the_real_speech(self):
        eng = _engine([TRUNCATED])
        pieces = eng._audio_for("short")
        self.assertEqual(eng.guard_events[-1]["action"], "truncated")
        self.assertEqual(len(pieces[0]), MAX_CODES_PER_CHUNK)

    def test_recursion_is_bounded(self):
        from roo_engine.engine import RESPLIT_CHARS
        eng = _engine([TRUNCATED] * 200)
        eng._audio_for(LONG)
        self.assertLess(len(eng.llama.calls), 60)
        self.assertLessEqual(max(e.get("depth", 0) for e in eng.guard_events
                                 if e["action"] == "resplit") if eng.guard_events else 0,
                             len(RESPLIT_CHARS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
