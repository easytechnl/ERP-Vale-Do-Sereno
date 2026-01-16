# ERP Financeiro (MVP) — FastAPI + HTML + Tailwind + JS (sem Docker)

Este projeto é um **starter kit funcional** para iniciar o ERP financeiro descrito (contas a receber, boletos em lote, CNAB stub, conciliação OFX stub, fechamento mensal, envio e-mail em lote).
Ele já sobe com telas HTML (Jinja2), APIs internas (JSON) e banco via SQLAlchemy.

## 1) Requisitos
- Python 3.11+ (recomendado 3.12)
- (Opcional) PostgreSQL (recomendado para produção)

## 2) Instalação (Windows / Linux)
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Windows (ou crie manualmente)
# Linux/Mac: cp .env.example .env
```

## 3) Banco de dados
Por padrão, o sistema usa SQLite local para você rodar imediatamente.
Para Postgres, defina `DATABASE_URL` no `.env`.

### PostgreSQL no Windows (sem dor de cabeça)
Para evitar erros de `libpq`/`psycopg` no Windows, este projeto inclui **psycopg2-binary**.
Use um `DATABASE_URL` assim:

```env
DATABASE_URL=postgresql+psycopg2://USUARIO:SENHA@localhost:5432/NOME_DO_BANCO
```

Se você preferir ficar no SQLite por enquanto, não precisa configurar nada.

### Criar tabelas (rápido / MVP)
```bash
python -m app.scripts.init_db
python -m app.scripts.create_admin
```

## 4) Rodar o servidor
```bash
uvicorn app.main:app --reload
```
Acesse:
- http://127.0.0.1:8000/login

## 5) Usuário admin
- Configure no `.env`:
  - `ADMIN_EMAIL`
  - `ADMIN_PASSWORD`
Depois rode:
```bash
python -m app.scripts.create_admin
```

## 6) O que já está pronto (MVP)
- Login (sessão/cookie) + perfis (admin/gestor/financeiro)
- Cadastros mínimos:
  - Clientes (sacados)
- Contas a receber:
  - Geração de parcelas por competência (YYYY-MM)
- Boletos:
  - Geração em lote (PDF) e listagem
  - Remessa CNAB **stub** (gera arquivo .txt no storage)
  - Retorno CNAB **stub** (importa arquivo e baixa parcelas/boletos de exemplo)
- Conciliação:
  - Importação OFX/CSV **stub** (estrutura pronta; OFX via `ofxparse`)
  - Tela de “espelho do extrato” e conciliação manual básica
- Fechamento mensal:
  - Gera PDF do demonstrativo/entradas-saídas (ReportLab) e “congela” a competência
- E-mail em lote:
  - Template básico + disparo SMTP + log de envios (com anexos)

## 7) CNAB e OFX (como evoluir)
- CNAB: implemente adapters reais em `app/modules/boletos/cnab/adapters/`
- OFX: o parser está em `app/modules/conciliacao/ofx_service.py` (estrutura pronta)

## 8) Estrutura
Veja `app/modules/` para cada domínio (receber, boletos, conciliacao, relatorios, email, admin).

---
Este starter é propositalmente simples para acelerar o início **sem Docker**.
