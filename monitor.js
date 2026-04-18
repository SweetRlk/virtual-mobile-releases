const fs = require('fs');
const path = require('path');

function findLogFile() {
  const paths = [
    "C:/Users/Usuario/Documents/Euro Truck Simulator 2/game.log.txt",
    process.env.APPDATA + "/Euro Truck Simulator 2/game.log.txt",
    path.join(process.env.USERPROFILE, "Documents/Euro Truck Simulator 2/game.log.txt")
  ];

  for (const p of paths) {
    try {
      if (fs.existsSync(p)) {
        console.log("✅ Log encontrado:", p);
        return p;
      }
    } catch (e) {}
  }

  console.warn("⚠️ Nenhum arquivo de log encontrado nas localizações padrão");
  return paths[0];
}

const logPath = findLogFile();
let lastSize = null, tail = '';

function monitor(win) {
  console.log("📝 Monitor iniciado. Procurando pedágios...");

  setInterval(() => {
    try {
      if (!fs.existsSync(logPath)) return;

      const stats = fs.statSync(logPath);

      if (lastSize === null) {
        lastSize = stats.size;
        return;
      }

      if (stats.size < lastSize) {
        lastSize = stats.size;
        tail = '';
        return;
      }

      if (stats.size > lastSize) {
        const stream = fs.createReadStream(logPath, {
          start: lastSize,
          end: stats.size - 1,
          encoding: 'utf8'
        });

        let data = '';
        stream.on('data', chunk => {
          data += chunk;
        });

        stream.on('end', () => {
          const combined = tail + data;
          const lines = combined.split(/\r?\n/);
          tail = lines.pop();

          lines.forEach(line => {
            if (/\[tollgate\]\s+Activated/i.test(line)) {
              console.log("🚧 Pedágio detectado:", line.trim().substring(0, 64));
              win.webContents.send("pedagio");
            }
          });
        });

        lastSize = stats.size;
      }
    } catch (e) {}
  }, 500);
}

module.exports = monitor;
