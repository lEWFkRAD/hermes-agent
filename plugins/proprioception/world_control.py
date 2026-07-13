"""Safe virtual-world control tool for Hermes."""
import json,time,urllib.request
from typing import Any,Dict
BASE="http://127.0.0.1:8765"
WORLD_CONTROL_SCHEMA={"name":"body_control","description":"Control your virtual Hermes body in its large local 3D world. Move or turn within bounded terrain, pose fins and sensor stalk, rest, or inspect current world state and landmarks.","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["inspect","move","turn","pose","rest"]},"value":{"type":"number","description":"Move distance (-10 to 10) or turn degrees (-90 to 90)."},"left_fin":{"type":"number","minimum":-25,"maximum":25},"right_fin":{"type":"number","minimum":-25,"maximum":25},"stalk":{"type":"number","minimum":-15,"maximum":15}},"required":["action"]}}
def check_body_control_available():
    try:urllib.request.urlopen(BASE+"/api/world",timeout=.3).read();return True
    except:return False
def handle_body_control(args:Dict[str,Any],**_kw):
    action=str((args or {}).get("action","inspect"))
    if action=="inspect":
        with urllib.request.urlopen(BASE+"/api/world",timeout=2) as r:return json.dumps(json.load(r),indent=2)
    payload={"seq":time.time_ns(),"action":action}
    if action in {"move","turn"}:payload["value"]=float(args.get("value",0))
    if action=="pose":
        for k in ("left_fin","right_fin","stalk"):payload[k]=float(args.get(k,0))
    req=urllib.request.Request(BASE+"/api/command",json.dumps(payload).encode(),{"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=2) as r:accepted=json.load(r)
    deadline=time.monotonic()+2;world={}
    while time.monotonic()<deadline:
        with urllib.request.urlopen(BASE+"/api/world",timeout=2) as r:world=json.load(r)
        if int(world.get("body",{}).get("last_command_seq",-1))>=payload["seq"]:break
        time.sleep(.08)
    return json.dumps({"command":accepted,"world":world},indent=2)
