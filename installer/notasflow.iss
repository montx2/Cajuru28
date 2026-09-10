; ===========================================================================
;  NotasFlow — instalador para Windows (Inno Setup 6)
; ===========================================================================
;
;  Este é o arquivo que transforma a pasta gerada pelo PyInstaller no `.exe`
;  que o contador baixa e dá dois cliques. Ele responde, sozinho, às perguntas
;  que todo instalador precisa responder — e as respostas aqui foram escolhidas
;  pensando em escritório de contabilidade, não em servidor:
;
;  **Instala por usuário, sem UAC.** `PrivilegesRequired=lowest` e a pasta em
;  `%LOCALAPPDATA%\Programs\NotasFlow`. Isso significa: nenhuma janela azul de
;  "permitir que este aplicativo faça alterações" — nem na instalação, nem,
;  principalmente, **na atualização automática**. Um updater silencioso que
;  precisa de clique de administrador não é silencioso: ele para no meio da
;  madrugada esperando alguém que não está lá.
;
;  **Atualiza por cima.** O `AppId` abaixo é fixo para sempre. Uma versão nova
;  se instala sobre a antiga (mesmo caminho, mesmas chaves), sem desinstalar
;  nada e sem tocar nos dados — que, de propósito, moram em
;  `%APPDATA%\NotasFlow` e não dentro da pasta do programa
;  (ver `backend/app/desktop/caminhos.py`).
;
;  **O usuário decide o que fazer com os dados.** Na desinstalação, o padrão é
;  **manter** banco, certificados e XMLs: quem desinstala para reinstalar não
;  pode perder o histórico fiscal por descuido.
;
;  Compilar:
;      iscc /DVersao=1.2.0 /DOrigem=..\dist\NotasFlow /DSaida=..\dist installer\notasflow.iss
;  (é o que `scripts/empacotar.py` faz automaticamente)
;
;  Testar o modo silencioso, que é o que a atualização automática usa:
;      NotasFlow-Setup-1.2.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL
; ===========================================================================

#ifndef Versao
  #define Versao "0.0.0"
#endif
#ifndef Origem
  #define Origem "..\dist\NotasFlow"
#endif
#ifndef Saida
  #define Saida "..\dist"
#endif

#define NomeApp "NotasFlow"
#define Fabricante "NotasFlow"
#define UrlApp "https://github.com/montx2/Cajuru28"
#define ExeApp "NotasFlow.exe"

[Setup]
; O AppId identifica o programa para sempre: é ele que faz a versão nova ser
; uma ATUALIZAÇÃO e não um segundo programa instalado ao lado do primeiro.
; Não mude esta linha — nem se o nome do programa mudar.
AppId={{8E4B1F62-2D6A-4C3B-9A57-4E0C1B7D53A1}
AppName={#NomeApp}
AppVersion={#Versao}
AppVerName={#NomeApp} {#Versao}
AppPublisher={#Fabricante}
AppPublisherURL={#UrlApp}
AppSupportURL={#UrlApp}/issues
AppUpdatesURL={#UrlApp}/releases
VersionInfoVersion={#Versao}
VersionInfoCompany={#Fabricante}
VersionInfoDescription={#NomeApp} — importação automática de notas fiscais
VersionInfoProductName={#NomeApp}

; Sem administrador: ver comentário no topo.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#NomeApp}
DefaultGroupName={#NomeApp}
DisableProgramGroupPage=yes
AllowNoIcons=yes

OutputDir={#Saida}
OutputBaseFilename={#NomeApp}-Setup-{#Versao}
SetupIconFile=notasflow.ico
UninstallDisplayIcon={app}\{#ExeApp}
UninstallDisplayName={#NomeApp} {#Versao}

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; O painel do instalador em português, mesmo que o Windows esteja em inglês.
ShowLanguageDialog=auto

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Um segundo clique no .exe durante a instalação não pode abrir duas cópias.
SetupMutex={#NomeApp}Setup

; Fechar um NotasFlow aberto antes de trocar os arquivos.
; A atualização automática já encerra o programa sozinha antes de chamar o
; instalador — mas quem baixou o instalador na mão e deu dois cliques com o
; programa aberto também precisa que isso funcione.
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll
RestartApplications=no

[Languages]
; Portuguese.isl é o português de Portugal; BrazilianPortuguese.isl é o nosso.
; Os dois entram porque o objetivo é o usuário entender a tela, não o contrário.
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "iconearea"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"
Name: "iniciarcomwindows"; Description: "Abrir o NotasFlow junto com o Windows (recomendado)"; GroupDescription: "Sincronização automática:"; Flags: checkedonce

[Files]
; A pasta inteira do PyInstaller. `recursesubdirs` porque o `_internal` traz
; bibliotecas em subpastas.
Source: "{#Origem}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#NomeApp}"; Filename: "{app}\{#ExeApp}"; IconFilename: "{app}\{#ExeApp}"
Name: "{group}\Desinstalar o {#NomeApp}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#NomeApp}"; Filename: "{app}\{#ExeApp}"; IconFilename: "{app}\{#ExeApp}"; Tasks: iconearea

[Registry]
; Mesma chave que o próprio programa usa (servidor.definir_iniciar_com_windows):
; assim a caixinha em Configurações e a tarefa do instalador nunca divergem.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "NotasFlow"; ValueData: """{app}\{#ExeApp}"" --minimizado"; \
    Flags: uninsdeletevalue; Tasks: iniciarcomwindows

[Run]
; `/VERYSILENT` na linha de comando também suprime esta tela — é assim que a
; atualização automática instala sem perguntar nada.
Filename: "{app}\{#ExeApp}"; Description: "Abrir o {#NomeApp} agora"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Nada da pasta de dados é apagado aqui de propósito: banco, certificados e
; XMLs ficam em %APPDATA%\NotasFlow, que é o que o [Code] abaixo pergunta.
; Aqui só se remove o que o instalador criou.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\NotasFlow.exe"

[Code]
// ---------------------------------------------------------------------------
// Desinstalação: perguntar antes de apagar dados fiscais
// ---------------------------------------------------------------------------
// Desinstalar um programa é uma ação reversível; apagar o banco de notas e os
// certificados digitais não é. Por isso o padrão aqui é **manter**, e apagar
// exige uma resposta explícita — no modo silencioso, sem ninguém para
// responder, mantém.
function InitializeUninstall(): Boolean;
var
  Resposta: Integer;
begin
  Result := True;

  if UninstallSilent() then
    Exit;

  Resposta := MsgBox(
    'Deseja apagar também os dados do NotasFlow deste computador?' + #13#10 + #13#10 +
    'Isso inclui o banco de notas fiscais, os certificados digitais A1 e os XMLs ' +
    'baixados. Se você pretende reinstalar o programa mais tarde, responda Não — ' +
    'assim o histórico continua aqui.' + #13#10 + #13#10 +
    'Pasta: %APPDATA%\NotasFlow',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2);

  if Resposta = IDYES then
  begin
    if DelTree(ExpandConstant('{userappdata}\NotasFlow'), True, True, True) then
      MsgBox('Os dados do NotasFlow foram apagados.', mbInformation, MB_OK)
    else
      MsgBox(
        'Não foi possível apagar toda a pasta de dados.' + #13#10 +
        'Ela pode estar aberta em outro programa. Apague manualmente se quiser: ' +
        ExpandConstant('{userappdata}\NotasFlow'),
        mbError, MB_OK);
  end;
end;
