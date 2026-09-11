#!/usr/bin/env bash
# =============================================================================
#  NotasFlow — Instalador completo para Linux e macOS
#  Instala TUDO numa máquina zerada: git + python3 + Docker + Docker Compose,
#  gera as chaves (.env), sobe o sistema e mostra o login.
#
#  Como usar:
#    chmod +x INSTALAR_TUDO.sh && ./INSTALAR_TUDO.sh
#
#  Verificar o que falta (sem instalar nada):
#    ./INSTALAR_TUDO.sh --so-verificar
#
#  Idempotente: pode rodar quantas vezes quiser.
# =============================================================================
set -euo pipefail

SO_VERIFICAR=0
[[ "${1:-}" == "--so-verificar" || "${1:-}" == "-n" ]] && SO_VERIFICAR=1

# ---------- helpers ----------
 passo()  { printf '\n\033[1;36m============================================================\033[0m\n\033[1;36m  %s\033[0m\n\033[1;36m============================================================\033[0m\n' "$1"; }
ok()      { printf '  \033[1;32m[OK]\033[0m %s\n' "$1"; }
aviso()   { printf '  \033[1;33m[!]\033[0m %s\n' "$1"; }
erro()    { printf '  \033[1;31m[ERRO]\033[0m %s\n' "$1"; }

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RAIZ"

printf '\n\033[1;36m########################################################\033[0m\n'
printf '\033[1;36m#        NotasFlow - INSTALADOR COMPLETO              #\033[0m\n'
printf '\033[1;36m#   Git + Python + Docker + Sistema no ar             #\033[0m\n'
printf '\033[1;36m########################################################\033[0m\n\n'
[[ $SO_VERIFICAR -eq 1 ]] && { printf '\033[1;33m  MODO VERIFICAÇÃO: nada será instalado.\033[0m\n\n'; }

# ---------- detecta sistema ----------
SO="desconhecido"
GERENTE=""
if [[ "$(uname -s)" == "Darwin" ]]; then
  SO="macos"
elif command -v apt-get >/dev/null 2>&1; then
  SO="debian"; GERENTE="apt"
elif command -v dnf >/dev/null 2>&1; then
  SO="redhat"; GERENTE="dnf"
elif command -v yum >/dev/null 2>&1; then
  SO="redhat"; GERENTE="yum"
elif command -v pacman >/dev/null 2>&1; then
  SO="arch"; GERENTE="pacman"
elif command -v zypper >/dev/null 2>&1; then
  SO="suse"; GERENTE="zypper"
fi

if [[ "$SO" == "desconhecido" ]]; then
  erro "Distribuição Linux não reconhecida (nem apt, dnf, pacman ou zypper)."
  erro "Instale manualmente: git, python3, docker e docker compose."
  exit 1
fi
if [[ $SO_VERIFICAR -eq 0 ]]; then
  # precisa de sudo (ou ser root) para instalar pacotes
  if [[ $EUID -ne 0 ]] && ! command -v sudo >/dev/null 2>&1; then
    erro "Preciso de 'sudo' (ou rodar como root) para instalar."
    exit 1
  fi
fi
SUDO=""
[[ $EUID -ne 0 ]] && SUDO="sudo"

printf '  Sistema detectado: %s\n\n' "$SO"

FALTANDO=()

# ---------- PASSO 1: pacotes básicos (git, python3, curl) ----------
passo "PASSO 1/7 — Git e Python 3"

instalar_pacotes() {
  local pkgs=("$@")
  case $GERENTE in
    apt)    $SUDO apt-get update -y >/dev/null 2>&1 || true; $SUDO apt-get install -y "${pkgs[@]}" ;;
    dnf)    $SUDO dnf install -y "${pkgs[@]}" ;;
    yum)    $SUDO yum install -y "${pkgs[@]}" ;;
    pacman) $SUDO pacman -Sy --noconfirm --needed "${pkgs[@]}" ;;
    zypper) $SUDO zypper --non-interactive install "${pkgs[@]}" ;;
  esac
}

GIT_OK=0; PYTHON_OK=0
command -v git >/dev/null 2>&1 && GIT_OK=1
command -v python3 >/dev/null 2>&1 && PYTHON_OK=1

if [[ $GIT_OK -eq 1 ]]; then ok "Git instalado ($(git --version))"; else FALTANDO+=("git"); fi
if [[ $PYTHON_OK -eq 1 ]]; then ok "Python instalado ($(python3 --version))"; else FALTANDO+=("python3"); fi

if [[ $SO_VERIFICAR -eq 0 && ( $GIT_OK -eq 0 || $PYTHON_OK -eq 0 ) ]]; then
  case $SO in
    debian) PACS=(git python3 curl ca-certificates) ;;
    redhat) PACS=(git python3 curl) ;;
    arch)   PACS=(git python curl) ;;
    suse)   PACS=(git python3 curl) ;;
    macos)  PACS=() ;;
  esac
  if [[ $SO == "macos" ]]; then
    if ! command -v brew >/dev/null 2>&1; then
      aviso "Homebrew não encontrado. Instalando Homebrew..."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    command -v brew >/dev/null 2>&1 && brew install git python3
  else
    aviso "Instalando: ${PACS[*]}"
    instalar_pacotes "${PACS[@]}" || aviso "algum pacote básico falhou (continuando...)"
  fi
  command -v git >/dev/null 2>&1 && ok "Git instalado" || erro "Git não foi instalado"
  command -v python3 >/dev/null 2>&1 && ok "Python instalado" || erro "Python não foi instalado"
fi

# ---------- PASSO 2: Docker ----------
passo "PASSO 2/7 — Docker"

DOCKER_OK=0
if command -v docker >/dev/null 2>&1; then DOCKER_OK=1; fi

if [[ $DOCKER_OK -eq 1 ]]; then
  ok "Docker instalado ($(docker --version 2>/dev/null || echo ok))"
else
  FALTANDO+=("docker")
  if [[ $SO_VERIFICAR -eq 0 ]]; then
    aviso "Instalando Docker via script oficial get.docker.com..."
    if [[ $SO == "macos" ]]; then
      brew install --cask docker || { erro "Falha ao instalar Docker Desktop"; exit 1; }
    else
      curl -fsSL https://get.docker.com | $SUDO sh || { erro "Falha ao instalar Docker"; exit 1; }
    fi
    command -v docker >/dev/null 2>&1 && ok "Docker instalado" || { erro "Docker não apareceu no PATH"; exit 1; }
  fi
fi

# ---------- PASSO 3: motor do Docker ligado ----------
passo "PASSO 3/7 — Motor do Docker"

MOTOR_OK=0
if [[ $SO == "macos" ]]; then
  if docker info >/dev/null 2>&1; then MOTOR_OK=1
  else
    if [[ $SO_VERIFICAR -eq 0 ]]; then
      aviso "Abrindo Docker Desktop..."
      open -a Docker 2>/dev/null || true
      printf '  Aguardando o motor ligar'
      for i in $(seq 1 60); do
        sleep 5; printf '.'
        if docker info >/dev/null 2>&1; then MOTOR_OK=1; break; fi
      done
      printf '\n'
    else FALTANDO+=("motor do Docker"); fi
  fi
else
  if docker info >/dev/null 2>&1; then MOTOR_OK=1
  elif [[ $SO_VERIFICAR -eq 0 ]]; then
    aviso "Ligando serviço do Docker..."
    $SUDO systemctl enable --now docker >/dev/null 2>&1 || $SUDO service docker start >/dev/null 2>&1 || true
    sleep 3
    if docker info >/dev/null 2>&1; then MOTOR_OK=1; fi
  else
    FALTANDO+=("motor do Docker")
  fi
  # se o usuário não tem permissão (grupo docker), tenta adicionar
  if [[ $MOTOR_OK -eq 0 && $SO_VERIFICAR -eq 0 && $EUID -ne 0 ]]; then
    if ! docker info >/dev/null 2>&1 && $SUDO docker info >/dev/null 2>&1; then
      aviso "Seu usuário não tem permissão no Docker. Adicionando ao grupo 'docker'..."
      $SUDO usermod -aG docker "$USER" 2>/dev/null || true
      aviso "Vou usar 'sudo' nesta execução. Depois de deslogar/logar, não precisará mais."
    fi
  fi
fi

# função que chama docker compose com ou sem sudo
DC="docker compose"
if [[ $SO_VERIFICAR -eq 0 ]]; then
  if ! docker info >/dev/null 2>&1; then
    if $SUDO docker info >/dev/null 2>&1; then DC="$SUDO docker compose"; fi
  fi
fi

if [[ $MOTOR_OK -eq 1 ]]; then ok "Motor do Docker ligado"; fi

# ---------- PASSO 4: Docker Compose ----------
passo "PASSO 4/7 — Docker Compose"

COMPOSE_OK=0
$DC version >/dev/null 2>&1 && COMPOSE_OK=1
if [[ $COMPOSE_OK -eq 1 ]]; then
  ok "Docker Compose disponível"
else
  FALTANDO+=("docker compose")
  if [[ $SO_VERIFICAR -eq 0 && $SO != "macos" ]]; then
    aviso "Instalando plugin docker-compose..."
    $SUDO apt-get update -y >/dev/null 2>&1 || true
    $SUDO apt-get install -y docker-compose-plugin 2>/dev/null \
      || $SUDO dnf install -y docker-compose-plugin 2>/dev/null \
      || { erro "Não consegui instalar o compose plugin. Instale manualmente."; exit 1; }
    $DC version >/dev/null 2>&1 && ok "Docker Compose instalado" || { erro "Compose ainda indisponível"; exit 1; }
  fi
fi

# ---------- resultado do modo verificação ----------
if [[ $SO_VERIFICAR -eq 1 ]]; then
  passo "RESULTADO DA VERIFICAÇÃO"
  if [[ ${#FALTANDO[@]} -eq 0 ]]; then
    ok "Tudo instalado! Pode rodar ./INSTALAR_TUDO.sh"
  else
    aviso "Falta instalar: ${FALTANDO[*]}"
    printf '  Rode ./INSTALAR_TUDO.sh para instalar automaticamente.\n'
  fi
  exit 0
fi

# ---------- PASSO 5: chaves e credenciais ----------
passo "PASSO 5/7 — Gerando chaves e login"

if [[ -f backend/.env ]]; then
  ok "backend/.env já existe (mantendo o atual)"
else
  python3 scripts/gerar_env.py
  ok "Chaves geradas (backend/.env, frontend/.env.local, CREDENCIAIS.txt)"
fi

# ---------- PASSO 6: portas livres ----------
passo "PASSO 6/7 — Verificando portas livres"

# Detecta portas ocupadas/reservadas e escolhe alternativas quando precisa,
# gravando a escolha no .env da raiz (o docker-compose lê de lá).
SAIDA_PORTAS="$(python3 scripts/ajustar_portas.py)" || {
  erro "Nenhuma porta livre encontrada. Feche o programa que usa a porta"
  erro "ou defina outra no arquivo .env da raiz (ex.: FRONTEND_PORT=3030)."
  exit 1
}
# Mensagens para humano (linhas com '#').
printf '%s\n' "$SAIDA_PORTAS" | grep '^#' | sed 's/^#//' || true

FRONTEND_PORT="$(printf '%s\n' "$SAIDA_PORTAS" | sed -n 's/^FRONTEND_PORT=//p' | head -1)"
API_PORT="$(printf '%s\n' "$SAIDA_PORTAS" | sed -n 's/^API_PORT=//p' | head -1)"
[[ -z "${FRONTEND_PORT:-}" ]] && FRONTEND_PORT=3000
[[ -z "${API_PORT:-}" ]] && API_PORT=8000
ok "Painel: http://localhost:${FRONTEND_PORT} — API: http://localhost:${API_PORT}"

# ---------- PASSO 7: subir o sistema ----------
passo "PASSO 7/7 — Subindo o NotasFlow (primeira vez demora vários minutos)"

$DC up --build -d

# Confere que TODOS os serviços ficaram de pé (antes só se checava a API).
SERVICOS="api frontend worker beat db redis"
FALTANDO=""
for s in $SERVICOS; do
  if ! $DC ps --services --status running 2>/dev/null | grep -qx "$s"; then
    FALTANDO="$FALTANDO $s"
  fi
done
if [[ -n "$FALTANDO" ]]; then
  erro "Estes serviços não subiram:$FALTANDO"
  aviso "Últimas mensagens:"
  $DC logs --tail 40 $FALTANDO || true
  aviso "Dica: se for conflito de porta, veja SOLUCAO_DE_PROBLEMAS.md."
  exit 1
fi
ok "Containers no ar"

printf '  Aguardando a API responder'
API_OK=0
for i in $(seq 1 60); do
  sleep 5; printf '.'
  if curl -fsS "http://localhost:${API_PORT}/saude" >/dev/null 2>&1; then API_OK=1; break; fi
done
printf '\n'
if [[ $API_OK -eq 1 ]]; then ok "API respondendo em http://localhost:${API_PORT}"; else aviso "API ainda subindo — aguarde 1-2 minutos."; fi

printf '  Aguardando o painel responder'
PAINEL_OK=0
for i in $(seq 1 30); do
  sleep 3; printf '.'
  if curl -fsS "http://localhost:${FRONTEND_PORT}/" >/dev/null 2>&1; then PAINEL_OK=1; break; fi
done
printf '\n'
if [[ $PAINEL_OK -eq 1 ]]; then ok "Painel respondendo em http://localhost:${FRONTEND_PORT}"; else aviso "Painel ainda subindo — aguarde 1-2 minutos."; fi

# ---------- final ----------
passo "PRONTO! NotasFlow instalado"
printf '\n  \033[1;32mPainel:\033[0m  http://localhost:%s\n' "$FRONTEND_PORT"
printf '  \033[1;32mAPI:\033[0m     http://localhost:%s/docs\n\n' "$API_PORT"

if [[ "$FRONTEND_PORT" != "3000" ]]; then
  aviso "A porta 3000 estava ocupada/reservada — o painel está na porta ${FRONTEND_PORT} (gravada no .env da raiz)."
fi

if [[ -f CREDENCIAIS.txt ]]; then
  printf '  Seu login (guarde o arquivo CREDENCIAIS.txt):\n'
  grep -E "Email:|Senha:" CREDENCIAIS.txt | sed 's/^/    /'
  printf '\n'
fi

printf '  Para parar:   %s docker compose down\n' "${SUDO}"
printf '  Para ligar:   ./INSTALAR_TUDO.sh  (ou %s docker compose up -d)\n' "${SUDO}"
printf '  Para atualizar: ./ATUALIZAR.sh\n\n'
