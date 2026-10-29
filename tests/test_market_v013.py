import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('accelerator',ROOT/'accelerator.py'); a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

def market(now=2000,a_price=70000,b_price=70100):
    prices=[a_price,b_price]; center=sum(prices)/2
    dev=max(abs(x-center)/center for x in prices)
    return {'schema':'hashburst-market-observation-v1','observed_at':now,'expires_at':now+900,'fiat_currency':'EUR','btc_fiat':center,
      'sources':[{'provider':'coingecko','btc_fiat':a_price,'observed_at':now,'response_sha256':'a'*64},{'provider':'coinbase','btc_fiat':b_price,'observed_at':now,'response_sha256':'b'*64}],
      'cross_check':{'sources_usable':2,'max_deviation_ratio':dev,'accepted':True},'production_apply':False}

def worker(t,pool='Zpool',revenue=.0001,temp=50):
 return {'user':'u','worker':'w','machinename':'h','cpu':'c','lastseen':t,'online':True,'status':'Running','powerdraw':100,
 'data':[{'Name':'m','Version':'1','Algorithm':['RandomX'],'Pool':[pool],'Devices':[{'Id':0,'Name':'CPU','Temp':temp}],
 'BTC/day':revenue,'Benchmarking':False,'Donator':False,'Accepted':[1],'Rejected':[0],'Stale':[0]}]}
class V013(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.path=Path(self.t.name)/'history.sqlite';self.db=a.database(self.path)
  self.p=a.read_json(ROOT/'policy.example.json');self.p['electricity_fiat_kwh']=.2;self.p['max_age_seconds']=1000
 def tearDown(self): self.db.close();self.t.cleanup()
 def ingest(self,w,t): a.collect(self.db,[w],{'generated_at':t,'pools':[]},t,1000)
 def test_policy_refuses_legacy_price(self):
  p=dict(self.p);p['btc_fiat']=70000
  with self.assertRaises(ValueError):a.validate_policy(p)
 def test_market_fresh_and_hashed(self):
  m=market();s=a.validate_market(m,self.p,2000);self.assertTrue(s['usable']);self.assertEqual(len(s['sha256']),64)
 def test_market_stale(self): self.assertFalse(a.validate_market(market(),self.p,4000)['usable'])
 def test_market_tampered_crosscheck_refused(self):
  m=market();m['cross_check']['accepted']=False
  with self.assertRaises(ValueError):a.validate_market(m,self.p,2000)
 def test_market_excess_deviation_refused(self):
  m=market();m['cross_check']['max_deviation_ratio']=.5
  with self.assertRaises(ValueError):a.validate_market(m,self.p,2000)
 def test_distinct_sources_required(self):
  m=market();m['sources'][1]['provider']='coingecko'
  with self.assertRaises(ValueError):a.validate_market(m,self.p,2000)
 def test_history_schema_unchanged(self):
  cols={n:[r[1] for r in self.db.execute('pragma table_info('+n+')')] for n in ['samples','collections','worker_health','local_identity']}
  self.assertEqual(cols['samples'],['worker','sampled','profile','payload']);self.assertEqual(len(cols),4)
 def test_fresh_market_can_recommend(self):
  for i in range(6):self.ingest(worker(1000+i*60,'Nanopool',.0002),1000+i*60)
  for i in range(6):self.ingest(worker(1400+i*60,'Zpool',.0001),1400+i*60)
  r=a.recommend(self.db,self.p,market(2000),2000);self.assertEqual(r['decisions'][0]['action'],'recommend_profile');self.assertIn('market_observation_sha256',r)
 def test_stale_market_holds(self):
  self.ingest(worker(2000),2000);r=a.recommend(self.db,self.p,market(1),2000);self.assertEqual(r['decisions'][0]['action'],'hold')
 def test_status_read_only_legacy_history(self):
  self.ingest(worker(2000),2000);self.db.commit();r=a.status_report(self.path,self.p,market(),2000);self.assertTrue(r['read_only']);self.assertEqual(r['version'],'0.1.3')
class MigrationPolicy(unittest.TestCase):
 def test_migration_removes_only_volatile_economics(self):
  old=a.read_json(ROOT/'legacy-policy-v0.1.2.example.json');new,report=a.migrate_policy_v012(old)
  self.assertNotIn('btc_fiat',new);self.assertNotIn('price_observed_at',new)
  self.assertEqual(new['electricity_fiat_kwh'],old['electricity_fiat_kwh']);self.assertEqual(report['volatile_fields_removed'],['btc_fiat','price_observed_at'])

if __name__=='__main__':unittest.main()