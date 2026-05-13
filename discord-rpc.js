const DiscordRPC = require('discord-rpc');
const clientId = '1503911863858233525';

let rpc = null;
let connected = false;
let lastPresence = null;
let reconnectTimer = null;
let startTime = Date.now();

function connect() {
  if (connected || rpc) return;
  try {
    rpc = new DiscordRPC.Client({ transport: 'ipc' });
    rpc.on('ready', () => {
      connected = true;
      console.log('[Discord RPC] Conectado');
      setPresence({
        details: 'Virtual Mobile',
        state: 'Iniciando...',
        startTimestamp: startTime,
        largeImageKey: "gg",
        largeImageText: 'Virtual Mobile',
        instance: false
      });
    });
    rpc.on('disconnected', () => {
      connected = false;
      rpc = null;
      scheduleReconnect();
    });
    rpc.login({ clientId }).catch(() => {
      rpc = null;
      scheduleReconnect();
    });
  } catch (_) {
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, 60000);
}

function setPresence(presence) {
  if (!connected || !rpc) return;
  const key = JSON.stringify(presence);
  if (key === lastPresence) return;
  lastPresence = key;
  try { rpc.setActivity(presence); } catch (_) {}
}

function updateTelemetry(data) {
  if (!connected) return;
  if (!data) {
    setPresence({
      details: 'Virtual Mobile',
      state: 'Aguardando jogo...',
      startTimestamp: startTime,
      largeImageKey: "gg",
      largeImageText: 'Virtual Mobile',
      instance: false
    });
    return;
  }
  const game = data.game || 'ETS2';
  const speed = data.speed || 0;
  const cargo = data.cargo || '';
  const citySrc = data.citySrc || '';
  const cityDst = data.cityDst || '';
  const onJob = data.onJob;

  let state = `${game} | ${speed} km/h`;
  if (data.fuelRange !== undefined && data.fuelCapacity > 0) {
    state += ` | ${data.fuel}L/${data.fuelCapacity}L`;
  }

  let details = `🚛 ${game}`;
  if (onJob && cargo) {
    details = `📦 ${cargo}`;
    if (citySrc && cityDst) {
      details += ` — ${citySrc} → ${cityDst}`;
    }
  } else if (cargo) {
    details = `📦 ${cargo}`;
  }

  setPresence({
    details: details,
    state: state,
    startTimestamp: startTime,
    largeImageKey: "gg",
    largeImageText: 'Virtual Mobile',
    buttons: [
      { label: 'Acessar Site', url: 'https://sweetrlk.com.br' }
    ],
    instance: false
  });
}

function destroy() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  if (rpc) {
    try { rpc.clearActivity(); } catch (_) {}
    try { rpc.destroy(); } catch (_) {}
    rpc = null;
  }
  connected = false;
}

module.exports = { connect, updateTelemetry, destroy };
