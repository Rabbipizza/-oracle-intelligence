#!/usr/bin/env python3
"""Exercise the production collector, allocator, cockpit, validator and release gate offline."""
import contextlib
import copy
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.parse

import oracle_market
from oracle_cockpit import build_portfolio
from oracle_data_quality import series_quality
from oracle_release import package, verify
from oracle_validate import validate

ROOT=Path(__file__).resolve().parent
AS_OF='2026-10-13'


def fixture(root):
    dates=[]
    day=date(2026,8,3)
    while day<=date.fromisoformat(AS_OF):
        if day.weekday()<5: dates.append(day.isoformat())
        day+=timedelta(days=1)
    trends={}
    for key,first in [('power','AAON'),('minerals','TMRC'),('cuas','C0'),('physical','R0'),('photonics','P0')]:
        ticks=[first]+[key.upper()+str(i) for i in range(1,20)]
        trends[key]={'label':key,'companies':[[t,t,'Bottleneck','UNPROVEN'] for t in ticks]}
    tickers=[r[0] for tr in trends.values() for r in tr['companies']]+['QQQ']
    prices={t:{'currency':'USD','exchange':'TEST','symbol':t,'url':'https://example.invalid/'+t,
        'rows':[{'date':d,'close':100.0+i/5} for i,d in enumerate(dates)]} for t in tickers}
    ledger={'version':3,'kind':'ACTUAL','currency':'CHF','baseline_date':'2026-09-04',
        'initial_capital_chf':1000,'cash_chf':960,'benchmark_ticker':'QQQ',
        'positions':[{'ticker':'AAON','status':'OPEN','trade_date':'2026-09-04','allocated_chf':40}]}
    simulated={**copy.deepcopy(ledger),'kind':'SIMULATED'}
    companies={r[0]:{'ticker':r[0],'name':r[0],'trend':key,'role':r[2],
        'maturity':'PROVEN' if r[0]=='AAON' else 'CORROBORATED','explicit_proven':r[0]=='AAON',
        'company_capture_score':100 if r[0]=='AAON' else 0,'trend_evidence_score':100}
        for key,tr in trends.items() for r in tr['companies']}
    files={
        'portfolio.json':ledger,'portfolio-simulated.json':simulated,
        'research-universe.json':{'trends':trends},
        'decision-state.json':{},
        'economic-evidence.json':{'companies':{'AAON':{'status':'PROVEN','trend':'power','role':'Bottleneck',
            'evidence_date':'2026-09-04','primary_source':'SYNTHETIC TEST FIXTURE',
            'source_url':'https://example.invalid/primary-proof','invalidation':['loss of issuer-level primary proof']}}},
        'data/market.json':{'prices':prices,'fx_usd_chf':[{'date':d,'chf_per_usd':.8} for d in dates],'errors':[]},
        'data/company-challengers.json':{'trends':{}},
        'data/evidence-dossiers.json':{'companies':companies,'concepts':{key:{'evidence_score':100,'family_count':4,'economic_origin_count':2} for key in trends}},
        'data/company-revalidation.json':{'results':[],'promoted':[]},
        'data/discovery-candidates.json':{'quality':'OK','candidates':[]},
        'data/source-gate-status.json':{'discovery_quality':'OK','candidate_gates':[]},
        'scientific-protocol.json':{'objective':'SYNTHETIC TEST','overfitting_controls':{'deflated_sharpe_ratio':True}}
    }
    for name,value in files.items():
        path=root/name; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value))
    return files


class SafetyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        fixture(self.root)

    def read(self,name): return json.loads((self.root/name).read_text())
    def write(self,name,value): (self.root/name).write_text(json.dumps(value))
    def run_script(self,name,*args):
        return subprocess.run([sys.executable,str(ROOT/name),*args],cwd=self.root,text=True,capture_output=True)
    def build(self,passes=True):
        run=self.run_script('oracle_build.py','--replay-date',AS_OF)
        self.assertEqual(run.returncode==0,passes,run.stdout+'\n'+run.stderr)
        return run
    def result(self): return validate(self.root,date.fromisoformat(AS_OF))
    def change_market(self,mutate):
        data=self.read('data/market.json'); mutate(data); self.write('data/market.json',data)

    def test_single_actual_position_plus_cash_is_valid(self):
        self.build()
        c=self.read('data/cockpit.json')
        self.assertEqual(len(c['portfolio']['positions']),1)
        self.assertEqual(c['portfolio']['cash_chf'],960)
        self.assertEqual(c['actual_holdings_pct'],{'AAON':4,'CASH_CHF':96})

    def test_http404_research_candidate_is_audited_and_never_investable(self):
        market=self.read('data/market.json')
        def request(url,*args,**kwargs):
            ticker=urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit('/',1)[-1])
            if ticker=='TMRC': raise urllib.error.HTTPError(url,404,'Not Found',{},None)
            rs=market['prices'][ticker]['rows']
            payload={'chart':{'result':[{'timestamp':[int(datetime.fromisoformat(r['date']).replace(tzinfo=timezone.utc).timestamp()) for r in rs],
                'meta':{'symbol':ticker,'currency':'USD','exchangeName':'TEST'},'indicators':{'quote':[{'close':[r['close'] for r in rs]}]}}]}}
            return json.dumps(payload).encode()
        import os
        previous=Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.object(oracle_market,'request_bytes',side_effect=request), mock.patch.object(oracle_market,'usd_chf',return_value=(market['fx_usd_chf'],['https://example.invalid/fx'])), mock.patch.object(oracle_market.time,'sleep'), contextlib.redirect_stdout(io.StringIO()):
                oracle_market.main()
        finally: os.chdir(previous)
        raw=self.read('data/market.json')
        self.assertNotIn('TMRC',raw['prices'])
        self.assertEqual(raw['data_quality']['TMRC']['status'],'DATA_UNAVAILABLE')
        self.assertEqual(next(e for e in raw['errors'] if e['ticker']=='TMRC')['http_status'],404)
        self.build()
        c=self.read('data/cockpit.json')
        tmrc=next(r for tr in c['trends'] for r in tr['companies'] if r['ticker']=='TMRC')
        self.assertEqual(tmrc['data_status'],'DATA_UNAVAILABLE')
        self.assertNotEqual(tmrc['signal'],'GREEN')
        self.assertEqual(tmrc['indicative_entry_sizing']['max_pct'],0)
        self.assertEqual(c['target_allocation_pct'].get('TMRC',0),0)
        self.assertTrue(any('TMRC' in w for w in self.result()['warnings']))

    def test_missing_actual_holding_blocks_without_fabricating_total(self):
        before=(self.root/'portfolio.json').read_bytes()
        self.change_market(lambda m:m['prices'].pop('AAON'))
        self.build(False)
        self.assertEqual((self.root/'portfolio.json').read_bytes(),before)
        self.assertIsNone(self.read('data/cockpit.json')['portfolio']['total_value_chf'])
        self.assertTrue(any('critical_market_series_invalid:AAON' in e for e in self.result()['errors']))

    def test_missing_holding_outside_top20_is_critical(self):
        ledger=self.read('portfolio.json')
        ledger['cash_chf']=955
        ledger['positions'].append({'ticker':'HOLDX','status':'OPEN','allocated_chf':5,'trade_date':'2026-09-04'})
        self.write('portfolio.json',ledger)
        self.build(False)
        self.assertTrue(any('HOLDX' in e for e in self.result()['errors']))

    def test_missing_target_outside_top20_is_critical(self):
        self.build()
        for name in ['decision-state.json','data/cockpit.json']:
            d=self.read(name); d['target_allocation_pct']={'NEW':100}; self.write(name,d)
        self.assertTrue(any('critical_market_series_invalid:NEW' in e for e in self.result()['errors']))

    def test_green_outside_radar_without_target_cannot_bypass_validation(self):
        self.build()
        d=self.read('decision-state.json'); d['signals']['NEW']={'signal':'GREEN'}; self.write('decision-state.json',d)
        self.assertTrue(any('critical_market_series_invalid:NEW' in e for e in self.result()['errors']))

    def test_positive_sizing_without_green_or_target_cannot_bypass_validation(self):
        self.build()
        d=self.read('decision-state.json')
        d['scores']['NEW']={'indicative_entry_sizing':{'max_pct':10}}
        self.write('decision-state.json',d)
        self.assertTrue(any('critical_market_series_invalid:NEW' in e for e in self.result()['errors']))

    def test_provider_identity_and_duplicate_or_lagging_dates_are_rejected(self):
        self.build()
        initial=self.read('data/market.json')
        cases=[]
        wrong=copy.deepcopy(initial); wrong['prices']['AAON']['symbol']='OTHER'; cases.append(wrong)
        no_currency=copy.deepcopy(initial); no_currency['prices']['AAON'].pop('currency'); cases.append(no_currency)
        duplicate=copy.deepcopy(initial); duplicate['prices']['AAON']['rows'].append(duplicate['prices']['AAON']['rows'][-1]); cases.append(duplicate)
        lag=copy.deepcopy(initial); lag['prices']['AAON']['rows'].pop(); cases.append(lag)
        for market in cases:
            with self.subTest(case=market['prices']['AAON']):
                self.write('data/market.json',market)
                self.assertTrue(any('critical_market_series_invalid:AAON' in e for e in self.result()['errors']))
        self.write('data/market.json',initial)

    def test_initial_deployment_preserves_the_proven_actual_incumbent(self):
        self.build()
        decision=self.read('decision-state.json')
        self.assertGreaterEqual(decision['target_allocation_pct'].get('AAON',0),4)
        self.assertEqual(decision['actual_holdings_pct'],{'AAON':4,'CASH_CHF':96})

    def test_market_error_audit_cannot_be_dropped(self):
        self.change_market(lambda m:(m['prices'].pop('TMRC'),m['errors'].append({'ticker':'TMRC','http_status':404,'error':'fixture HTTP 404'})))
        self.build()
        cockpit=self.read('data/cockpit.json'); cockpit['market_errors']=[]; self.write('data/cockpit.json',cockpit)
        self.assertIn('market_error_audit_not_preserved',self.result()['errors'])

    def test_unpriced_proven_candidate_cannot_borrow_trend_strength(self):
        e=self.read('economic-evidence.json')
        e['companies']['TMRC']=copy.deepcopy(e['companies']['AAON'])
        self.write('economic-evidence.json',e)
        self.change_market(lambda m:m['prices'].pop('TMRC'))
        self.build()
        d=self.read('decision-state.json')
        self.assertNotEqual(d['signals']['TMRC']['signal'],'GREEN')
        self.assertEqual(d['scores']['TMRC']['indicative_entry_sizing']['max_pct'],0)
        self.assertEqual(d['target_allocation_pct'].get('TMRC',0),0)

    def test_zero_weight_missing_radar_name_is_not_a_holding(self):
        self.change_market(lambda m:m['prices'].pop('TMRC'))
        self.build()
        for name in ['decision-state.json','data/cockpit.json']:
            d=self.read(name); d['target_allocation_pct']['TMRC']=0; self.write(name,d)
        self.assertEqual(self.result()['status'],'PASS')

    def test_qqq_absence_blocks(self):
        self.change_market(lambda m:m['prices'].pop('QQQ'))
        self.build(False)

    def test_bad_price_values_block(self):
        self.build()
        initial=self.read('data/market.json')
        for value in [None,0,-1,float('nan'),float('inf')]:
            with self.subTest(close=value):
                m=copy.deepcopy(initial); m['prices']['QQQ']['rows'][-1]['close']=value; self.write('data/market.json',m)
                self.assertEqual(self.result()['status'],'FAIL')
        self.write('data/market.json',initial)

    def test_missing_invalid_stale_or_future_fx_blocks(self):
        self.build()
        initial=self.read('data/market.json')
        cases=[[],[{'date':'2000-01-01','chf_per_usd':.8},{'date':'2000-01-02','chf_per_usd':.8}],
            [{'date':'2099-01-01','chf_per_usd':.8},{'date':'2099-01-02','chf_per_usd':.8}]]
        for value in [0,-1,None,float('nan'),float('inf')]:
            cases.append([{'date':'2026-10-12','chf_per_usd':.8},{'date':AS_OF,'chf_per_usd':value}])
        for rows in cases:
            with self.subTest(rows=rows):
                m=copy.deepcopy(initial); m['fx_usd_chf']=rows; self.write('data/market.json',m)
                self.assertTrue(any('critical_fx_invalid:' in e for e in self.result()['errors']))
        self.write('data/market.json',initial)

    def test_missing_dates_stale_snapshot_and_short_history_block(self):
        self.build()
        c=self.read('data/cockpit.json')
        c['data_as_of']=None; c['decision_as_of']=None; self.write('data/cockpit.json',c)
        self.assertEqual(self.result()['status'],'FAIL')
        self.build()
        self.assertEqual(validate(self.root,date(2026,10,21))['status'],'FAIL')
        self.change_market(lambda m:m['prices']['AAON'].update(rows=m['prices']['AAON']['rows'][-1:]))
        self.build(False)

    def test_actual_simulated_and_target_never_update_each_other(self):
        before={name:(self.root/name).read_bytes() for name in ['portfolio.json','portfolio-simulated.json']}
        self.build(); self.build()
        for name,data in before.items(): self.assertEqual((self.root/name).read_bytes(),data)
        d=self.read('decision-state.json')
        self.assertNotEqual(d['actual_holdings_pct'],d['target_allocation_pct'])
        c=self.read('data/cockpit.json'); c['portfolio']=copy.deepcopy(c['simulated_portfolio']); self.write('data/cockpit.json',c)
        self.assertEqual(self.result()['status'],'FAIL')

    def test_full_capital_benchmark_includes_cash_and_negative_alpha(self):
        m=self.read('data/market.json')
        for ticker in ['AAON','QQQ']:
            for row in m['prices'][ticker]['rows']: row['close']=100
            m['prices'][ticker]['rows'][-1]['close']=110
        self.write('data/market.json',m)
        self.build()
        c=self.read('data/cockpit.json')['portfolio']['official_comparison']
        self.assertEqual(c['oracle_value_chf'],1004)
        self.assertEqual(c['qqq_value_chf'],1100)
        self.assertEqual(c['oracle_return_pct'],.4)
        self.assertEqual(c['alpha_chf'],-96)
        self.assertEqual(c['alpha_pct_points'],-9.6)
        self.assertEqual(self.result()['status'],'PASS')
        self.assertTrue(any('prospective_alpha_negative' in w for w in self.result()['warnings']))

    def test_benchmark_uses_entry_and_current_fx(self):
        m=self.read('data/market.json')
        for ticker in ['AAON','QQQ']:
            for row in m['prices'][ticker]['rows']: row['close']=100
            m['prices'][ticker]['rows'][-1]['close']=110
        m['fx_usd_chf'][-1]['chf_per_usd']=.9
        result=build_portfolio(m,self.read('portfolio.json'))['official_comparison']
        self.assertEqual(result['oracle_value_chf'],1009.5)
        self.assertEqual(result['qqq_value_chf'],1237.5)
        self.assertEqual(result['alpha_chf'],-228)
        self.assertEqual(result['alpha_pct_points'],-22.8)

    def test_missing_entry_date_coverage_blocks(self):
        self.change_market(lambda m:m.update(fx_usd_chf=m['fx_usd_chf'][-2:]))
        self.build(False)
        self.assertTrue(any('benchmark_metric_missing' in e for e in self.result()['errors']))

    def test_missing_simulated_holding_cannot_create_partial_total(self):
        sim=self.read('portfolio-simulated.json')
        sim['positions'].append({'ticker':'SIMX','allocated_chf':5,'status':'OPEN','trade_date':'2026-09-04'})
        sim['cash_chf']-=5; self.write('portfolio-simulated.json',sim)
        self.build(False)
        self.assertIsNone(self.read('data/cockpit.json')['simulated_portfolio']['total_value_chf'])

    def test_unproven_company_does_not_inherit_trend_proof(self):
        self.build()
        d=self.read('decision-state.json')
        self.assertNotEqual(d['signals']['POWER1']['signal'],'GREEN')
        self.assertEqual(d['target_allocation_pct'].get('POWER1',0),0)
        chains=self.read('data/economic-chains.json')
        self.assertFalse(chains['companies']['POWER1']['investable'])
        self.assertIn('explicit_company_capture',chains['companies']['POWER1']['blockers'])

    def test_forged_explicit_dossier_is_rejected(self):
        d=self.read('data/evidence-dossiers.json')
        d['companies']['TMRC']['explicit_proven']=True
        self.write('data/evidence-dossiers.json',d)
        self.build(False)
        self.assertIn('unproven_company_capture_inherited',self.result()['errors'])

    def test_automatic_proof_is_revoked_when_sources_no_longer_pass(self):
        e=self.read('economic-evidence.json')
        e['companies']['AAON']['validation_method']='ORACLE_STRICT_PRIMARY_REVALIDATION_V1'
        self.write('economic-evidence.json',e)
        run=self.run_script('oracle_company_revalidate.py')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertNotEqual(self.read('economic-evidence.json')['companies']['AAON']['status'],'PROVEN')

    def test_fetch_universe_includes_holdings_targets_and_long_lived_baseline(self):
        actual=self.read('portfolio.json'); actual['positions'].append({'ticker':'HOLDX','status':'OPEN','allocated_chf':5,'trade_date':'2026-09-04'})
        self.write('portfolio.json',actual)
        self.write('decision-state.json',{'target_allocation_pct':{'TARGETX':5,'CASH_CHF':95}})
        import os
        previous=Path.cwd()
        try:
            os.chdir(self.root)
            self.assertIn('HOLDX',oracle_market.universe_tickers())
            self.assertIn('TARGETX',oracle_market.universe_tickers())
            self.assertNotIn('CASH_CHF',oracle_market.universe_tickers())
            self.assertLess(oracle_market.history_start(datetime(2027,10,21,tzinfo=timezone.utc)),date(2026,9,4))
        finally: os.chdir(previous)

    def test_real_baseline_is_exactly_the_confirmed_one(self):
        actual=json.loads((ROOT/'portfolio.json').read_text())
        self.assertEqual(actual['kind'],'ACTUAL')
        self.assertEqual(actual['cash_chf'],960)
        self.assertEqual([(p['ticker'],p['allocated_chf'],p['trade_date']) for p in actual['positions']],[('AAON',40,'2026-09-04')])

    def test_release_rejects_historical_payload_and_tampered_files(self):
        today=datetime.now(timezone.utc).date().isoformat()
        (self.root/'index.html').write_text('<!doctype html><title>fixture</title>')
        self.write('data/cockpit.json',{'data_as_of':today})
        self.write('data/funnel-audit.json',{})
        self.write('data/validation.json',{'status':'PASS','errors':[],'validation_mode':'HISTORICAL_REPLAY','data_as_of':today})
        historical=self.root/'historical'
        package(self.root,historical,'fixture',replay=True)
        with self.assertRaises(ValueError): verify(historical)
        self.write('data/validation.json',{'status':'PASS','errors':[],'validation_mode':'PRODUCTION','data_as_of':today})
        release=self.root/'release'
        package(self.root,release,'fixture')
        self.assertEqual(verify(release)['source_sha'],'fixture')
        (release/'index.html').write_text('changed after validation')
        with self.assertRaisesRegex(ValueError,'hash mismatch'): verify(release)

    def test_unvalidated_pages_path_is_removed_and_ci_has_no_write_permission(self):
        self.assertFalse((ROOT/'.github/workflows/pages.yml').exists())
        ci=(ROOT/'.github/workflows/oracle-ci.yml').read_text()
        self.assertIn('pull_request:',ci)
        self.assertIn('contents: read',ci)
        self.assertNotIn('contents: write',ci)
        production=(ROOT/'.github/workflows/oracle-sources.yml').read_text()
        self.assertIn("vars.ORACLE_PRODUCTION_ENABLED == 'true'",production)
        self.assertNotIn('ref: main',production)
        self.assertNotIn('git rebase',production)
        self.assertIn('oracle_release.py .verified-site',production)


if __name__=='__main__': unittest.main()
