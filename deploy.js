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

    // 3. Git commit + tag (repo privado — código)
    console.log('\n📝 Git commit + tag...');
    run('git add -A');
    run(`git commit -m "v${newVersion}"`);
    run(`git tag -f v${newVersion}`);

    // 4. Push código pro repo privado
    console.log('\n☁️ Push pro repo privado...');
    run('git push origin main');
    run(`git push origin v${newVersion} --force`);

    // 5. Criar release no repo público e fazer upload do instalador
    console.log('\n📤 Criando release no repo público...');
    const distDir = path.join(__dirname, 'dist');
    const setupExe = `Virtual-Mobile-Setup-${newVersion}.exe`;
    const blockmap = `Virtual-Mobile-Setup-${newVersion}.exe.blockmap`;
    const latestYml = 'latest.yml';
    
    const assets = [setupExe, blockmap, latestYml]
      .map(f => path.join(distDir, f))
      .filter(f => fs.existsSync(f));
    
    if (assets.length === 0) {
      throw new Error('Nenhum arquivo de instalação encontrado em dist/');
    }
    
    const assetFlags = assets.map(f => `"${f}"`).join(' ');
    run(`gh release create v${newVersion} ${assetFlags} --repo SweetRlk/virtual-mobile-releases --title "v${newVersion}" --notes "Virtual Mobile v${newVersion}"`);

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
