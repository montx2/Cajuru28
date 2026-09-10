/**
 * Build backend Python para executável usando PyInstaller
 * 
 * Gera um .exe (Windows) ou binário (Linux/Mac) que roda sem precisar de Python instalado
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const backendDir = path.join(__dirname, '../../backend');
const distDir = path.join(backendDir, 'dist');
const isWin = process.platform === 'win32';

console.log('=== Build Backend NotasFlow ===');
console.log(`Backend dir: ${backendDir}`);
console.log(`Platform: ${process.platform}`);

function runCommand(cmd, args, cwd) {
  return new Promise((resolve, reject) => {
    console.log(`\n> ${cmd} ${args.join(' ')}`);
    const proc = spawn(cmd, args, {
      cwd,
      stdio: 'inherit',
      shell: isWin,
    });
    proc.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`Command failed with code ${code}`));
    });
    proc.on('error', reject);
  });
}

async function build() {
  try {
    // Verificar se PyInstaller está instalado
    try {
      await runCommand('pyinstaller', ['--version'], backendDir);
    } catch (e) {
      console.log('PyInstaller não encontrado, instalando...');
      await runCommand('pip', ['install', 'pyinstaller'], backendDir);
    }

    // Criar spec file se não existir
    const specContent = `
# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

block_cipher = None

# Coletar todos os arquivos necessários
backend_path = Path(SPECPATH).parent

a = Analysis(
    [os.path.join(str(backend_path), 'app', 'desktop_main.py')],
    pathex=[str(backend_path)],
    binaries=[],
    datas=[
        # Incluir templates, etc se necessário
        # (os.path.join(str(backend_path), 'app', 'templates'), 'app/templates'),
    ],
    hiddenimports=[
        'app.main',
        'app.desktop_main',
        'app.models',
        'app.schemas',
        'app.db.base',
        'app.db.session',
        'app.db.migracoes',
        'app.api.routers.auth',
        'app.api.routers.empresas',
        'app.api.routers.certificados',
        'app.api.routers.documentos',
        'app.api.routers.importacoes',
        'app.core.config',
        'app.core.security',
        'app.core.vault',
        'app.services.fila',
        'app.services.sincronizacao',
        'app.services.certificados',
        'app.services.mtls',
        'app.services.periodo',
        'app.services.importadores.base',
        'app.services.importadores.nfse_adn',
        'app.services.importadores.nfe_sefaz',
        'app.services.importadores.cte_sefaz',
        'app.services.importadores.eventos',
        'app.services.importadores._distribuicao_dfe',
        'app.worker.executor',
        'app.worker.celery_app',
        'app.bootstrap',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'sqlalchemy',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.postgresql',
        'cryptography',
        'cryptography.fernet',
        'jose',
        'passlib',
        'bcrypt',
        'httpx',
        'lxml',
        'dateutil',
        'OpenSSL',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='notasflow-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Manter console para logs (pode ser False para ocultar)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# Para modo diretório (mais rápido para iniciar, mas mais arquivos)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='notasflow-backend',
)
`;

    const specPath = path.join(backendDir, 'notasflow-backend.spec');
    if (!fs.existsSync(specPath)) {
      fs.writeFileSync(specPath, specContent, 'utf8');
      console.log(`Spec file criado: ${specPath}`);
    }

    // Limpar dist anterior
    if (fs.existsSync(distDir)) {
      console.log('Limpando dist anterior...');
      fs.rmSync(distDir, { recursive: true, force: true });
    }

    // Build com PyInstaller
    console.log('\n=== Iniciando PyInstaller ===');
    const args = [
      '--noconfirm',
      '--clean',
      '--log-level=INFO',
      specPath,
    ];

    await runCommand('pyinstaller', args, backendDir);

    console.log('\n=== Build concluído ===');
    const exePath = path.join(distDir, 'notasflow-backend', isWin ? 'notasflow-backend.exe' : 'notasflow-backend');
    const exePath2 = path.join(distDir, isWin ? 'notasflow-backend.exe' : 'notasflow-backend');
    
    if (fs.existsSync(exePath)) {
      console.log(`✓ Executável: ${exePath}`);
      const stats = fs.statSync(exePath);
      console.log(`  Tamanho: ${(stats.size / 1024 / 1024).toFixed(1)} MB`);
    } else if (fs.existsSync(exePath2)) {
      console.log(`✓ Executável: ${exePath2}`);
      const stats = fs.statSync(exePath2);
      console.log(`  Tamanho: ${(stats.size / 1024 / 1024).toFixed(1)} MB`);
    } else {
      console.log('Arquivos em dist:');
      if (fs.existsSync(distDir)) {
        const files = fs.readdirSync(distDir, { recursive: true });
        console.log(files.slice(0, 20));
      }
    }

    console.log('\nPara testar o backend:');
    console.log(`  cd ${backendDir}`);
    console.log(`  ./dist/notasflow-backend/${isWin ? 'notasflow-backend.exe' : 'notasflow-backend'}`);

  } catch (e) {
    console.error('\n✗ Erro no build:', e);
    process.exit(1);
  }
}

build();
