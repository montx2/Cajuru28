# NotasFlow Desktop (.exe)

Versão desktop do NotasFlow - roda 100% local, sem precisar de Docker, internet para funcionar (só precisa de internet para buscar notas na SEFAZ/ADN).

## 🎯 Por que desktop?

**Antes (Docker/web):**
- Um servidor central, todos os usuários competem por recursos
- Se 10 pessoas clicam "importar todas" ao mesmo tempo, trava
- Precisa de Docker, configuração técnica

**Agora (Desktop .exe):**
- Cada computador roda seu próprio programa
- Não trava com muitos usuários - cada um usa sua máquina
- Baixa o .exe bonito e pronto
- Auto-atualização: quando você corrige um erro, todos recebem automaticamente

## 📦 Como gerar o .exe

### Opção 1: Automático via GitHub (recomendado para distribuição)

1. Faça suas alterações no código
2. Crie uma tag de versão:
   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```
3. O GitHub Actions vai:
   - Compilar backend Python para .exe com PyInstaller
   - Compilar frontend Next.js para arquivos estáticos
   - Empacotar tudo com Electron em um instalador .exe
   - Criar uma Release no GitHub com o .exe
4. Usuários com o app instalado recebem atualização automática!

### Opção 2: Build local (Windows)

Pré-requisitos:
- Node.js 20+
- Python 3.11+
- Windows (para gerar .exe Windows)

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --noconfirm --clean --name notasflow-backend --onedir --console app/desktop_main.py

# 2. Frontend
cd ../frontend
npm install
npm run build:desktop

# 3. Desktop
cd ../desktop
npm install
npm run build:win

# Resultado em desktop/dist/
# - NotasFlow-1.0.0-x64.exe (instalador)
# - NotasFlow-Portable-1.0.0.exe (portátil, sem instalação)
```

## 🔄 Auto-atualização (você corrige, todos recebem)

O sistema usa `electron-updater` com GitHub Releases:

**Como funciona:**
1. App instalado verifica GitHub a cada inicialização
2. Se houver nova versão (nova Release), baixa em segundo plano
3. Mostra notificação "Atualização disponível"
4. Na próxima reinicialização, instala automaticamente

**Para você (desenvolvedor):**
- Corrigiu um bug? Faça commit e push de tag `v1.0.2`
- GitHub Actions gera novo .exe e publica como Release
- Todos os clientes atualizam sozinhos em até 24h
- Não precisa pedir para cada um baixar manualmente

**Configuração:**
Em `desktop/package.json`:
```json
"publish": {
  "provider": "github",
  "owner": "montx2",
  "repo": "Cajuru28"
}
```

## 🖥️ Como o usuário usa

1. Baixa `NotasFlow-1.0.0-x64.exe` da página de Releases
2. Dá duplo clique, instala (como qualquer programa)
3. Abre o NotasFlow no Menu Iniciar
4. Na primeira vez, mostra `CREDENCIAIS.txt` com email/senha
5. Usa normalmente: cadastra empresas, envia certificados, importa notas

**Dados salvos em:**
- Windows: `%APPDATA%\NotasFlow\`
- Banco: `%APPDATA%\NotasFlow\dados\notasflow.db`
- Certificados: `%APPDATA%\NotasFlow\dados\certificados\`
- XMLs: `%APPDATA%\NotasFlow\dados\xml\`

**Desinstalação:**
- Desinstala pelo Painel de Controle, mas dados são preservados
- Para remover tudo, apagar `%APPDATA%\NotasFlow\`

## 🔧 Arquitetura Desktop

```
NotasFlow.exe (Electron)
    │
    ├─→ Frontend (Next.js static export em resources/frontend/)
    │   └─→ Carregado via file:// no BrowserWindow
    │
    └─→ Backend (Python FastAPI em resources/backend/)
        ├─→ Rodado como processo filho (PyInstaller .exe)
        ├─→ SQLite local (notasflow.db)
        ├─→ Scheduler em thread (substitui Celery Beat)
        └─→ Fila em thread (substitui Redis/Celery)
        
        └─→ SEFAZ/ADN (internet, só para buscar notas)
```

**Diferenças do modo Docker:**
| Aspecto | Docker (servidor) | Desktop (.exe) |
|---------|-------------------|----------------|
| Banco | PostgreSQL | SQLite local |
| Fila | Redis + Celery | Threads Python |
| Scheduler | Celery Beat | Thread loop |
| Deploy | Docker Compose | Instalador .exe |
| Multiusuário | Sim, central | Não, cada PC isolado |
| Performance | Compartilhada | Individual (não trava) |
| Atualização | git pull + docker rebuild | Automática via GitHub |

## 🛡️ Segurança Desktop

- Banco SQLite local, criptografado via cofre Fernet (mesmo do modo Docker)
- Certificados .pfx com permissão restrita, salvos em userData
- Senhas nunca em texto puro, só cifradas
- CORS liberado para file:// e localhost (necessário para Electron)

## 📝 Desenvolvimento

```bash
# Terminal 1: Backend
cd backend
DATABASE_URL=sqlite:///./data_desktop/notasflow.db DADOS_DIR=./data_desktop MODO_DESKTOP=true python -m app.desktop_main

# Terminal 2: Frontend
cd frontend
npm run dev

# Terminal 3: Electron (dev)
cd desktop
npm install
npm run dev
```

Em dev, Electron tenta conectar em `http://localhost:3000` (Next.js dev) e `http://localhost:8000` (backend).

## 🚀 Roadmap Desktop

- [x] Backend modo desktop (SQLite + threads)
- [x] Electron main process com backend sidecar
- [x] Auto-updater via GitHub Releases
- [x] Instalador NSIS + Portable
- [x] Seleção de empresas na importação (não mais "todas obrigatórias")
- [ ] Code signing (certificado para evitar SmartScreen)
- [ ] Backup automático do banco para nuvem (opcional)
- [ ] Sincronização entre PCs do mesmo escritório (opcional, via API central)

## ❓ FAQ

**P: O usuário precisa de internet?**
R: Só para buscar notas na SEFAZ/ADN. O programa abre e mostra notas já baixadas mesmo offline.

**P: E se eu tiver 30 empresas?**
R: Cada PC importa só as que selecionar. Antes era "todas ou nada", agora tem checkbox para escolher.

**P: Como faço para atualizar todos quando corrijo um bug?**
R: Crie tag `v1.0.2` e push. GitHub Actions publica Release, e todos os apps instalados atualizam sozinhos.

**P: O .exe funciona sem Python instalado?**
R: Sim! PyInstaller empacota Python + dependências dentro do .exe. Usuário não precisa instalar nada.

**P: Posso ter modo Docker e Desktop ao mesmo tempo?**
R: Sim! São modos diferentes do mesmo código. Docker continua funcionando como antes. Desktop é novo.
