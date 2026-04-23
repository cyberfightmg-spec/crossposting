const http = require('http');
const { ArmcloudEngine } = require('armcloud-rtc');

const PAD_CODE = 'AC32010940924';
const PORT = 8080;

let armCloud = null;
let html = '';

function serveHtml() {
  return `
<!DOCTYPE html>
<html>
<head>
  <title>VMOS Cloud - TenChat Control</title>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { margin: 0; padding: 20px; font-family: Arial; background: #1a1a1a; color: #fff; }
    #phoneBox { width: 360px; height: 640px; margin: 0 auto; border: 2px solid #333; border-radius: 20px; overflow: hidden; background: #000; }
    .controls { text-align: center; margin: 20px 0; }
    button { padding: 10px 20px; margin: 5px; font-size: 14px; cursor: pointer; background: #4CAF50; color: white; border: none; border-radius: 5px; }
    button.stop { background: #f44336; }
    button.action { background: #2196F3; }
    #log { width: 100%; height: 150px; background: #222; color: #0f0; font-family: monospace; font-size: 12px; padding: 10px; box-sizing: border-box; overflow: auto; }
    .status { text-align: center; padding: 10px; background: #333; margin-bottom: 10px; }
  </style>
</head>
<body>
  <div class="status" id="status">Initializing...</div>
  <div id="phoneBox"></div>
  <div class="controls">
    <button class="action" onclick="doClick(180, 300)">Create Post</button>
    <button class="action" onclick="doClick(180, 500)">Input Text</button>
    <button class="action" onclick="doSwipe(180, 500, 180, 200)">Scroll Down</button>
    <button class="action" onclick="takeScreenshot()">Screenshot</button>
    <button class="stop" onclick="location.reload()">Restart</button>
  </div>
  <div id="log"></div>
  <script>
    function log(msg) { document.getElementById('log').innerHTML += '<div>' + msg + '</div>'; }
    function setStatus(msg) { document.getElementById('status').innerHTML = msg; }
    
    function doClick(x, y) { 
      log('Click at ' + x + ',' + y + ' - Use cloud UI for now'); 
    }
    function doSwipe(x1, y1, x2, y2) { 
      log('Swipe from ' + x1 + ',' + y1 + ' to ' + x2 + ',' + y2); 
    }
    function takeScreenshot() { log('Screenshot - Use cloud UI'); }
  </script>
</body>
</html>
  `;
}

async function initVMOS() {
  console.log('Loading VMOS client...');
  
  // Dynamic import for Python
  const { spawn } = require('child_process');
  const py = spawn('python3', ['-c', `
import sys
sys.path.insert(0, '.')
from integrations.vmos.client import get_client
client = get_client()
result = client.get_sts_token('${PAD_CODE}')
print(result['data']['token'])
  `]);
  
  let token = '';
  py.stdout.on('data', (data) => { token += data; });
  py.stderr.on('data', (data) => { console.log('Python:', data); });
  
  py.on('close', (code) => {
    if (code !== 0) {
      setStatus('Failed to get token');
      return;
    }
    token = token.trim();
    console.log('Token:', token.substring(0, 20) + '...');
    
    setStatus('Connecting to cloud phone...');
    
    armCloud = new ArmcloudEngine({
      baseUrl: 'https://openapi-hk.armcloud.net',
      token: token,
      deviceInfo: {
        padCode: PAD_CODE,
        userId: 'web-control-' + Date.now(),
        videoStream: { resolution: 12, frameRate: 15, bitrate: 3 },
        mediaType: 3,
        rotateType: 0,
        keyboard: 'pad'
      },
      viewId: 'phoneBox',
      callbacks: {
        onInit: ({ code, msg }) => {
          log('Init: ' + code + ' ' + msg);
          if (code === 0) armCloud.start();
        },
        onConnectSuccess: () => {
          setStatus('Connected! Device: ' + PAD_CODE);
          log('Connected to cloud phone!');
        },
        onConnectFail: ({ code, msg }) => {
          setStatus('Failed: ' + msg);
          log('Failed: ' + code + ' ' + msg);
        },
        onRenderedFirstFrame: () => {
          log('First frame rendered!');
        }
      }
    });
  });
}

const server = http.createServer((req, res) => {
  if (req.url === '/') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(html);
  } else {
    res.writeHead(404);
    res.end();
  }
});

server.listen(PORT, () => {
  console.log(`Server: http://localhost:${PORT}`);
  console.log('VMOS Cloud Control Panel');
  html = serveHtml();
  initVMOS();
});