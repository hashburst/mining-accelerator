#!/usr/bin/env python3
"""Read-only telemetry collection and empirical mining policy evaluation."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import sys
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import time
import urllib.request
import urllib.parse

VERSION = '0.1.3'
MAX_BYTES = 16 * 1024 * 1024

def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(v):
    return hashlib.sha256(canonical(v).encode()).hexdigest()

def number(v, minimum=0):
    if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < minimum:
        raise ValueError('invalid finite numeric telemetry')
    return v

def fetch_json(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.username or parts.password:
        raise ValueError('HTTPS endpoint required without embedded credentials')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('API redirects refused')
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'HashBurst-Accelerator/'+VERSION})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        data = response.read(MAX_BYTES+1)
    if len(data) > MAX_BYTES:
        raise ValueError('API response exceeds limit')
    return json.loads(data, parse_constant=reject_constant, object_pairs_hook=unique_object)

def reject_constant(value):
    raise ValueError('non-finite JSON number refused')

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key refused')
        result[key] = value
    return result

def read_json(path):
    with open(path, encoding='utf-8-sig') as f:
        return json.load(f, parse_constant=reject_constant, object_pairs_hook=unique_object)

def write_new(path, value):
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n'
    with open(path, 'x', encoding='utf-8', newline='\n') as f:
        f.write(text)

def database(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS samples (worker TEXT, sampled INTEGER, profile TEXT, payload TEXT, PRIMARY KEY(worker,sampled))')
    db.execute('CREATE TABLE IF NOT EXISTS collections (collected INTEGER PRIMARY KEY, payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS worker_health (worker TEXT PRIMARY KEY, collected INTEGER, healthy INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS local_identity (id INTEGER PRIMARY KEY CHECK(id=1), salt BLOB)')
    db.execute('INSERT OR IGNORE INTO local_identity VALUES (1, ?)', (os.urandom(32),))
    db.commit()
    return db

def strings(value):
    if not isinstance(value, list) or not value or any(not isinstance(x,str) or not x or len(x)>128 for x in value):
        raise ValueError('expected nonempty string list')
    return value

def normalize(worker, salt, now, max_age):
    identity = [worker.get('user'), worker.get('worker'), worker.get('machinename')]
    if any(not isinstance(x,str) or not x for x in identity):
        raise ValueError('worker identity incomplete')
    key = hmac.new(salt, canonical(identity).encode(), hashlib.sha256).hexdigest()
    seen = int(number(worker['lastseen']))
    if seen > now+30 or now-seen > max_age or worker.get('online') is not True or worker.get('status') != 'Running':
        raise ValueError('worker offline, paused or stale')
    if any(worker.get(k) not in (None,0,False,'') for k in ('tempalert','crashalert','uncleanalert','diskmingbalert')):
        raise ValueError('worker health alert')
    watts = number(worker['powerdraw'])
    if watts <= 0:
        raise ValueError('missing measured power')
    temp = 0  # maxtemp is an alert threshold, not a sensor reading.
    workload=[]; revenue=0; accepted=0; rejected=0
    data=worker.get('data')
    if not isinstance(data,list) or not data:
        raise ValueError('missing workload')
    for miner in data:
        if miner.get('Benchmarking') is not False or miner.get('Donator') is not False:
            raise ValueError('benchmark or donation workload')
        slots=[]
        for device in miner.get('Devices',[]):
            slots.append({'id':str(device['Id']), 'name':str(device['Name'])})
            measured = number(device['Temp'])
            if measured <= 0:
                raise ValueError('missing measured device temperature')
            temp=max(temp,measured)
        if not slots:
            raise ValueError('missing device inventory')
        workload.append({'miner':str(miner['Name']), 'version':str(miner['Version']),
                         'algorithms':strings(miner['Algorithm']), 'pools':strings(miner['Pool']),
                         'devices':sorted(slots,key=canonical)})
        revenue += number(miner['BTC/day'])
        for field in ('Accepted','Rejected','Stale'):
            values=miner.get(field)
            if not isinstance(values,list) or not values:
                raise ValueError('missing share counters')
            total=sum(number(x) for x in values)
            if field=='Accepted':accepted+=total
            else:rejected+=total
    workload.sort(key=canonical)
    hardware=digest({'cpu':worker.get('cpu'), 'slots':[x['devices'] for x in workload]})
    profile=digest(workload)
    return {'worker':key,'sampled':seen,'profile':profile,'hardware':hardware,'workload':workload,
            'estimated_btc_day':revenue,'watts':watts,'temperature_c':temp,
            'temperature_source':'device_temp_v1',
            'accepted':accepted,'rejected_or_stale':rejected}

def collect(db, workers, pools, now, max_age=300):
    if not isinstance(workers,list):
        raise ValueError('RainbowMiner response must be a worker list')
    if not isinstance(pools,dict) or not isinstance(pools.get('pools'),list):
        raise ValueError('pool summary schema not recognized')
    timestamp=int(number(pools['generated_at']))
    if not -30 <= now-timestamp <= max_age:
        raise ValueError('pool summary stale')
    salt=db.execute('SELECT salt FROM local_identity WHERE id=1').fetchone()[0]
    counts={'received':len(workers),'inserted':0,'duplicates':0,'excluded':0}
    reasons={}
    with db:
        for worker in workers:
            if not isinstance(worker, dict):
                counts['excluded'] += 1
                reasons['incomplete telemetry'] = reasons.get('incomplete telemetry', 0) + 1
                continue
            identity=[worker.get('user'),worker.get('worker'),worker.get('machinename')]
            key=hmac.new(salt,canonical(identity).encode(),hashlib.sha256).hexdigest()
            db.execute('INSERT OR REPLACE INTO worker_health VALUES (?,?,0)',(key,now))
            try:
                row=normalize(worker,salt,now,max_age)
                cur=db.execute('INSERT OR IGNORE INTO samples VALUES (?,?,?,?)',
                               (row['worker'],row['sampled'],row['profile'],canonical(row)))
                counts['inserted' if cur.rowcount else 'duplicates']+=1
                db.execute('UPDATE worker_health SET healthy=1 WHERE worker=?',(key,))
            except (ValueError,KeyError,TypeError) as exc:
                counts['excluded']+=1
                reason=str(exc) if isinstance(exc,ValueError) else 'incomplete telemetry'
                reasons[reason]=reasons.get(reason,0)+1
        # Pool totals are not allocated to individual workers or treated as payouts.
        summary={'collected_at':now,'workers':counts,'excluded_reasons':reasons,
                 'pool_generated_at':timestamp,'pool_count':len(pools['pools']),
                 'pool_summary_sha256':digest(pools),'worker_response_sha256':digest(workers)}
        db.execute('INSERT OR REPLACE INTO collections VALUES (?,?)',(now,canonical(summary)))
    return summary

def validate_policy(p):
    if not isinstance(p, dict):
        raise ValueError('policy must be a JSON object')
    if p.get('mode') != 'shadow':
        raise ValueError('only shadow mode is implemented')
    integer_keys = ('max_age_seconds', 'history_seconds', 'min_samples',
                    'min_span_seconds', 'min_sample_spacing_seconds')
    for key in integer_keys:
        value = p.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError('policy requires positive integer: ' + key)
    for key in ('max_temperature_c', 'min_improvement_btc_day',
                'min_improvement_ratio', 'confidence_multiplier'):
        number(p.get(key))
    if p['max_temperature_c'] <= 0:
        raise ValueError('temperature limit must be positive')
    if p['min_samples'] < 3 or p['min_span_seconds'] < 60 or p['min_sample_spacing_seconds'] < 1:
        raise ValueError('insufficient statistical observation policy')
    if p['history_seconds'] < max(p['min_span_seconds'], (p['min_samples']-1)*p['min_sample_spacing_seconds']):
        raise ValueError('history window cannot contain required samples')
    for key in ('allowed_pools', 'allowed_algorithms'):
        values = strings(p.get(key))
        if len(set(values)) != len(values) or any(x != x.strip() for x in values):
            raise ValueError('allowlist duplicates or surrounding whitespace: ' + key)
    if p.get('electricity_fiat_kwh') is not None:
        number(p['electricity_fiat_kwh'])
    if 'btc_fiat' in p or 'price_observed_at' in p:
        raise ValueError('volatile market price fields are forbidden in policy v0.1.3')
    if p.get('fiat_currency') != 'EUR':
        raise ValueError('v0.1.3 requires fiat_currency EUR')
    for key in ('market_max_age_seconds', 'market_min_sources'):
        value=p.get(key)
        if isinstance(value,bool) or not isinstance(value,int) or value <= 0:
            raise ValueError('policy requires positive integer: '+key)
    number(p.get('market_max_deviation_ratio'))
    return p


def existing_database(path):
    """Open an existing history without initialization or identity generation."""
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('history is not a regular file')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        expected = {
            'samples': ['worker', 'sampled', 'profile', 'payload'],
            'collections': ['collected', 'payload'],
            'worker_health': ['worker', 'collected', 'healthy'],
            'local_identity': ['id', 'salt'],
        }
        tables = dict(db.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view')"))
        for table, columns in expected.items():
            if tables.get(table) != 'table':
                raise ValueError('history schema not recognized')
            if [r[1] for r in db.execute('PRAGMA table_info(' + table + ')')] != columns:
                raise ValueError('history schema not recognized')
        identity = db.execute('SELECT id,salt FROM local_identity').fetchall()
        if len(identity) != 1 or identity[0][0] != 1 or not isinstance(identity[0][1], bytes) or len(identity[0][1]) != 32:
            raise ValueError('history identity missing or invalid; no replacement generated')
        return db
    except Exception:
        db.close()
        raise


def validate_market(m, p, now):
    if not isinstance(m,dict) or m.get('schema') != 'hashburst-market-observation-v1':
        raise ValueError('market observation schema not recognized')
    if m.get('production_apply') is not False:
        raise ValueError('market observation cannot authorize apply')
    if m.get('fiat_currency') != p['fiat_currency']:
        raise ValueError('market fiat currency mismatch')
    observed=m.get('observed_at'); expires=m.get('expires_at')
    if any(isinstance(x,bool) or not isinstance(x,int) for x in (observed,expires)):
        raise ValueError('market timestamps invalid')
    if expires <= observed or expires-observed > p['market_max_age_seconds']:
        raise ValueError('market expiry invalid')
    price=number(m.get('btc_fiat'))
    if price <= 0: raise ValueError('BTC exchange rate must be positive')
    sources=m.get('sources')
    if not isinstance(sources,list) or len(sources) < p['market_min_sources']:
        raise ValueError('insufficient market sources')
    providers=set()
    for src in sources:
        if not isinstance(src,dict): raise ValueError('market source invalid')
        provider=src.get('provider')
        if not isinstance(provider,str) or not provider or provider in providers: raise ValueError('market providers must be distinct')
        providers.add(provider); number(src.get('btc_fiat'))
        if not isinstance(src.get('response_sha256'),str) or len(src['response_sha256']) != 64: raise ValueError('market source provenance invalid')
    cross=m.get('cross_check')
    if not isinstance(cross,dict) or cross.get('accepted') is not True: raise ValueError('market cross-check not accepted')
    deviation=number(cross.get('max_deviation_ratio'))
    if deviation > p['market_max_deviation_ratio']: raise ValueError('market source deviation exceeds policy')
    age=now-observed
    state='future' if age < -30 else 'stale' if age > p['market_max_age_seconds'] or now > expires else 'fresh'
    return {'state':state,'age_seconds':age,'usable':state=='fresh','sha256':digest(m)}

def policy_status(p, market, now):
    validate_policy(p)
    ms=validate_market(market,p,now)
    return {'valid':True,'mode':p['mode'],'policy_sha256':digest(p),
            'fiat_currency':p['fiat_currency'],'electricity_fiat_kwh':p.get('electricity_fiat_kwh'),
            'market_state':ms['state'],'market_age_seconds':ms['age_seconds'],
            'market_observation_sha256':ms['sha256'],'market_observed_at':market['observed_at'],
            'market_expires_at':market['expires_at'],'market_sources':len(market['sources']),
            'economics_usable':ms['usable'] and p.get('electricity_fiat_kwh') is not None,
            'allowed_pools':p['allowed_pools'],'allowed_algorithms':p['allowed_algorithms'],
            'max_age_seconds':p['max_age_seconds'],'min_samples':p['min_samples'],
            'min_span_seconds':p['min_span_seconds'],'min_sample_spacing_seconds':p['min_sample_spacing_seconds']}

def parse_market_source(provider, payload, observed_at):
    if provider == 'coingecko':
        price=payload['bitcoin']['eur']
    elif provider == 'coinbase':
        if str(payload['data'].get('currency','EUR')).upper() != 'EUR': raise ValueError('Coinbase currency mismatch')
        price=float(payload['data']['amount'])
    else: raise ValueError('unsupported market provider')
    price=number(price)
    if price <= 0: raise ValueError('BTC exchange rate must be positive')
    return {'provider':provider,'btc_fiat':price,'observed_at':observed_at,'response_sha256':digest(payload)}

def market_collect(source_specs, policy, now):
    validate_policy(policy)
    sources=[]
    for provider,url in source_specs:
        payload=fetch_json(url)
        sources.append(parse_market_source(provider,payload,now))
    if len({x['provider'] for x in sources}) < policy['market_min_sources']:
        raise ValueError('insufficient independent market providers')
    prices=[x['btc_fiat'] for x in sources]
    center=statistics.median(prices)
    deviation=max(abs(x-center)/center for x in prices)
    accepted=deviation <= policy['market_max_deviation_ratio']
    if not accepted: raise ValueError('market source deviation exceeds policy')
    return {'schema':'hashburst-market-observation-v1','observed_at':now,
            'expires_at':now+policy['market_max_age_seconds'],'fiat_currency':policy['fiat_currency'],
            'btc_fiat':center,'sources':sources,
            'cross_check':{'sources_usable':len(sources),'max_deviation_ratio':deviation,'accepted':True},
            'production_apply':False}

def status_report(path, policy, market, now):
    """Aggregate-only diagnostics. No keys, endpoints or per-worker identifiers."""
    result = {'schema': 'hashburst-accelerator-status-v1', 'version': VERSION,
              'created_at': now, 'read_only': True, 'mode': 'shadow',
              'apply_supported': False, 'full_node_status': 'not_checked',
              'policy': policy_status(policy, market, now), 'market': {'schema':market['schema'],'sha256':digest(market)}}
    with closing(existing_database(path)) as db:
        db.execute('BEGIN')  # A consistent read snapshot, including committed WAL.
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('history integrity check failed')
        total, workers, oldest, newest = db.execute('SELECT count(*),count(DISTINCT worker),min(sampled),max(sampled) FROM samples').fetchone()
        normalized = 0
        for (payload,) in db.execute('SELECT payload FROM samples'):
            row = json.loads(payload)
            normalized += row.get('temperature_source') == 'device_temp_v1'
        collections, last = db.execute('SELECT count(*),max(collected) FROM collections').fetchone()
        summary = recommend(db, policy, market, now)
        reasons = {}
        actions = {}
        for decision in summary['decisions']:
            reason = decision['reason']
            reasons[reason] = reasons.get(reason, 0) + 1
            action = decision['action']
            actions[action] = actions.get(action, 0) + 1
        last_counts = None
        if last is not None:
            latest = json.loads(db.execute('SELECT payload FROM collections WHERE collected=?', (last,)).fetchone()[0])
            last_counts = latest.get('workers')
        result['history'] = {'integrity': 'ok', 'samples_total': total,
                             'samples_device_temp_v1': normalized,
                             'samples_legacy_temperature': total-normalized,
                             'workers_total': workers, 'oldest_sample_at': oldest,
                             'newest_sample_at': newest, 'collections_total': collections,
                             'last_collection_at': last, 'last_collection_counts': last_counts}
        result['evaluation'] = {'workers_in_history_window': len(summary['decisions']),
                                'action_counts': actions, 'reason_counts': reasons}
    return result


def doctor():
    return {'version': VERSION, 'platform': platform.system(), 'architecture': platform.machine(),
            'python': platform.python_version(), 'cpu_logical': os.cpu_count(),
            'accelerator_mode': 'shadow', 'apply_supported': False,
            'full_node_installed': None, 'full_node_status': 'not_checked',
            'full_node_note': 'This command does not probe full-node services.',
            'gpu_fpga_asic_capability': 'requires driver and benchmark discovery'}


def recommend(db, p, market, now):
    validate_policy(p)
    ms=validate_market(market,p,now)
    out={'schema':'hashburst-accelerator-shadow-v1','created_at':now,'expires_at':now+p['max_age_seconds'],
         'policy_sha256':digest(p),'market_observation_sha256':digest(market),'market_observed_at':market['observed_at'],
         'mode':'shadow','apply_supported':False,
         'objective':'estimated BTC/day minus electricity; not settled pool payouts',
         'decisions':[]}
    economics=p.get('electricity_fiat_kwh') is not None and ms['usable']
    btc_fiat=market['btc_fiat']
    rows=[json.loads(x[0]) for x in db.execute('SELECT payload FROM samples WHERE sampled>=? AND sampled<=? ORDER BY worker,sampled',(now-p['history_seconds'],now+30))]
    workers={}
    for row in rows:workers.setdefault(row['worker'],[]).append(row)
    for worker,history in workers.items():
        latest=history[-1]
        decision={'worker':worker,'action':'hold','current_profile':latest['profile'],'sampled':latest['sampled']}
        out['decisions'].append(decision)
        if latest.get('temperature_source') != 'device_temp_v1':
            decision['reason']='new temperature telemetry required after collector upgrade';continue
        health=db.execute('SELECT collected,healthy FROM worker_health WHERE worker=?',(worker,)).fetchone()
        if not health or not health[1] or now-health[0]>p['max_age_seconds']:
            decision['reason']='current worker health not confirmed';continue
        if now-latest['sampled']>p['max_age_seconds']:
            decision['reason']='stale telemetry';continue
        if latest['temperature_c'] > p['max_temperature_c']:
            decision['reason']='current temperature exceeds policy';continue
        if not economics:
            decision['reason']='electricity cost or fresh BTC price missing';continue
        grouped={}
        for row in history:
            if row.get('temperature_source') != 'device_temp_v1':continue
            if row['hardware']!=latest['hardware'] or row['temperature_c']>p['max_temperature_c']:continue
            if any(pool not in p['allowed_pools'] for m in row['workload'] for pool in m['pools']):continue
            if any(alg not in p['allowed_algorithms'] for m in row['workload'] for alg in m['algorithms']):continue
            group=grouped.setdefault(row['profile'],[])
            if not group or row['sampled']-group[-1]['sampled']>=p['min_sample_spacing_seconds']:group.append(row)
        models={}
        for profile,samples in grouped.items():
            if len(samples)<p['min_samples'] or samples[-1]['sampled']-samples[0]['sampled']<p['min_span_seconds']:continue
            if now-samples[-1]['sampled']>p['max_age_seconds']:continue
            values=[s['estimated_btc_day']-s['watts']*24/1000*p['electricity_fiat_kwh']/btc_fiat for s in samples]
            mean=statistics.mean(values)
            margin=p['confidence_multiplier']*statistics.stdev(values)/math.sqrt(len(values))
            models[profile]={'mean':mean,'lower':mean-margin,'upper':mean+margin,'samples':len(values),
                             'workload':samples[-1]['workload']}
        if latest['profile'] not in models or len(models)<2:
            decision['reason']='insufficient recent comparable workload history';continue
        current=models[latest['profile']]
        best=max(models,key=lambda x:models[x]['lower'])
        delta=models[best]['lower']-current['upper']
        threshold=max(p['min_improvement_btc_day'],abs(current['mean'])*p['min_improvement_ratio'])
        if best!=latest['profile'] and delta>threshold:
            decision.update(action='recommend_profile',candidate_profile=best,workload=models[best]['workload'],
                            conservative_gain_btc_day=delta,reason='empirical estimate exceeds switching threshold')
        else:decision['reason']='no sufficiently supported improvement'
        decision['model']=models
    return out

def migrate_policy_v012(old):
    if not isinstance(old,dict): raise ValueError('legacy policy must be object')
    out=dict(old)
    removed={}
    for key in ('btc_fiat','price_observed_at'):
        if key in out: removed[key]=out.pop(key)
    out.setdefault('fiat_currency','EUR')
    out.setdefault('market_max_age_seconds',out.get('max_age_seconds',900))
    out.setdefault('market_min_sources',2)
    out.setdefault('market_max_deviation_ratio',0.02)
    validate_policy(out)
    return out, {'schema':'hashburst-policy-migration-v1','from':'0.1.2','to':'0.1.3',
                 'volatile_fields_removed':sorted(removed),'old_policy_sha256':digest(old),'new_policy_sha256':digest(out)}

def main():
    if sys.version_info < (3, 10):
        raise ValueError('Python 3.10 or later is required')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=VERSION)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('collect')
    c.add_argument('--db', required=True)
    c.add_argument('--workers-url-env', default='HB_RBMINER_URL')
    c.add_argument('--pool-url', default='https://blockchainapi.one/api/hashburst/mining/summary')
    c.add_argument('--max-age-seconds', type=int, default=300)
    c.add_argument('--out')
    r = sub.add_parser('recommend')
    r.add_argument('--db', required=True)
    r.add_argument('--policy', required=True)
    r.add_argument('--market', required=True)
    r.add_argument('--out', required=True)
    t = sub.add_parser('status')
    t.add_argument('--db', required=True)
    t.add_argument('--policy', required=True)
    t.add_argument('--market', required=True)
    t.add_argument('--out')
    m = sub.add_parser('market-collect')
    m.add_argument('--policy', required=True)
    m.add_argument('--source-a-env', default='HB_MARKET_SOURCE_A_URL')
    m.add_argument('--source-a-provider', choices=['coingecko','coinbase'], default='coingecko')
    m.add_argument('--source-b-env', default='HB_MARKET_SOURCE_B_URL')
    m.add_argument('--source-b-provider', choices=['coingecko','coinbase'], default='coinbase')
    m.add_argument('--out', required=True)
    pm=sub.add_parser('migrate-policy')
    pm.add_argument('--source',required=True);pm.add_argument('--out',required=True);pm.add_argument('--report',required=True)
    v = sub.add_parser('validate-policy')
    v.add_argument('--policy', required=True)
    sub.add_parser('doctor')
    args = parser.parse_args()
    now = int(time.time())
    if args.command == 'doctor':
        print(json.dumps(doctor(), indent=2)); return
    if args.command == 'validate-policy':
        print(json.dumps({'valid':True,'policy_sha256':digest(validate_policy(read_json(args.policy)))}, indent=2)); return
    if args.command == 'migrate-policy':
        if Path(args.out).exists() or Path(args.report).exists(): raise ValueError('migration output exists')
        newp,report=migrate_policy_v012(read_json(args.source));write_new(args.out,newp);write_new(args.report,report)
        print(json.dumps(report,indent=2));return
    if getattr(args, 'out', None) and Path(args.out).exists():
        raise ValueError('output exists; use a new filename')
    if args.command == 'market-collect':
        policy=validate_policy(read_json(args.policy))
        ua=os.environ.get(args.source_a_env); ub=os.environ.get(args.source_b_env)
        if not ua or not ub: raise ValueError('market source URL environment variable missing')
        result=market_collect([(args.source_a_provider,ua),(args.source_b_provider,ub)],policy,now)
    elif args.command == 'status':
        result = status_report(args.db, read_json(args.policy), read_json(args.market), now)
    elif args.command == 'collect':
        if args.max_age_seconds < 1:
            raise ValueError('max age must be positive')
        url = os.environ.get(args.workers_url_env)
        if not url:
            raise ValueError('worker URL environment variable missing')
        # Fetch before creating a new DB; unavailable APIs must not create empty identities.
        workers = fetch_json(url)
        pools = fetch_json(args.pool_url)
        # Retain a caller's configured age; do not relax health checks silently.
        now = int(time.time())
        if Path(args.db).exists():
            with closing(existing_database(args.db)):
                pass
        with closing(database(args.db)) as db:
            result = collect(db, workers, pools, now, args.max_age_seconds)
    else:
        policy = validate_policy(read_json(args.policy))
        with closing(existing_database(args.db)) as db:
            db.execute('BEGIN')
            result = recommend(db, policy, read_json(args.market), now)
    if getattr(args, 'out', None):
        write_new(args.out, result)
    if args.command == 'recommend':
        print('SHADOW_PLAN_WRITTEN no_worker_configuration_applied')
    else:
        print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, OverflowError, sqlite3.Error):
        # Never echo a URL, HTTP exception body, credential or input payload.
        raise SystemExit('STOP: invalid, unavailable or incomplete input; no worker configuration applied')
