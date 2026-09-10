# Como adicionar o workflow de build do .exe no GitHub

O arquivo `.github/workflows/build-desktop.yml` foi criado localmente mas **não pode ser enviado pelo bot** (permissão `workflows` bloqueada para GitHub Apps).

## O que fazer (1 minuto)

### Opção 1 — Via GitHub Web (mais fácil)
1. Abra https://github.com/montx2/Cajuru28
2. Vá em `Add file` → `Create new file`
3. Caminho: `.github/workflows/build-desktop.yml`
4. Copie o conteúdo abaixo e faça commit direto na `main` ou na branch `arena/01a088f3-cajuru28`
5. Pronto — o workflow aparecerá em Actions

### Opção 2 — Via git local (se você tem o repo clonado)
```bash
git checkout arena/01a088f3-cajuru28
git add .github/workflows/build-desktop.yml
git commit -m "ci: add desktop build workflow"
git push
```

### Conteúdo do arquivo (já está em `.github/workflows/build-desktop.yml` neste branch local)

```yaml
name: Build Desktop App (.exe)

on:
  push:
    tags:
      - 'v*'
      - 'desktop-v*'
  workflow_dispatch:

jobs:
  build-windows:
    runs-on: windows-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install frontend
        working-directory: frontend
        run: npm ci
      - name: Install backend
        working-directory: backend
        run: |
          pip install -r requirements.txt
          pip install pyinstaller
      - name: Build backend
        working-directory: backend
        run: |
          pyinstaller --noconfirm --clean --name notasflow-backend --onedir --console app/desktop_main.py
      - name: Build frontend standalone
        working-directory: frontend
        env:
          NEXT_PUBLIC_API_URL: http://localhost:8000
        run: node scripts/build-desktop.js
      - name: Install desktop
        working-directory: desktop
        run: npm ci
      - name: Build Electron
        working-directory: desktop
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: npm run build:win
      - name: Upload
        uses: actions/upload-artifact@v4
        with:
          name: NotasFlow-Windows
          path: |
            desktop/dist/*.exe
            desktop/dist/*.yml
            desktop/dist/*.blockmap
      - name: Release
        if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v1
        with:
          files: |
            desktop/dist/*.exe
            desktop/dist/*.yml
            desktop/dist/*.blockmap
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Como gerar Release e auto-update

1. Depois do workflow estar na `main`, crie uma tag:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
2. O GitHub Actions vai buildar o `.exe` automaticamente (Windows runner)
3. Vai criar uma Release com `.exe` + `.yml` + `.blockmap`
4. Clientes instalados verificam essa Release e auto-atualizam (electron-updater)

Para correção rápida:
```bash
git tag v1.0.1
git push origin v1.0.1
# todos os PCs atualizam em até 24h, ou ao clicar "Verificar atualizações" no menu Ajuda
```
