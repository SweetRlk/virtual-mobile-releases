const fs = require('fs');
const path = require('path');

const BACKUP_DIR = path.join(__dirname, '.backup');
const FILES = ['main.js', 'telemetry.js', 'overlay.html'];

if (!fs.existsSync(BACKUP_DIR)) {
  console.log('Nenhum backup encontrado.');
  process.exit(0);
}

FILES.forEach(file => {
  const backupPath = path.join(BACKUP_DIR, file);
  if (fs.existsSync(backupPath)) {
    fs.copyFileSync(backupPath, path.join(__dirname, file));
    console.log(`  ♻️ ${file} restaurado`);
  }
});

// Remove backup dir
fs.rmSync(BACKUP_DIR, { recursive: true, force: true });
console.log('♻️ Código original restaurado!');
