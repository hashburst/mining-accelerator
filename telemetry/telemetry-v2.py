#!/usr/bin/env python3
"""HashBurst Mining Telemetry v2 - read-only, portable schema with Linux/cgroup-v2 adapter."""
import json,os,platform,re,subprocess,time
def out(a):
 return subprocess.run(a,text=True,capture_output=True,timeout=5).stdout.strip()
def unit_pid(u):
 try:return int(out(["systemctl","show",u,"-p","MainPID","--value"]) or 0)
 except:return 0
def unit_state(u): return out(["systemctl","is-active",u]) or "unknown"
def cgroup(pid):
 if pid<=0:return None
 try:
  for line in open(f"/proc/{pid}/cgroup"):
   p=line.rstrip().split(":",2)
   if len(p)==3 and p[0]=="0": return p[2]
 except OSError: pass
 return None
def usage_usec(cg):
 if not cg:return None
 p="/sys/fs/cgroup"+cg+"/cpu.stat"
 try:
  for line in open(p):
   k,v=line.split()
   if k=="usage_usec":return int(v)
 except OSError:pass
 return None
def interval_cpu(pid,seconds=2.0):
 cg=cgroup(pid); a=usage_usec(cg)
 if a is None:return {"quality":"unavailable","cores":None,"host_percent":None,"cgroup":cg}
 t=time.monotonic();time.sleep(seconds);b=usage_usec(cg);dt=time.monotonic()-t
 if b is None or dt<=0:return {"quality":"unavailable","cores":None,"host_percent":None,"cgroup":cg}
 cores=(b-a)/(dt*1_000_000); n=os.cpu_count() or 1
 return {"quality":"systemd-cgroup-v2-interval","cores":round(cores,4),"host_percent":round(cores/n*100,4),"cgroup":cg,"interval_seconds":round(dt,3)}
def miner_pid():
 try:return int(out(["pgrep","-xo","cpuminer"]) or 0)
 except:return 0
def parse_shares():
 candidates=["/var/log/cpuminer.log","/var/log/hashburst/cpuminer.log"]
 for p in candidates:
  if not os.path.isfile(p):continue
  try:
   st=os.stat(p); lines=open(p,errors="replace").read().splitlines()[-5000:]
   acc=sum(bool(re.search(r"\baccepted\b",x,re.I)) for x in lines)
   rej=sum(bool(re.search(r"\brejected\b",x,re.I)) for x in lines)
   rates=[]
   for x in lines:
    m=re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kMGT]?H)/s",x,re.I)
    if m:rates.append({"value":float(m.group(1)),"unit":m.group(2)+"/s"})
   return {"quality":"log-snapshot-proxy","source":p,"file_inode":st.st_ino,"file_size":st.st_size,
           "accepted_events_snapshot":acc,"rejected_events_snapshot":rej,
           "latest_hashrate":rates[-1] if rates else None}
  except OSError:pass
 return {"quality":"unavailable","source":None,"accepted_events_snapshot":None,"rejected_events_snapshot":None,"latest_hashrate":None}
def role(name,state):return {"unit":name,"state":state,"main_pid":unit_pid(name)}
hvm="hashburst-hvm-testnet.service";tep="hashburst-tep.service";mp=miner_pid()
hs=role(hvm,unit_state(hvm));ts=role(tep,unit_state(tep))
hs["cpu"]=interval_cpu(hs["main_pid"]);ts["cpu"]=interval_cpu(ts["main_pid"])
m={"process":"cpuminer","pid":mp,"cpu":interval_cpu(mp),"shares":parse_shares()}
doc={"schema":"hashburst-mining-telemetry-v2","ts":time.time(),"node":out(["hostname"]),
 "platform":{"os":platform.system().lower(),"release":platform.release(),"arch":platform.machine(),
             "adapter":"linux-cgroup-v2","supported_node_classes":["vps","raspberry","desktop-linux","rig","hpc"]},
 "roles":{"full_node":True,"validator":hs["state"]=="active","tep":ts["state"]=="active","miner":mp>0},
 "capacity":{"logical_cpus":os.cpu_count(),"load1":float(open("/proc/loadavg").read().split()[0])},
 "services":{"hvm":hs,"tep":ts},"mining":m,
 "energy":{"quality":"cpu-time-proxy","joules":None,"co2e_g":None,"claim":"not_measured"}}
print(json.dumps(doc,sort_keys=True,separators=(",",":")))
