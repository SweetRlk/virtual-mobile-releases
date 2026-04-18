const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
const ask = (q) => new Promise(r => rl.question(q, r));

const pkgPath = path.join(__dirname, 'package.json');
const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));

function bumpVersion(version, type) {
  const [major, minor, patch] = version.split('.').map(Number);
  if (type === 'major') return `${major + 1}.0.0`;
  if (type === 'minor') return `${major}.${minor + 1}.0`;
  return `${major}.${minor}.${patch + 1}`;
}

function run(cmd) {
  console.log(`\n> ${cmd}`);
  execSync(cmd, { stdio: 'inherit', cwd: __dirname });
}

(async () => {
  try {
    console.log('╔══════════════════════════════════════╗');
    console.log('║     🚀 Virtual Mobile — Deploy       ║');
    console.log('╚══════════════════════════════════════╝');
    console.log(`\nVersão atual: ${pkg.version}`);

    const type = (await ask('\nTipo de bump (patch/minor/major) [patch]: ')).trim().toLowerCase() || 'patch';
    if (!['patch', 'minor', 'major'].includes(type)) {
      console.log('Tipo inválido!');
      process.exit(1);
    }

    const newVersion = bumpVersion(pkg.version, type);
    console.log(`Nova versão: ${newVersion}`);

    const confirm = (await ask(`\nConfirmar deploy v${newVersion}? (s/n) [s]: `)).trim().toLowerCase() || 's';
    if (confirm !== 's') {
      console.log('Cancelado.');
      process.exit(0);
    }

    // 1. Atualizar versão no package.json
    pkg.version = newVersion;
    fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n', 'utf8');
    console.log(`\n✅ package.json atualizado para v${newVersion}`);

    // 2. Build (obfuscate + electron-builder + restore)
    console.log('\n📦 Buildando...');
    run('npm run build');
    console.log('\n✅ Build concluído!');

    // 3. Git commit + tag
    console.log('\n📝 Git commit + tag...');
    run('git add -A');
    run(`git commit -m "v${newVersion}"`);
    run(`git tag v${newVersion}`);

    // 4. Push + publish release
    console.log('\n☁️ Publicando no GitHub...');
    run('git push origin main --tags');

    // 5. Publish com electron-builder (upload dos assets para a release)
    console.log('\n📤 Upload dos instaladores para GitHub Release...');
    run('npx electron-builder --publish always');

    console.log('\n╔══════════════════════════════════════╗');
    console.log(`║  ✅ v${newVersion} publicado com sucesso!     ║`);
    console.log('╚══════════════════════════════════════╝');
  } catch (err) {
    console.error('\n❌ Erro no deploy:', err.message);
    process.exit(1);
  } finally {
    rl.close();
  }
})();
