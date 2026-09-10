.PHONY: up down logs user test build empacotar icone desktop diagnostico

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

# --- Programa instalado (Windows) -----------------------------------------
# O .exe é montado com PyInstaller, que não faz compilação cruzada: estes
# alvos rodam no Windows (ou no runner do GitHub Actions).
empacotar:            ## gera o instalador (.exe) + ZIP portátil + latest.json
	python scripts/empacotar.py

icone:                ## regenera o ícone do programa e o favicon do painel
	python scripts/gerar_icone.py

desktop:              ## roda o programa direto do código-fonte
	cd backend && python desktop_main.py

diagnostico:          ## mostra pastas, banco e versão do programa
	cd backend && python desktop_main.py --diagnostico
