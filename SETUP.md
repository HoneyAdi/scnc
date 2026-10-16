# SCN College Accounting — Setup, Run, Test (Phase 1)

Local development setup only. No production deployment is approved.

## 1. Prerequisites

- Windows 10/11, PostgreSQL 16 (server reachable, e.g. `127.0.0.1:5434`),
  Python 3.11+ (`python --version`), Node.js 20+ (`node --version`).
- Verified during Phase 1: Python 3.11.8, Node v24.15.0, PostgreSQL 16.15.
  Toolchain pins (Python 3.12.x / Node 20 LTS) remain pending user approval (A2);
  the stack runs on the versions above with no code changes required.

## 2. Database roles (run once, as a PostgreSQL superuser or owner)

```sql
CREATE ROLE scnc_owner LOGIN PASSWORD '<strong-owner-password>';
CREATE ROLE scnc_app LOGIN PASSWORD '<strong-app-password>';
CREATE ROLE scnc_test_owner LOGIN CREATEDB PASSWORD '<strong-test-owner-password>';
CREATE ROLE scnc_app_test LOGIN PASSWORD '<strong-test-app-password>';
CREATE DATABASE scnc_dev OWNER scnc_owner;
CREATE DATABASE scnc_test OWNER scnc_test_owner;
```

Generate each password fresh (e.g. `python -c "import secrets; print(secrets.token_urlsafe(24))"`).
Never commit them. Never reuse them for production.

## 3. Backend setup

```powershell
Set-Location D:\HONEY\Projects\scnc
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt   # pinned versions
Copy-Item .env.example .env               # then fill real local values
```

`.env` keys: `ENV`, `DATABASE_URL` (app role), `ALEMBIC_DATABASE_URL` (owner role),
`STORAGE_ROOT`, `SESSION_COOKIE_NAME`, `SESSION_EXPIRE_MINUTES`.

## 4. Migrate (owner role only) + least-privilege grants

```powershell
$env:ALEMBIC_DATABASE_URL = "postgresql+psycopg://scnc_owner:<pw>@127.0.0.1:5434/scnc_dev"
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
```

Then, as the owner role, grant the app role its least privileges (CONNECT, USAGE,
DML on tables, sequence usage, plus default privileges for future tables).
The app role must NOT be able to CREATE TABLE (verified: denied).

For the test database, repeat against `scnc_test` as `scnc_test_owner`, granting to
`scnc_app_test`, with this guard set first:

```powershell
$env:ENV = "test"; $env:CONFIRM_DISPOSABLE = "YES"
```

## 5. Run the backend (from `backend/`)

```powershell
Set-Location D:\HONEY\Projects\scnc\backend
D:\HONEY\Projects\scnc\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On first start with an empty user table, a one-time setup token file is written to
`backend\storage\setup\setup_token.txt` (valid 2h, single use; file holds 0o600-style
restricted access intent — harden ACLs per local policy). Create the first Super Admin:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/setup/admin -Method Post `
  -Body (@{token="<token-from-file>"; username="<name>"; password="<12+ chars>"} | ConvertTo-Json) `
  -ContentType "application/json"
```

Health: `GET /health`, `GET /health/db`. Login: `POST /api/v1/auth/login`.

## 6. Run the tests (isolated test database only)

```powershell
Set-Location D:\HONEY\Projects\scnc
$env:ENV = "test"; $env:CONFIRM_DISPOSABLE = "YES"
$env:TEST_DATABASE_URL = "postgresql+psycopg://scnc_app_test:<pw>@127.0.0.1:5434/scnc_test"
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

The suite refuses any non-`scnc_test*` target and connects as `scnc_app_test` only.

## 7. Frontend

```powershell
Set-Location D:\HONEY\Projects\scnc\frontend
npm install
npm run build    # TypeScript + production build check
npm run dev -- --port 5173 --host 127.0.0.1   # local dev server
```

Set `VITE_API_BASE` (default `http://127.0.0.1:8000`) if the API runs elsewhere.

## 8. Backup note (dev)

```powershell
pg_dump -U scnc_owner -h 127.0.0.1 -p 5434 -Fc scnc_dev -f backups\scnc_dev.dump
```

Production backup/restore procedures arrive with Phase 9. No production use is approved.

## 9. Security notes

- HTTP is NEVER safe for production credentials. Production must terminate TLS
  and set `ENV=prod` with `SESSION_SECURE_COOKIE=true`; the backend refuses to
  start otherwise. Localhost development (`ENV=dev`) stays on plain HTTP.
- Browser mutations additionally require a matching `Origin`/`Referer` host
  (mismatches are rejected with 403); non-browser API clients omit these headers.
- The login response carries no session token — the HttpOnly cookie is the only
  browser credential. The one-time setup token exists only in
  `backend\storage\setup\setup_token.txt` (restricted file, never logged).
