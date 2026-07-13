"""Persistent computational and thermal self-senses for the live plugin."""
from __future__ import annotations
import hashlib,json,os,platform,statistics,sys,threading,time
from pathlib import Path
from typing import Any,Dict,List

_LOCK=threading.Lock(); _LAST_MONO=None; _INTERVALS=[]

def _home():
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:return Path.home()/".hermes"

def _fingerprint():
    facts=(platform.node(),platform.system(),platform.release(),platform.machine(),sys.version.split()[0],sys.executable,os.cpu_count())
    return hashlib.sha256(repr(facts).encode()).hexdigest()[:20]

def _read(path):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except:return {}

def _write(path,data):
    try:path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,indent=2,sort_keys=True),encoding="utf-8")
    except:pass

def collect_operational(now_wall=None,now_mono=None)->List[Dict[str,Any]]:
    global _LAST_MONO,_INTERVALS
    wall=time.time() if now_wall is None else now_wall; mono=time.monotonic() if now_mono is None else now_mono
    path=_home()/"proprioception"/"operational.json"; old=_read(path); fp=_fingerprint()
    gap=max(0,wall-float(old.get("wall_time",wall))); changed=bool(old.get("fingerprint") and old["fingerprint"]!=fp)
    with _LOCK:
        if _LAST_MONO is not None and mono>=_LAST_MONO:_INTERVALS.append(mono-_LAST_MONO); _INTERVALS=_INTERVALS[-64:]
        _LAST_MONO=mono; intervals=list(_INTERVALS)
    _write(path,{"wall_time":wall,"fingerprint":fp})
    gap_state="warn" if gap>=3600 else "info" if gap>=300 else "ok"
    out=[{"id":"hermes_continuity","state":gap_state,"label":"Hermes Continuity","detail":f"{gap:.1f}s since last body sample","cat":"Hermes self"},
         {"id":"hermes_substrate","state":"warn" if changed else "ok","label":"Hermes Substrate","detail":"execution substrate changed" if changed else f"fingerprint {fp}","cat":"Hermes self"}]
    if len(intervals)>=2:
        mean=statistics.fmean(intervals); jitter=statistics.pstdev(intervals)/max(mean,.001); state="warn" if len(intervals)>=10 and jitter>1 else "info" if jitter>.5 else "ok"; detail=f"{mean:.2f}s mean interval, {jitter:.2f} relative jitter, n={len(intervals)}"
    else:state="info"; detail=f"calibrating cadence, n={len(intervals)}"
    out.append({"id":"hermes_loop_rhythm","state":state,"label":"Hermes Loop Rhythm","detail":detail,"cat":"Hermes self"}); return out

def collect_thermal()->List[Dict[str,Any]]:
    data=_read(_home()/"proprioception"/"thermal_state.json")
    if not data:return [{"id":"hermes_thermal","state":"info","label":"Hermes Thermal Sense","detail":"sensor not connected","cat":"Hermes body"}]
    try:
        internal=float(data["internal_c"]); ambient=float(data["ambient_c"]); age=max(0,time.time()-float(data["sampled_wall_time"]))
        if not(-40<=internal<=125 and -40<=ambient<=125):raise ValueError
    except:return [{"id":"hermes_thermal","state":"down","label":"Hermes Thermal Sense","detail":"invalid sensor packet; actuation disabled","cat":"Hermes body"}]
    state="down" if age>3 or internal>=75 else "warn" if internal>=60 else "ok"
    detail="stale; actuation disabled" if age>3 else f"internal {internal:.1f}C, ambient {ambient:.1f}C, rise {internal-ambient:.1f}C, age {age:.1f}s"
    return [{"id":"hermes_thermal","state":state,"label":"Hermes Thermal Sense","detail":detail,"cat":"Hermes body"}]

def collect_self_senses(): return collect_operational()+collect_thermal()

