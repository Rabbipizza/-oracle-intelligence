import unittest
from oracle_themes import _daily_theme_data, _rank_theme

class ChartQualityTests(unittest.TestCase):
    def test_one_document_is_not_a_10000_point_trend(self):
        snap={"sources":{"fed":{"documents":1,"terms":{
            "announces approval":{"count":1,"links":["https://example.org/a"]}}}}}
        grouped=_daily_theme_data(snap,{"fed":"macroeconomics"})
        self.assertEqual(dict(grouped["economics"]),{})

    def test_minimum_two_mentions_and_smoothing(self):
        snap={"sources":{"geek_gaming":{"documents":10,"terms":{
            "nintendo switch":{"count":2,"links":["https://example.org/g"]},
            "random article":{"count":1,"links":["https://example.org/x"]}}}}}
        results=_rank_theme([snap],{"geek_gaming":"geek"},"geek")
        self.assertEqual(len(results),1)
        self.assertEqual(results[0]["term"],"nintendo switch")
        self.assertLess(results[0]["score"],1000)

if __name__=="__main__":
    unittest.main()
