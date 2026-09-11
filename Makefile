.PHONY: up down logs user test build portas

up:
	-python3 scripts/ajustar_portas.py || true
	docker compose up --build -d
	@p=$$(sed -n 's/^FRONTEND_PORT=//p' .env 2>/dev/null | head -1); \
	a=$$(sed -n 's/^API_PORT=//p' .env 2>/dev/null | head -1); \
	echo ""; \
	echo "Painel:  http://localhost:$${p:-3000}"; \
	echo "API:     http://localhost:$${a:-8000}/docs"; \
	echo "Crie o usuário: make user"

down:
	docker compose down

logs:
	docker compose logs -f api worker frontend

user:
	docker compose exec api python scripts/criar_usuario_inicial.py

# Roda os testes DENTRO do container da API (a imagem inclui o pytest —
# antes o alvo falhava com "pytest: not found").
test:
	docker compose exec api pytest -q

build:
	docker compose build

# Só verifica/escolhe portas livres, sem subir nada.
portas:
	python3 scripts/ajustar_portas.py
