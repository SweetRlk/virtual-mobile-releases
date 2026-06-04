// Ponte de telemetria: lê do jogo e envia pro servidor Flask via Socket.IO
const getTelemetryData = require('./telemetry').getData;
const { io } = require('socket.io-client');
const readline = require('readline');

const SERVER_URL = process.env.SERVER_URL || 'https://sweetrlk.com.br';
const BRIDGE_TOKEN = process.env.BRIDGE_TOKEN || 'bridge-secret-token';

let currentGame = 'ETS2';
let socket = null;
let connected = false;
let interval = null;

function connect() {
  console.log(`[Bridge] Conectando em ${SERVER_URL}...`);
  socket = io(SERVER_URL, {
    reconnection: true,
    reconnectionDelay: 2000,
  });

  socket.on('connect', () => {
    connected = true;
    console.log('[Bridge] Conectado. Registrando...');
    socket.emit('bridge-hello', { token: BRIDGE_TOKEN });
  });

  socket.on('disconnect', (reason) => {
    connected = false;
    console.log('[Bridge] Desconectado:', reason);
  });

  socket.on('connect_error', (err) => {
    console.log('[Bridge] Erro de conexão:', err.message);
  });
}

function startPolling() {
  if (interval) clearInterval(interval);
  interval = setInterval(() => {
    if (!connected) return;
    try {
      const telem = getTelemetryData(() => currentGame);
      if (telem) {
        socket.emit('telemetry', telem);
      }
    } catch (_) {}
  }, 100);
}

function main() {
  connect();
  startPolling();

  console.log('[Bridge] Telemetry Bridge rodando.');
  console.log('[Bridge] Pressione Ctrl+C para sair.');

  const rl = readline.createInterface({ input: process.stdin });
  rl.on('line', (line) => {
    if (line.trim() === 'q') {
      console.log('[Bridge] Encerrando...');
      if (interval) clearInterval(interval);
      if (socket) socket.disconnect();
      process.exit(0);
    }
  });
}

main();
