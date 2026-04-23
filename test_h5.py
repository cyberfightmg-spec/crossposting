const { ArmcloudEngine } = require('armcloud-rtc');
const readline = require('readline');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

const padCode = 'AC32010940924';
let armCloud = null;

async function main() {
  console.log('=== VMOS Cloud H5 SDK Test ===\n');
  
  const { VmosClient } = require('./integrations/vmos/client');
  const client = new VmosClient();
  
  console.log('1. Getting STS token...');
  const tokenResult = await client.get_sts_token(padCode);
  const token = tokenResult.data?.token;
  
  if (!token) {
    console.error('Failed to get token:', tokenResult);
    process.exit(1);
  }
  console.log('Token received:', token.substring(0, 20) + '...\n');
  
  console.log('2. Starting H5 SDK...');
  
  armCloud = new ArmcloudEngine({
    baseUrl: 'https://openapi-hk.armcloud.net',
    token: token,
    deviceInfo: {
      padCode: padCode,
      userId: 'test-user-' + Date.now(),
      videoStream: {
        resolution: 12,
        frameRate: 15,
        bitrate: 4
      },
      mediaType: 3,
      rotateType: 0,
      keyboard: 'pad'
    },
    viewId: 'phoneBox',
    callbacks: {
      onInit: ({ code, msg }) => {
        console.log('   Init:', code, msg);
        if (code === 0) {
          armCloud.start();
        }
      },
      onConnectSuccess: () => {
        console.log('   Connected! Streaming started.\n');
        console.log('Controls:');
        console.log('  click x y  - click at position');
        console.log('  text msg   - input text');
        console.log('  swipe x1 y1 x2 y2 - swipe');
        console.log('  screenshot - take screenshot');
        console.log('  quit       - exit\n');
      },
      onConnectFail: ({ code, msg }) => {
        console.log('   Failed:', code, msg);
      },
      onRenderedFirstFrame: () => {
        console.log('   First frame rendered!');
      }
    }
  });
}

function handleInput(line) {
  const parts = line.trim().split(' ');
  const cmd = parts[0];
  
  if (cmd === 'quit') {
    if (armCloud) armCloud.stop();
    process.exit(0);
  }
  else if (cmd === 'click' && parts.length >= 3) {
    const x = parseInt(parts[1]);
    const y = parseInt(parts[2]);
    console.log(`Clicking at ${x}, ${y}...`);
    // H5 SDK doesn't have direct click, need to use cloud phone API
  }
  else if (cmd === 'screenshot') {
    console.log('Taking screenshot...');
  }
  else {
    console.log('Unknown command. Try: click x y, text msg, swipe x1 y1 x2 y2, screenshot, quit');
  }
  
  rl.question('> ', handleInput);
}

main().catch(console.error);
rl.on('line', handleInput);