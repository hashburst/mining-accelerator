#!/usr/bin/env python3
"""Compare canary/control Mining Telemetry v2 snapshots without inventing unavailable metrics."""
import hashlib,json,sys
if len(sys.argv)!=5:raise SystemExit("usage: compare-telemetry-v2.py canary.before canary.after control.before control.after")
cb,ca,xb,xa=[json.load(open(p)) for p in sys.argv[1:]]
for d in (cb,ca,xb,xa):
 if d.get("schema")!="hashburst-mining-telemetry-v2":raise SystemExit("bad telemetry schema")
def n(d,path):
 for k in path:d=d.get(k,{}) if isinstance(d,dict) else None
 return d if isinstance(d,(int,float)) else None
def diff(a,b,path):
 x,y=n(a,path),n(b,path);return None if x is None or y is None else y-x
def node(a,b):
 return {"load_delta":diff(a,b,["capacity","load1"]),
 "miner_core_delta":diff(a,b,["mining","cpu","cores"]),
 "hvm_core_delta":diff(a,b,["services","hvm","cpu","cores"]),
 "tep_core_delta":diff(a,b,["services","tep","cpu","cores"]),
 "miner_pid_continuity":n(a,["mining","pid"])==n(b,["mining","pid"]) and n(a,["mining","pid"]) not in (None,0),
 "hvm_active":b["services"]["hvm"]["state"]=="active","tep_active":b["services"]["tep"]["state"]=="active",
 "shares_quality":b["mining"]["shares"]["quality"],"latest_hashrate":b["mining"]["shares"]["latest_hashrate"]}
r={"schema":"hashburst-mining-efficiency-comparison-v1","canary":node(cb,ca),"control":node(xb,xa)}
r["difference_in_differences_load"]=None if r["canary"]["load_delta"] is None or r["control"]["load_delta"] is None else r["canary"]["load_delta"]-r["control"]["load_delta"]
r["throughput_measured"]=r["canary"]["latest_hashrate"] is not None
r["share_acceptance_measured"]=r["canary"]["shares_quality"]!="unavailable"
r["energy_claim"]="proxy_only"
body=json.dumps(r,sort_keys=True,separators=(",",":"));r["comparison_sha256"]=hashlib.sha256(body.encode()).hexdigest()
print(json.dumps(r,sort_keys=True,separators=(",",":")))
