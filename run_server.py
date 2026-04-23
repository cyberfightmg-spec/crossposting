#!/usr/bin/env python3
import json, sys, os, time
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, ".")
os.chdir("/root/crossposting")

# Read the SDK JS
with open("node_modules/armcloud-rtc/dist/index.es.js", "r") as f:
    SDK_JS = f.read()

# Pre-fetch token at startup
from integrations.vmos.client import get_client
print("Getting token...")
_client = get_client()
_token = _client.get_sts_token("AC32010940924")["data"]["token"]
print(f"Token: {_token[:20]}...")

HTML = f"""<html><body style="background:#111;color:#fff;font-family:sans-serif;text-align:center;padding:50px">
<h1>VMOS Cloud - TenChat Control</h1>
<iframe id="p" style="width:360px;height:640px;border:2px solid #4CAF50;border-radius:20px"></iframe>
<br><br>
<button onclick="connect()" style="background:#4CAF50;color:white;padding:15px 30px;border:none;border-radius:8px;font-size:16px">Connect to Cloud Phone</button>
<div id="l" style="background:#222;color:#0f0;padding:15px;height:150px;overflow:auto;font-family:monospace"></div>
<script type="module">
{SDK_JS}
let ArmcloudEngine = window.ArmcloudEngine;
let c = null;
function log(m){{ document.getElementById("l").innerHTML = "<div>"+m+"</div>" + document.getElementById("l").innerHTML; }}
window.connect = async function(){{
  log("Connecting...");
  c = new ArmcloudEngine({{
    baseUrl: "https://openapi-hk.armcloud.net",
    token: "{_token}",
    deviceInfo: {{padCode: "AC32010940924", userId: "web"+Date.now(), videoStream:{{resolution:12}}}},
    viewId: "p",
    callbacks: {{
      onInit: e => log("Init: "+e.msg),
      onConnectSuccess: () => log("Connected!"),
      onConnectFail: e => log("Error: "+e.msg)
    }}
  }});
}};
</script>
</body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())
    
    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"token": _token}).encode())

print("Starting server on http://0.0.0.0:8888")
HTTPServer(("0.0.0.0", 8888), H).serve_forever()