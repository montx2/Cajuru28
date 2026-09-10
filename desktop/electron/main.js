/**
 * NotasFlow Desktop - Main Process
 * 
 * Baseado nas melhores práticas de:
 * - https://github.com/AlanSynn/vue-tauri-fastapi-sidecar-template
 * - https://github.com/fudanglp/tauri-fastapi-full-stack-template
 * - https://medium.com/@shakeef.rakin321/electron-react-fastapi-template-for-cross-platform-desktop-apps-cf31d56c470c
 * 
 * Arquitetura:
 * - Electron cria a janela desktop
 * - Backend Python (FastAPI) roda como sidecar (PyInstaller .exe ou python direto em dev)
 * - Frontend Next.js static export é servido via electron-serve ou file://
 * - Auto-updater verifica GitHub Releases e atualiza automaticamente
 */

const { app, BrowserWindow, dialog, ipcMain, shell, Menu } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, execFile } = require('child_process');
const http = require('http');

// Logging
const log = require('electron-log');
log.transports.file.level = 'info';
log.transports.console.level = 'debug';
Object.assign(console, log.functions);

// Auto updater (só em produção)
let autoUpdater = null;
if (app.isPackaged) {
  try {
    autoUpdater = require('electron-updater').autoUpdater;
    autoUpdater.logger = log;
    autoUpdater.autoDownload = true;
    autoUpdater.autoInstallOnAppQuit = true;
  } catch (e) {
    log.warn('electron-updater não disponível:', e.message);
  }
}

// Configurações
const BACKEND_PORT = process.env.BACKEND_PORT || 8000;
const FRONTEND_PORT = process.env.FRONTEND_PORT || 3000;
const isDev = !app.isPackaged || process.env.NODE_ENV === 'development';

let mainWindow = null;
let backendProcess = null;
let backendReady = false;
let splashWindow = null;

// Paths
function getAppDataPath() {
  // Usar userData para armazenar banco, certificados, etc
  return app.getPath('userData');
}

function getBackendPath() {
  if (isDev) {
    // Em dev, usar python direto
    return null;
  }
  // Em produção, o backend está em extraResources/backend
  const resourcesPath = process.resourcesPath;
  const backendDir = path.join(resourcesPath, 'backend');
  
  // Tentar encontrar o executável
  const possibleNames = [
    'notasflow-backend.exe',  // Windows PyInstaller onefile
    'notasflow-backend',       // Linux/Mac PyInstaller onefile
    path.join('notasflow-backend', 'notasflow-backend.exe'), // Windows dir
    path.join('notasflow-backend', 'notasflow-backend'),     // Linux dir
  ];
  
  for (const name of possibleNames) {
    const fullPath = path.join(backendDir, name);
    if (fs.existsSync(fullPath)) {
      return fullPath;
    }
  }
  
  // Fallback: procurar qualquer .exe na pasta backend
  if (fs.existsSync(backendDir)) {
    const files = fs.readdirSync(backendDir);
    for (const file of files) {
      if (file.endsWith('.exe') || file === 'notasflow-backend') {
        return path.join(backendDir, file);
      }
    }
  }
  
  return null;
}

function getFrontendPath() {
  if (isDev) {
    return null; // Em dev, usa localhost:3000
  }
  const resourcesPath = process.resourcesPath;
  // Tentar vários locais possíveis para frontend standalone
  const possible = [
    path.join(resourcesPath, 'frontend'), // extraResources/frontend
    path.join(resourcesPath, 'app.asar.unpacked', 'frontend'),
    path.join(__dirname, '../../frontend/.next/standalone'),
    path.join(__dirname, '../../frontend/out'),
  ];
  for (const p of possible) {
    if (fs.existsSync(p)) return p;
  }
  return path.join(resourcesPath, 'frontend');
}

let frontendProcess = null;

function findFrontendServer() {
  const frontendPath = getFrontendPath();
  if (!frontendPath) return null;
  
  const candidates = [
    path.join(frontendPath, 'server.js'),
    path.join(frontendPath, 'frontend', 'server.js'),
    path.join(__dirname, '../../frontend/.next/standalone/server.js'),
    path.join(frontendPath, '.next', 'standalone', 'server.js'),
  ];
  
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return null;
}

function startFrontend() {
  if (!isDev) {
    const frontendPath = getFrontendPath();
    log.info(`Frontend path: ${frontendPath}`);
    
    const serverPath = findFrontendServer();
    
    if (serverPath) {
      log.info(`Iniciando frontend Next.js standalone: ${serverPath}`);
      const frontendDir = path.dirname(serverPath);
      frontendProcess = spawn('node', [serverPath], {
        cwd: frontendDir,
        env: {
          ...process.env,
          PORT: String(FRONTEND_PORT),
          HOSTNAME: '127.0.0.1',
          NEXT_PUBLIC_API_URL: `http://127.0.0.1:${BACKEND_PORT}`,
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      
      frontendProcess.stdout?.on('data', (data) => {
        log.info(`[frontend] ${data.toString().trim()}`);
      });
      frontendProcess.stderr?.on('data', (data) => {
        log.info(`[frontend] ${data.toString().trim()}`);
      });
      frontendProcess.on('error', (err) => {
        log.error('Erro no frontend:', err);
      });
      frontendProcess.on('exit', (code) => {
        log.warn(`Frontend saiu: code=${code}`);
      });
    } else {
      log.info('Frontend standalone não encontrado, tentando servir arquivos estáticos');
      log.info(`Procurado em: ${frontendPath}/server.js`);
    }
  }
}

function checkFrontendHealth() {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${FRONTEND_PORT}`, (res) => {
      resolve(res.statusCode === 200 || res.statusCode === 404); // 404 também indica que server está respondendo
    });
    req.on('error', () => resolve(false));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForFrontend(maxAttempts = 30) {
  for (let i = 0; i < maxAttempts; i++) {
    const ok = await checkFrontendHealth();
    if (ok) {
      log.info('Frontend pronto!');
      return true;
    }
    log.info(`Aguardando frontend... tentativa ${i + 1}/${maxAttempts}`);
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

function getEnvForBackend() {
  const appDataPath = getAppDataPath();
  const dadosDir = path.join(appDataPath, 'dados');
  const dbPath = path.join(dadosDir, 'notasflow.db');
  
  // Garantir diretórios
  if (!fs.existsSync(dadosDir)) {
    fs.mkdirSync(dadosDir, { recursive: true });
  }
  for (const sub of ['certificados', 'xml']) {
    const p = path.join(dadosDir, sub);
    if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
  }
  
  // Gerar chaves se não existirem
  const envPath = path.join(appDataPath, '.env.desktop');
  let envVars = {};
  if (fs.existsSync(envPath)) {
    try {
      const content = fs.readFileSync(envPath, 'utf8');
      for (const line of content.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) continue;
        const eqIdx = trimmed.indexOf('=');
        if (eqIdx > 0) {
          const key = trimmed.slice(0, eqIdx).trim();
          const value = trimmed.slice(eqIdx + 1).trim();
          envVars[key] = value;
        }
      }
    } catch (e) {
      log.warn('Erro ao ler .env.desktop:', e);
    }
  }
  
  // Gerar chaves faltantes
  if (!envVars.SECRET_KEY) {
    const crypto = require('crypto');
    envVars.SECRET_KEY = crypto.randomBytes(32).toString('hex');
  }
  if (!envVars.VAULT_MASTER_KEY) {
    // Fernet key: 32 bytes base64 urlsafe
    const crypto = require('crypto');
    const key = crypto.randomBytes(32);
    envVars.VAULT_MASTER_KEY = key.toString('base64').replace(/\+/g, '-').replace(/\//g, '_');
  }
  if (!envVars.BOOTSTRAP_EMAIL) {
    envVars.BOOTSTRAP_EMAIL = 'admin@notasflow.local';
  }
  if (!envVars.BOOTSTRAP_SENHA) {
    const crypto = require('crypto');
    envVars.BOOTSTRAP_SENHA = 'Admin@' + crypto.randomBytes(3).toString('hex');
  }
  if (!envVars.BOOTSTRAP_NOME) {
    envVars.BOOTSTRAP_NOME = 'Administrador';
  }
  
  // Salvar env
  try {
    const envContent = Object.entries(envVars).map(([k, v]) => `${k}=${v}`).join('\n');
    fs.writeFileSync(envPath, envContent, 'utf8');
    log.info(`Env desktop salvo em: ${envPath}`);
    
    // Também salvar credenciais em arquivo texto para o usuário (como no modo Docker)
    const credPath = path.join(appDataPath, 'CREDENCIAIS.txt');
    if (!fs.existsSync(credPath)) {
      fs.writeFileSync(credPath, 
        `NotasFlow Desktop - Credenciais de Acesso\n` +
        `==========================================\n` +
        `Email: ${envVars.BOOTSTRAP_EMAIL}\n` +
        `Senha: ${envVars.BOOTSTRAP_SENHA}\n` +
        `\n` +
        `Guarde este arquivo em local seguro!\n` +
        `Local do banco: ${dbPath}\n` +
        `Local dos dados: ${dadosDir}\n`,
        'utf8'
      );
    }
  } catch (e) {
    log.warn('Erro ao salvar .env.desktop:', e);
  }
  
  return {
    ...process.env,
    DATABASE_URL: `sqlite:///${dbPath.replace(/\\/g, '/')}`,
    DADOS_DIR: dadosDir,
    MODO_DESKTOP: 'true',
    DESKTOP_MODE: 'true',
    SECRET_KEY: envVars.SECRET_KEY,
    VAULT_MASTER_KEY: envVars.VAULT_MASTER_KEY,
    BOOTSTRAP_EMAIL: envVars.BOOTSTRAP_EMAIL,
    BOOTSTRAP_SENHA: envVars.BOOTSTRAP_SENHA,
    BOOTSTRAP_NOME: envVars.BOOTSTRAP_NOME,
    BOOTSTRAP_ESCRITORIO: 'Escritorio Cajuru',
    CORS_ORIGINS: '*',
    HOST: '127.0.0.1',
    PORT: String(BACKEND_PORT),
    API_PORT: String(BACKEND_PORT),
    PYTHONUNBUFFERED: '1',
  };
}

function checkBackendHealth() {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${BACKEND_PORT}/saude`, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend(maxAttempts = 60) {
  for (let i = 0; i < maxAttempts; i++) {
    const ok = await checkBackendHealth();
    if (ok) {
      log.info('Backend pronto!');
      backendReady = true;
      return true;
    }
    log.info(`Aguardando backend... tentativa ${i + 1}/${maxAttempts}`);
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

function startBackend() {
  const env = getEnvForBackend();
  const backendPath = getBackendPath();
  
  log.info(`Iniciando backend...`);
  log.info(`Backend path: ${backendPath || 'python modo dev'}`);
  log.info(`Dados dir: ${env.DADOS_DIR}`);
  log.info(`Database: ${env.DATABASE_URL}`);
  
  if (isDev) {
    // Modo dev: usar python -m app.desktop_main
    const backendRoot = path.join(__dirname, '../../backend');
    log.info(`Backend root (dev): ${backendRoot}`);
    
    backendProcess = spawn('python', ['-m', 'app.desktop_main'], {
      cwd: backendRoot,
      env: env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } else {
    // Modo produção: usar executável PyInstaller
    if (!backendPath || !fs.existsSync(backendPath)) {
      log.error(`Backend executável não encontrado: ${backendPath}`);
      // Tentar fallback: procurar em app.asar.unpacked ou resources
      const altPaths = [
        path.join(process.resourcesPath, 'app.asar.unpacked', 'backend', 'notasflow-backend.exe'),
        path.join(__dirname, '../../backend/dist/notasflow-backend/notasflow-backend.exe'),
        path.join(__dirname, '../../backend/dist/notasflow-backend.exe'),
      ];
      for (const alt of altPaths) {
        if (fs.existsSync(alt)) {
          log.info(`Usando backend alternativo: ${alt}`);
          backendProcess = execFile(alt, {
            env: env,
            windowsHide: true,
          });
          break;
        }
      }
      if (!backendProcess) {
        dialog.showErrorBox(
          'Erro ao iniciar',
          `Backend não encontrado.\n\nProcurado em: ${backendPath}\n\nTente reinstalar o aplicativo.`
        );
        return;
      }
    } else {
      log.info(`Executando backend: ${backendPath}`);
      backendProcess = execFile(backendPath, {
        env: env,
        windowsHide: true,
      });
    }
  }
  
  if (backendProcess) {
    backendProcess.stdout?.on('data', (data) => {
      log.info(`[backend] ${data.toString().trim()}`);
    });
    backendProcess.stderr?.on('data', (data) => {
      const text = data.toString().trim();
      // Filtrar logs normais do uvicorn que vão para stderr
      if (text.includes('INFO') || text.includes('Uvicorn') || text.includes('Started')) {
        log.info(`[backend] ${text}`);
      } else {
        log.warn(`[backend-err] ${text}`);
      }
    });
    backendProcess.on('error', (err) => {
      log.error('Erro no backend:', err);
    });
    backendProcess.on('exit', (code, signal) => {
      log.warn(`Backend saiu: code=${code} signal=${signal}`);
      if (mainWindow && !app.isQuitting) {
        // Tentar reiniciar se saiu inesperadamente
        log.info('Tentando reiniciar backend em 3s...');
        setTimeout(() => {
          if (!app.isQuitting) startBackend();
        }, 3000);
      }
    });
  }
}

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 400,
    height: 300,
    frame: false,
    alwaysOnTop: true,
    transparent: false,
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });
  
  const splashHtml = `
    <html>
    <head>
      <style>
        body { 
          margin:0; padding:0; 
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: white;
          display:flex; flex-direction:column; align-items:center; justify-content:center;
          height:100vh; text-align:center;
        }
        h1 { font-size:24px; margin:0 0 10px 0; font-weight:700; }
        p { font-size:14px; opacity:0.9; margin:5px 0; }
        .spinner { 
          width:40px; height:40px; border:3px solid rgba(255,255,255,0.3);
          border-top-color:white; border-radius:50%;
          animation: spin 1s linear infinite; margin:20px 0;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .logo { font-size:48px; margin-bottom:10px; }
      </style>
    </head>
    <body>
      <div class="logo">📄</div>
      <h1>NotasFlow</h1>
      <div class="spinner"></div>
      <p>Iniciando sistema...</p>
      <p style="font-size:11px; opacity:0.7;">Isso pode levar alguns segundos na primeira vez</p>
    </body>
    </html>
  `;
  
  splashWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(splashHtml)}`);
  splashWindow.center();
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 600,
    show: false,
    backgroundColor: '#ffffff',
    icon: getIconPath(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
  });

  // Menu
  const template = [
    {
      label: 'Arquivo',
      submenu: [
        { role: 'quit', label: 'Sair' },
      ],
    },
    {
      label: 'Editar',
      submenu: [
        { role: 'undo', label: 'Desfazer' },
        { role: 'redo', label: 'Refazer' },
        { type: 'separator' },
        { role: 'cut', label: 'Recortar' },
        { role: 'copy', label: 'Copiar' },
        { role: 'paste', label: 'Colar' },
        { role: 'selectAll', label: 'Selecionar tudo' },
      ],
    },
    {
      label: 'Exibir',
      submenu: [
        { role: 'reload', label: 'Recarregar' },
        { role: 'forceReload', label: 'Forçar recarga' },
        { role: 'toggleDevTools', label: 'Ferramentas de desenvolvedor' },
        { type: 'separator' },
        { role: 'resetZoom', label: 'Zoom normal' },
        { role: 'zoomIn', label: 'Aumentar zoom' },
        { role: 'zoomOut', label: 'Diminuir zoom' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: 'Tela cheia' },
      ],
    },
    {
      label: 'Ajuda',
      submenu: [
        {
          label: 'Sobre NotasFlow',
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'Sobre NotasFlow',
              message: 'NotasFlow Desktop',
              detail: `Versão: ${app.getVersion()}\n\nImportação automática de documentos fiscais (NFS-e, NFe, CT-e) direto das fontes oficiais.\n\nDados salvos em: ${getAppDataPath()}\nBackend: http://127.0.0.1:${BACKEND_PORT}\nFrontend: http://127.0.0.1:${FRONTEND_PORT}\n\n© 2026 NotasFlow`,
            });
          },
        },
        {
          label: 'Abrir pasta de dados',
          click: () => {
            shell.openPath(getAppDataPath());
          },
        },
        {
          label: 'Ver credenciais',
          click: () => {
            const credPath = path.join(getAppDataPath(), 'CREDENCIAIS.txt');
            if (fs.existsSync(credPath)) {
              shell.openPath(credPath);
            } else {
              dialog.showMessageBox(mainWindow, {
                type: 'info',
                title: 'Credenciais',
                message: 'Arquivo de credenciais não encontrado',
                detail: `Procure em: ${credPath}\n\nSe for a primeira vez, aguarde o backend iniciar completamente.`,
              });
            }
          },
        },
        { type: 'separator' },
        {
          label: 'Verificar atualizações',
          click: () => {
            if (autoUpdater) {
              autoUpdater.checkForUpdatesAndNotify();
            } else {
              dialog.showMessageBox(mainWindow, {
                type: 'info',
                title: 'Atualizações',
                message: 'Verificação de atualizações só funciona na versão instalada (não em desenvolvimento).',
              });
            }
          },
        },
      ],
    },
  ];
  
  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);

  // Carregar frontend
  if (isDev) {
    // Em dev, tentar localhost:3000 primeiro (Next.js dev server)
    mainWindow.loadURL(`http://127.0.0.1:${FRONTEND_PORT}`).catch(() => {
      // Fallback: tentar carregar do arquivo se dev server não estiver rodando
      const frontendPath = path.join(__dirname, '../../frontend/out/index.html');
      if (fs.existsSync(frontendPath)) {
        mainWindow.loadFile(frontendPath);
      } else {
        mainWindow.loadURL(`data:text/html,<h1>Frontend não encontrado</h1><p>Rode 'npm run dev:frontend' em outro terminal</p>`);
      }
    });
  } else {
    // Em produção, frontend roda como standalone server em localhost:3000
    // Se standalone não estiver rodando, tenta carregar arquivo estático
    mainWindow.loadURL(`http://127.0.0.1:${FRONTEND_PORT}`).catch(() => {
      const frontendPath = getFrontendPath();
      const indexPath = path.join(frontendPath, 'index.html');
      const altIndexPath = path.join(frontendPath, '.next/server/app/index.html');
      
      if (fs.existsSync(indexPath)) {
        mainWindow.loadFile(indexPath);
      } else if (frontendPath && fs.existsSync(path.join(frontendPath, 'server.js'))) {
        // Frontend standalone existe mas ainda não iniciou, aguardar e tentar de novo
        setTimeout(() => {
          mainWindow.loadURL(`http://127.0.0.1:${FRONTEND_PORT}`).catch(() => {
            mainWindow.loadURL(`data:text/html,<h1>NotasFlow</h1><p>Backend: http://127.0.0.1:${BACKEND_PORT}</p><p>Frontend iniciando...</p>`);
          });
        }, 2000);
      } else {
        mainWindow.loadURL(`http://127.0.0.1:${BACKEND_PORT}/docs`).catch(() => {
          mainWindow.loadURL(`data:text/html,<h1>NotasFlow</h1><p>Backend rodando em http://127.0.0.1:${BACKEND_PORT}</p><p>Frontend não encontrado em ${frontendPath}</p><p>Aguarde inicialização...</p>`);
        });
      }
    });
  }

  // Abrir links externos no navegador padrão
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      // Permitir apenas localhost para API, resto abre no browser
      if (url.includes('localhost') && (url.includes(String(BACKEND_PORT)) || url.includes(String(FRONTEND_PORT)))) {
        return { action: 'allow' };
      }
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  mainWindow.once('ready-to-show', () => {
    if (splashWindow) {
      splashWindow.close();
      splashWindow = null;
    }
    mainWindow.show();
    mainWindow.maximize();
    
    if (isDev) {
      mainWindow.webContents.openDevTools();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function getIconPath() {
  if (isDev) {
    return path.join(__dirname, '../build/icon.png');
  }
  const possible = [
    path.join(process.resourcesPath, 'build/icon.png'),
    path.join(__dirname, '../build/icon.png'),
    path.join(__dirname, 'build/icon.png'),
  ];
  for (const p of possible) {
    if (fs.existsSync(p)) return p;
  }
  return undefined;
}

// IPC handlers
ipcMain.handle('get-app-info', () => {
  return {
    version: app.getVersion(),
    isDev,
    appDataPath: getAppDataPath(),
    backendPort: BACKEND_PORT,
    backendReady,
  };
});

ipcMain.handle('get-credentials', () => {
  try {
    const credPath = path.join(getAppDataPath(), 'CREDENCIAIS.txt');
    if (fs.existsSync(credPath)) {
      return fs.readFileSync(credPath, 'utf8');
    }
    return null;
  } catch (e) {
    return null;
  }
});

ipcMain.handle('open-data-folder', () => {
  shell.openPath(getAppDataPath());
});

ipcMain.handle('check-for-updates', () => {
  if (autoUpdater) {
    autoUpdater.checkForUpdatesAndNotify();
    return true;
  }
  return false;
});

// App lifecycle
app.whenReady().then(async () => {
  log.info(`NotasFlow Desktop v${app.getVersion()} iniciando...`);
  log.info(`isDev: ${isDev}`);
  log.info(`appDataPath: ${getAppDataPath()}`);
  
  createSplashWindow();
  
  // Iniciar backend
  startBackend();
  
  // Iniciar frontend (em produção, standalone server)
  if (!isDev) {
    startFrontend();
  }
  
  // Aguardar backend ficar pronto
  const ready = await waitForBackend(90);
  if (!ready) {
    log.error('Backend não ficou pronto a tempo');
    if (splashWindow) {
      splashWindow.close();
    }
    dialog.showErrorBox(
      'Erro ao iniciar',
      'O backend não iniciou corretamente.\n\nVerifique os logs em:\n' + path.join(getAppDataPath(), 'logs')
    );
  }
  
  // Aguardar frontend em produção
  if (!isDev && frontendProcess) {
    await waitForFrontend(30);
  }
  
  createMainWindow();
  
  // Auto updater
  if (autoUpdater) {
    autoUpdater.on('checking-for-update', () => {
      log.info('Verificando atualizações...');
    });
    autoUpdater.on('update-available', (info) => {
      log.info('Atualização disponível:', info.version);
      if (mainWindow) {
        dialog.showMessageBox(mainWindow, {
          type: 'info',
          title: 'Atualização disponível',
          message: `Nova versão ${info.version} disponível`,
          detail: 'A atualização será baixada em segundo plano.',
        });
      }
    });
    autoUpdater.on('update-not-available', () => {
      log.info('Nenhuma atualização disponível');
    });
    autoUpdater.on('download-progress', (progress) => {
      log.info(`Download atualização: ${progress.percent.toFixed(1)}%`);
      if (mainWindow) {
        mainWindow.setProgressBar(progress.percent / 100);
      }
    });
    autoUpdater.on('update-downloaded', (info) => {
      log.info('Atualização baixada:', info.version);
      if (mainWindow) {
        mainWindow.setProgressBar(-1);
        dialog.showMessageBox(mainWindow, {
          type: 'info',
          title: 'Atualização pronta',
          message: `Versão ${info.version} baixada`,
          detail: 'A aplicação será reiniciada para instalar a atualização.',
          buttons: ['Reiniciar agora', 'Depois'],
          defaultId: 0,
        }).then((result) => {
          if (result.response === 0) {
            autoUpdater.quitAndInstall();
          }
        });
      }
    });
    autoUpdater.on('error', (err) => {
      log.error('Erro no auto-updater:', err);
    });
    
    // Verificar atualizações após 5 segundos
    setTimeout(() => {
      autoUpdater.checkForUpdatesAndNotify().catch((e) => {
        log.warn('Falha ao verificar atualizações:', e.message);
      });
    }, 5000);
  }
  
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  app.isQuitting = true;
  log.info('Encerrando aplicação...');
  
  if (backendProcess) {
    try {
      if (process.platform === 'win32') {
        // No Windows, matar processo e filhos
        spawn('taskkill', ['/pid', backendProcess.pid.toString(), '/f', '/t']);
      } else {
        backendProcess.kill('SIGTERM');
      }
      log.info('Backend encerrado');
    } catch (e) {
      log.warn('Erro ao encerrar backend:', e);
    }
    backendProcess = null;
  }
  
  if (frontendProcess) {
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', frontendProcess.pid.toString(), '/f', '/t']);
      } else {
        frontendProcess.kill('SIGTERM');
      }
      log.info('Frontend encerrado');
    } catch (e) {
      log.warn('Erro ao encerrar frontend:', e);
    }
    frontendProcess = null;
  }
});

// Tratar erros não capturados
process.on('uncaughtException', (error) => {
  log.error('Uncaught exception:', error);
});

process.on('unhandledRejection', (reason) => {
  log.error('Unhandled rejection:', reason);
});
