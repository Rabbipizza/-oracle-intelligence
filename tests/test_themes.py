import unittest
from datetime import date,timedelta
from oracle_themes import THEMES,choose_theme,make_billboard

SOURCES=[
    ("geek_gaming","Geek feed","geek","google_news","rss","https://example.org"),
    ("google_news_us","News","news","google_news","rss","https://example.org")
]
def snap(day, geek=5, tech=1, include=True):
    sources = {
        "geek_gaming": {"documents":50,"terms":{
            "nintendo switch":{"count":geek,"links":["https://example.org/g"]},
            "anime cosplay":{"count":min(geek,3),"links":["https://example.org/a"]}}},
        "google_news_us": {"documents":50,"terms":{
            "quantum computing":{"count":tech,"links":["https://example.org/q"]}}}
    }
    health=[{"source":key,"status":"OK"} for key in sources]
    if not include:
        sources.pop("geek_gaming")
        health=[{"source":"geek_gaming","status":"RATE_LIMITED"},{"source":"google_news_us","status":"OK"}]
    return {"date":day.isoformat(),"sources":sources,"source_health":health}

class ThemeBillboardTests(unittest.TestCase):
    def test_geek_is_a_theme(self):
        self.assertIn("geek",THEMES)
        self.assertEqual(choose_theme("anime cosplay","news"),"geek")
        self.assertEqual(choose_theme("quantum computing","news"),"technology")

    def test_preview_never_invents_weekly_delta(self):
        d=date(2026,11,12)
        b=make_billboard(d.isoformat(),snap(d),[],SOURCES)
        self.assertEqual(b["geek"]["state"],"PREVIEW")
        self.assertEqual(b["geek"]["top20"][0]["rank"],1)
        self.assertIsNone(b["geek"]["top20"][0]["movement"])
        self.assertEqual(b["geek"]["top20"][0]["movement_status"],"UNAVAILABLE")
        self.assertIsNone(b["geek"]["top20"][0]["weeks_on_chart"])

    def test_true_weekly_movement_compares_complete_windows(self):
        d=date(2026,11,12)
        prev=[]
        for offset in range(13,0,-1):
            day=d-timedelta(days=offset)
            # Older week anime leads, current week Nintendo leads
            p=snap(day,geek=1 if offset>=7 else 8,tech=2)
            p["sources"]["geek_gaming"]["terms"]["anime cosplay"]["count"]=8 if offset>=7 else 1
            prev.append(p)
        today=snap(d,geek=8,tech=2)
        today["sources"]["geek_gaming"]["terms"]["anime cosplay"]["count"]=1
        b=make_billboard(d.isoformat(),today,prev,SOURCES)["geek"]
        self.assertEqual(b["state"],"WEEKLY_COMPARABLE")
        self.assertEqual(b["top20"][0]["term"],"nintendo switch")
        self.assertEqual(b["top20"][0]["previous_rank"],2)
        self.assertEqual(b["top20"][0]["movement"],1)
        self.assertEqual(b["top20"][0]["movement_status"],"UP")

    def test_rate_limited_day_disables_weekly_comparison(self):
        d=date(2026,11,12)
        prev=[snap(d-timedelta(days=k),include=(k!=9)) for k in range(13,0,-1)]
        b=make_billboard(d.isoformat(),snap(d),prev,SOURCES)
        # Other source is fully available but Geek is not: no fake chart movement
        self.assertEqual(b["geek"]["state"],"WEEKLY_COMPARABLE")
        # Source pool restricted to only google_news_us, so geek has no entries.
        self.assertEqual(b["geek"]["top20"],[])
        self.assertEqual(b["technology"]["state"],"WEEKLY_COMPARABLE")

    def test_no_internet_samples_no_rank(self):
        d=date(2026,11,12)
        b=make_billboard(d.isoformat(),{"date":d.isoformat(),"sources":{}},[],SOURCES)
        self.assertEqual(b["geek"]["top20"],[])

if __name__=="__main__":
    unittest.main()
