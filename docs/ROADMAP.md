# Roadmap

## Concluído

- API FastAPI multiempresa e autenticação JWT.
- PostgreSQL, Redis, Celery e Celery Beat via Docker Compose.
- Certificados A1 protegidos por cofre Fernet.
- Importação NFS-e ADN, NFe e CT-e SEFAZ.
- Controle de NSU, cooldown, retomada e exportação em massa.
- Painel Next.js responsivo.
- **v2.0 — Dashboard executivo** (`/dashboard/*`): KPIs, evolução mensal,
  quebra por tipo, top emitentes, ranking de empresas e feed de atividades.
- **v2.0 — Central de alertas** (`/alertas`): certificados, janelas SEFAZ,
  risco de distribuição, XMLs pendentes, erros e saúde do ambiente.
- **v2.0 — Fechamento mensal** (`/relatorios/fechamento` + CSV): mapa
  empresa × tipo da competência, imprimível.
- **v2.0 — Detalhe de documento** (`/documentos/detalhe/{id}`): ficha completa
  com visualizador de XML.
- **v2.0 — Experiência premium:** sidebar escura, busca global (`Ctrl+K`),
  sino de alertas, toasts, onboarding guiado e layout mobile.

## Próximos passos

- Métricas Prometheus + alertas externos (e-mail/webhook) a partir da central.
- Rotação assistida das chaves do cofre.
- Política automatizada de backup dos volumes.
- Gestão de usuários e papéis (admin/operador/leitura).
- Testes de carga e dimensionamento horizontal de workers.
