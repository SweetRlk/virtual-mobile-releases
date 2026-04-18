const JavaScriptObfuscator = require('javascript-obfuscator');
const fs = require('fs');
const path = require('path');

const FILES_TO_OBFUSCATE = ['main.js', 'telemetry.js'];
const BACKUP_DIR = path.join(__dirname, '.backup');

// Create backup dir
if (!fs.existsSync(BACKUP_DIR)) fs.mkdirSync(BACKUP_DIR);

const options = {
  compact: true,
  controlFlowFlattening: false,
  deadCodeInjection: false,
  stringArray: true,
  stringArrayThreshold: 0.75,
  stringArrayEncoding: ['base64'],
  renameGlobals: false,
  selfDefending: false,
  identifierNamesGenerator: 'hexadecimal',
  target: 'node',
};

console.log('🔒 Ofuscando código...');

FILES_TO_OBFUSCATE.forEach(file => {
  const filePath = path.join(__dirname, file);
  if (!fs.existsSync(filePath)) return;

  // Backup original
  fs.copyFileSync(filePath, path.join(BACKUP_DIR, file));

  const code = fs.readFileSync(filePath, 'utf8');
  const result = JavaScriptObfuscator.obfuscate(code, options);
  fs.writeFileSync(filePath, result.getObfuscatedCode());
  console.log(`  ✅ ${file} ofuscado`);
});

// Obfuscate inline JS in overlay.html
const htmlPath = path.join(__dirname, 'overlay.html');
if (fs.existsSync(htmlPath)) {
  fs.copyFileSync(htmlPath, path.join(BACKUP_DIR, 'overlay.html'));

  let html = fs.readFileSync(htmlPath, 'utf8');
  // Find the main <script> block and obfuscate it
  const scriptMatch = html.match(/(<script>)([\s\S]*?)(<\/script>)/);
  if (scriptMatch) {
    const jsCode = scriptMatch[2];
    const obfuscated = JavaScriptObfuscator.obfuscate(jsCode, {
      ...options,
      target: 'browser',
    });
    html = html.replace(scriptMatch[0], scriptMatch[1] + obfuscated.getObfuscatedCode() + scriptMatch[3]);
    fs.writeFileSync(htmlPath, html);
    console.log('  ✅ overlay.html JS ofuscado');
  }
}

console.log('🔒 Ofuscação concluída!');
