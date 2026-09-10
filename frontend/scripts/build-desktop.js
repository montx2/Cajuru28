/**
 * Build frontend para desktop (standalone)
 * 
 * Para desktop, usamos o mesmo output standalone do Docker, mas com API_URL apontando para localhost:8000
 * O Electron vai iniciar o server Next.js standalone (server.js) em localhost:3000
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const frontendDir = path.join(__dirname, '..');
const originalConfig = path.join(frontendDir, 'next.config.mjs');
const desktopConfig = path.join(frontendDir, 'next.config.desktop.mjs');
const backupConfig = path.join(frontendDir, 'next.config.mjs.backup');

console.log('=== Build Frontend Desktop ===');

if (!fs.existsSync(desktopConfig)) {
  console.error('next.config.desktop.mjs não encontrado!');
  process.exit(1);
}

// Backup original
if (fs.existsSync(originalConfig)) {
  fs.copyFileSync(originalConfig, backupConfig);
  console.log('Backup do config original criado');
}

// Copiar desktop config para original
fs.copyFileSync(desktopConfig, originalConfig);
console.log('Usando config desktop para build');

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    console.log(`> ${cmd} ${args.join(' ')}`);
    const proc = spawn(cmd, args, {
      cwd: frontendDir,
      stdio: 'inherit',
      shell: process.platform === 'win32',
      env: {
        ...process.env,
        NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
      },
    });
    proc.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`Exit code ${code}`));
    });
    proc.on('error', reject);
  });
}

async function build() {
  try {
    await run('npx', ['next', 'build']);
    console.log('✓ Frontend desktop build concluído');
    console.log('  Standalone em frontend/.next/standalone/');
    console.log('  Static em frontend/.next/static/');
    
    // Verificar arquivos
    const standalonePath = path.join(frontendDir, '.next/standalone');
    if (fs.existsSync(standalonePath)) {
      console.log(`✓ Standalone encontrado: ${standalonePath}`);
    }
  } catch (e) {
    console.error('✗ Erro no build:', e);
    process.exitCode = 1;
  } finally {
    // Restaurar original
    if (fs.existsSync(backupConfig)) {
      fs.copyFileSync(backupConfig, originalConfig);
      fs.unlinkSync(backupConfig);
      console.log('Config original restaurado');
    }
  }
}

build();
