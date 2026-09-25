import unittest
from datetime import date, datetime

from scorer import calculate, _score_tide
from main import build_day_block


def score(height, wind=2.6):
    return calculate(height, 7, 7, wind, 60, 60, 0, date(2026, 9, 25))


def record(hour, height):
    return dict(datetime=datetime(2026, 9, 25, hour), wave_height=height,
                swell_period=7, wave_period=7, wind_speed=2.6,
                wind_direction=60, cloud_cover=60, precipitation=0,
                temperature=22, weather_desc="晴れ〜曇り")


class SurfScoringTests(unittest.TestCase):
    def test_crowding_does_not_affect_total_or_decision(self):
        results = [calculate(0.7, 7, 7, 2, 0, 0, 0, day)
                   for day in (date(2026, 9, 25), date(2026, 9, 26),
                               date(2026, 9, 27), date(2026, 9, 23))]
        self.assertEqual({s.total for s in results}, {73})
        self.assertEqual({s.decision for s in results}, {"◎ 行くべき"})
        self.assertEqual({s.crowd_score for s in results}, {20, 100})

    def test_weights_and_weather_does_not_affect_total(self):
        # 波高45×0.4 + 風100×0.3 + 周期100×0.2 + 潮暫定50×0.1 = 73
        s = calculate(0.7, 7, 7, 2, 0, 90, 0, date(2026, 9, 25))
        self.assertEqual(s.wave_condition_score, 73)
        self.assertEqual(s.weather_score, 60)
        self.assertEqual(s.total, 73)
        rainy = calculate(0.7, 7, 7, 2, 0, 100, 5, date(2026, 9, 25))
        self.assertEqual(rainy.total, s.total)

    def test_tide_preference_and_unknown(self):
        tides = {"highs": [(datetime(2026, 9, 25, 4), 1.5),
                            (datetime(2026, 9, 25, 16), 1.6)],
                 "lows": [(datetime(2026, 9, 25, 10), 0.2)]}
        high = _score_tide(datetime(2026, 9, 25, 4), 0.5, tides)[0]
        low = _score_tide(datetime(2026, 9, 25, 10), 0.5, tides)[0]
        ebb = _score_tide(datetime(2026, 9, 25, 7), 0.5, tides)[0]
        flood = _score_tide(datetime(2026, 9, 25, 13), 0.5, tides)[0]
        self.assertGreater(low, high)
        self.assertGreater(ebb, flood)
        self.assertEqual(_score_tide(datetime(2026, 9, 25, 7), 0.7, tides)[0], 100)
        self.assertEqual(_score_tide(datetime(2026, 9, 25, 1), 0.5, tides)[0], 50)
        self.assertIn("未判定", _score_tide(None, 0.5, None)[1])
        block = build_day_block("2026-09-25", [record(8, 0.5), record(9, 0.5)],
                                date(2026, 9, 25), tide_info=tides)
        self.assertIn("下げ潮", block)
        self.assertIn("潮の評価:", block)

    def test_tide_weight_and_small_wave_cap(self):
        tides = {"highs": [(datetime(2026, 9, 25, 4), 1.5)],
                 "lows": [(datetime(2026, 9, 25, 10), 0.2)]}
        s = calculate(0.5, 7, 7, 2, 0, at=datetime(2026, 9, 25, 10), tides=tides)
        self.assertEqual(s.tide_score, 90)
        self.assertEqual(s.total, 99)
        small = calculate(0.3, 7, 7, 2, 0, at=datetime(2026, 9, 25, 10), tides=tides)
        self.assertLessEqual(small.total, 39)

    def test_medium_waves_can_be_recommended_in_good_conditions(self):
        for height in (0.6, 0.6001, 0.7, 0.8999):
            with self.subTest(height=height):
                s = calculate(height, 7, 7, 2, 0, 0, 0, date(2026, 9, 26))
                self.assertEqual(s.decision, "◎ 行くべき")

    def test_reported_small_waves_are_not_recommended(self):
        s = score(0.3)
        self.assertLessEqual(s.total, 39)
        self.assertEqual(s.decision, "✕ 見送り推奨")
        self.assertFalse(s.crowd_caution)
        self.assertIn("ショアブレイク", s.risk_note)
        self.assertNotIn("理想", s.wave_label)

    def test_low_wave_boundaries(self):
        for height, cap in [(0, 39), (0.2, 39), (0.35, 39),
                            (0.3501, 54), (0.45, 54)]:
            with self.subTest(height=height):
                self.assertLessEqual(score(height).total, cap)
                self.assertNotEqual(score(height).decision, "◎ 行くべき")

    def test_good_candidate_and_out_of_range_conditions(self):
        self.assertEqual(score(0.5).decision, "◎ 行くべき")
        self.assertLessEqual(score(0.9).total, 39)
        self.assertLessEqual(score(0.5, wind=5).total, 39)

    def test_two_hour_window_does_not_hide_bad_hour(self):
        block = build_day_block("2026-09-25", [record(8, 0.5), record(9, 0.3)],
                                date(2026, 9, 25))
        self.assertIn("見送り推奨", block)
        self.assertIn("09:00の予報", block)
        self.assertIn("0.30m", block)
        self.assertNotIn("予報上の候補", block)

    def test_better_window_needs_two_good_hours(self):
        records = [record(7, 0.5), record(8, 0.3), record(9, 0.3)]
        block = build_day_block("2026-09-25", records, date(2026, 9, 25))
        self.assertNotIn("予報上の候補", block)
        records += [record(10, 0.5), record(11, 0.5)]
        block = build_day_block("2026-09-25", records, date(2026, 9, 25))
        self.assertIn("予報上の候補 10:00-12:00", block)

    def test_missing_target_hour_is_not_a_complete_window(self):
        self.assertEqual(build_day_block("2026-09-25", [record(8, 0.5)],
                                        date(2026, 9, 25)), "")


if __name__ == "__main__":
    unittest.main()
