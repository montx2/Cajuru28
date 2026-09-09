.PHONY: up down logs user test build

up:
	docker compose up --build -d
	@echo ""
	@echo "API:     http://localhost:8000/docs"
	@echo "Painel:  http://localhost:3000"
	@echo "Crie o usuário: make user"

down:
	docker compose down

logs:
	docker compose logs -f api worker frontend

user:
	docker compose exec api python scripts/criar_usuario_inicial.py

test:
	cd backend && PYTHONPATH=. pytest -q

build:
	docker compose build
