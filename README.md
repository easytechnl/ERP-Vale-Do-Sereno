# ERP Vale do Sereno — Divisão de Custos (EasyTech)

Este projeto inclui o módulo **Divisão de Custos** (antigo “Rateio”), onde você:
- cadastra **despesas** manualmente (com repetição mensal/bi-mensal/anual),
- mantém **construtoras** (base automática + cadastro manual),
- gera a **divisão** de custos por **percentual** (0,12 = 12%) e
- exporta **CSV** e **PDFs** (1 por construtora + ZIP).

> Rodapé/assinatura: **"Desenvolvido EasyTech — Facilitando a tecnologia"**

---

## 1) Instalação (PowerShell)

Na raiz do projeto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> Este projeto está validado em **Python 3.12**. Evite criar a `.venv` com Python 3.14, pois dependências nativas como `pydantic-core`, `psycopg2`, `greenlet` e `httptools` precisam combinar exatamente com a versão do interpretador.

---

## 2) Configurar banco (.env)

Exemplo (PostgreSQL):

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/erp_finance
SECRET_KEY=change-me-please
```

---

## 3) Criar tabelas

> Use **sempre** o modo módulo (evita erro `No module named 'app'`).

```powershell
python -m app.scripts.init_db
```

---

## 4) Rodar o servidor

```powershell
python run_dev.py
# (ou, sem ativar a venv: .\.venv\Scripts\python.exe run_dev.py)
# para porta customizada, ex.: 8010
python run_dev.py --port 8010
```

Acesse: `http://127.0.0.1:8000`

---

## 5) Módulo Divisão de Custos

- Tela: `/divisao-custos`
- Compatibilidade (rota antiga): `/rateio` → redireciona

### Percentuais (base)
Os percentuais são carregados automaticamente do arquivo:

`app/assets/percentual.docx`

Formato: **0,12 = 12%**.

---

## 6) Comandos úteis no psql

Entre no psql:

```powershell
psql -U postgres
```

Comandos:

```sql
\l              -- lista bancos
\c erp_finance   -- conecta no banco
\dt             -- lista tabelas
\dt rateio*     -- lista tabelas do módulo
\d rateio_companies
\d rateio_expenses
SELECT COUNT(*) FROM rateio_companies;
SELECT COUNT(*) FROM rateio_expenses;
```

---

## Observação sobre pastas com espaço

Se a pasta do projeto tiver espaço no nome, **não tem problema**, mas prefira sempre rodar:

```powershell
python run_dev.py
```

(Esse entrypoint usa `if __name__ == "__main__"` e `freeze_support()` para evitar erro de spawn no Windows com `--reload`.)
