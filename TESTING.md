# TESTING.md â€” SCN College Accounting Application (Canonical, Rev 5)

**Status:** Phase 1+2+3 partial (2026-10-17): 76 pytest cases pass on an isolated PG16 test DB (auth, RBAC, audit, security/CSRF, atomicity, concurrency, periods, accounts, draft vouchers/journal lines); posting/approval/reversal suites remain Planned.
**Version:** Phase 0 Rev 5 â€” **Date:** 2026-10-15 (UTC)
**Governs with:** `README.md`, `plan.md`, `ARCHITECTURE.md`, `DATABASE.md`, `PERMISSIONS.md`

## 1. Strategy

Pyramid: unit (services/math) > API (HTTPX + authZ matrix) > integration (PostgreSQL + storage) > pilot E2E. Money paths use `Decimal`; rounding/boundary cases included. Report tests parse PDF/Excel content vs on-screen JSON, not status codes alone. Every suite states its phase gate from plan.md.

Concurrency tests assert outcomes that must hold under ANY interleaving and, where two writers must provably overlap, rendezvous deterministically through a test-only hook (`accounting_service._create_barrier`: `None` and inert in production) instead of relying on thread timing. Real-commit tests delete only the rows they create and never empty shared tables; where a test needs a globally clean system it aborts on unexpected committed data rather than deleting it. Audit rows are cleaned by `actor_id` scope only (never by action pattern), and `create_period`/`create_account` translate ONLY the expected duplicate-code unique violation (server SQLSTATE `23505` on the named `uq_financial_periods_code`/`uq_accounts_code` constraint) into the same clean 400 a sequential caller sees; every other `IntegrityError` is rolled back and propagated to the normal error path (no SQL or internals leaked).

## 2. Reproducible Windows setup (normative; pinned in Phase 1)

Prerequisites (64-bit Windows 10/11): Python **3.12.x** (from python.org, "Add to PATH" checked), PostgreSQL **16.x** (`psql` in PATH), Node **20 LTS** (frontend, Phase 1+), Git. Versions recorded with `python --version`, `psql --version`, `node --version` in every test report.

**Safety rules (mandatory):** destructive database commands MUST fail safe. The caller must configure the test environment explicitly â€” scripts MUST NOT set `ENV=test` themselves. Every destructive step aborts unless ALL hold: `$env:ENV -eq "test"` (pre-set by the caller, verified not set by the script), role names are exactly `scnc_test_owner` (owner steps) and `scnc_app_test` (test-runner steps) â€” arbitrary values abort before any database command, the target database name matches the disposable pattern `^scnc_test(_[a-z0-9]+)?$`, the name is NOT in the denylist (`scnc`, `scnc_prod`, `postgres`, `template1`, anything not starting with `scnc_test`), the target host is in the explicit allowlist `TEST_DB_HOST_ALLOWLIST` (loopback-aware on both sides; non-loopback must match literally), the LIVE connection target is verified by connecting to the target itself and querying `current_database()` + `current_user` (never by pattern-matching the connection string alone â€” abort on any mismatch), pre-drop existence + ownership is verified (foreign owner aborts; absent target takes the creation path explicitly), and explicit confirmation `$env:CONFIRM_DISPOSABLE -eq "YES"` is set for that command. Credentials: `Invoke-GuardedPsql` is the SOLE writer of `Env:\PGPASSWORD` â€” no other statement in this procedure assigns or removes it â€” restoring any prior value in a per-call `finally` block; a baseline snapshot (`Save-EnvBaseline @('ALEMBIC_DATABASE_URL','DATABASE_URL')`, `PGPASSWORD` deliberately excluded) taken before any assignment lets each URL scope's `finally` cleanup (`Restore-EnvBaseline`) RESTORE pre-existing caller values instead of deleting them, removing only values this procedure created â€” including on exceptions and failed commands; connection strings are built with URL-encoded credentials (`Build-SafeDbUrl`) so special characters cannot redirect the connection. No passwords appear in commands, logs, or error messages. Every command's exit code is checked immediately and failure aborts. Three separated roles: `scnc_test_owner` (database creation + migrations/DDL only), `scnc_app_test` (API/app tests â€” DML only, explicitly NO DDL: no `CREATEDB`, no `CREATEROLE`, does not own the test DB), and `scnc_reversal_invoker` (approved reversal path only, DATABASE.md Â§3 â€” never by the test runner except in suite 1C denial/authorized-path tests). The superuser/postgres account is never used.

```powershell
# 0. Clone and enter (paths below assume D:\HONEY\Projects\scnc)
Set-Location D:\HONEY\Projects\scnc

# 1. Backend venv + dependencies (exact pins live in backend\requirements.txt from Phase 1)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt

# 2. OWNER step â€” create/migrate the disposable test DB (role: scnc_test_owner).
#    Caller pre-sets ALL of these (script never sets ENV itself). Do NOT commit real passwords.
#    Required: ENV=test, TEST_DB_HOST, TEST_DB_HOST_ALLOWLIST, TEST_DB_OWNER,
#              TEST_DB_OWNER_PASSWORD, TEST_DB_APP, TEST_DB_APP_PASSWORD, TEST_DB_NAME, CONFIRM_DISPOSABLE
#    TEST_DB_HOST_ALLOWLIST example: "localhost,127.0.0.1" (comma-separated literal connection
#    hosts; loopback aliases localhost/127.0.0.1/::1 are treated as one equivalent group).
function Normalize-Host([string]$H) {
  # Loopback aliases are one equivalent group so valid loopback configs work without
  # weakening the allowlist; every non-loopback host must match exactly (see below).
  $loopback = @('localhost','127.0.0.1','::1')
  if ($loopback -contains $H.Trim().ToLower()) { return 'loopback' }
  return $H.Trim().ToLower()
}
function Assert-DisposableTarget([string]$DbName, [string]$HostName) {
  if ($env:ENV -ne "test") { throw "Refusing: ENV must be pre-set to 'test' by the caller (current: '$env:ENV'). The script will not set it. Aborting." }
  if ($env:CONFIRM_DISPOSABLE -ne "YES") { throw "Refusing: CONFIRM_DISPOSABLE must be 'YES' for destructive test-DB commands. Aborting." }
  if ($DbName -notmatch '^scnc_test(_[a-z0-9]+)?$') { throw "Refusing: '$DbName' is not a disposable test DB name (must match ^scnc_test(_[a-z0-9]+)?$). Aborting." }
  $deny = @('scnc','scnc_prod','postgres','template1')
  if ($deny -contains $DbName) { throw "Refusing: '$DbName' is deny-listed. Aborting." }
  # Normalization applies to BOTH sides: each allowlist entry is normalized before comparison,
  # so `localhost` listed covers `127.0.0.1`/`::1` and vice versa â€” loopback only.
  $allow = @($env:TEST_DB_HOST_ALLOWLIST -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
  $normAllow = @($allow | ForEach-Object { Normalize-Host $_ })
  if ($normAllow -notcontains (Normalize-Host $HostName)) { throw "Refusing: host '$HostName' is not covered by TEST_DB_HOST_ALLOWLIST ('$env:TEST_DB_HOST_ALLOWLIST', loopback-aware). Aborting." }
  if ((Normalize-Host $HostName) -ne 'loopback' -and ($allow -notcontains $HostName.Trim())) { throw "Refusing: non-loopback host '$HostName' must appear literally in TEST_DB_HOST_ALLOWLIST (normalization never widens non-loopback). Aborting." }
}
function Test-HostMatch([string]$LiveSrv, [string]$ExpectedHost) {
  # Fail-closed host comparison. NEVER a bare literal string compare of a hostname against an IP:
  # a valid non-loopback hostname (e.g. dbserver.lan â†’ 192.168.1.10) must not be rejected, and an
  # unexpected server must never be accepted. Any error (incl. DNS failure) returns $false.
  try {
    if ($LiveSrv -eq 'socket') { return ((Normalize-Host $ExpectedHost) -eq 'loopback') }
    if ($LiveSrv.Trim().ToLower() -eq $ExpectedHost.Trim().ToLower()) { return $true }
    if ((Normalize-Host $LiveSrv) -eq 'loopback' -and (Normalize-Host $ExpectedHost) -eq 'loopback') { return $true }
    $resolved = [System.Net.Dns]::GetHostAddresses($ExpectedHost) | ForEach-Object { $_.ToString() } | Sort-Object -Unique
    if ($resolved -contains $LiveSrv.Trim()) { return $true }
    return $false
  } catch { return $false }
}
function Invoke-GuardedPsql([string]$Role, [string]$Password, [string]$HostName, [string]$Db, [string]$Sql) {
  # SOLE place that writes Env:\PGPASSWORD. A helper must never remove a credential owned by its
  # caller, so this helper saves any pre-existing value and restores it in a finally block â€” the
  # credential lifetime is confined to this call even on exceptions or command failure. $Password
  # is never echoed, never interpolated into messages, and never logged. Exit code checked here:
  # every caller inherits immediate abort-on-failure without needing its own check.
  $hadPrior = Test-Path Env:\PGPASSWORD
  $prior = $null
  if ($hadPrior) { $prior = $env:PGPASSWORD }
  $env:PGPASSWORD = $Password
  try {
    $out = psql -U $Role -h $HostName -d $Db -tA -c $Sql
    if ($LASTEXITCODE -ne 0) { throw "Refusing: psql failed (exit $LASTEXITCODE) for role '$Role' on database '$Db'. Aborting before any further step." }
    return $out
  } finally {
    if ($hadPrior) { $env:PGPASSWORD = $prior } else { Remove-Item Env:\PGPASSWORD }
  }
}
function Format-UrlHost([string]$H) {
  # IPv6 literals MUST be bracketed in URLs: an unbracketed ::1 produces
  # "postgresql+psycopg://user:pass@::1:5432/db", which misparses the host/port boundary.
  # Brackets apply to the URL ONLY â€” psql -h and the allowlist keep the raw form (::1),
  # and Test-HostMatch compares post-parse values, so validation is unaffected.
  $t = $H.Trim()
  if ($t.StartsWith('[') -and $t.EndsWith(']')) { return $t }
  if ($t.Contains(':')) { return "[$t]" }
  return $t
}
function Build-SafeDbUrl([string]$User, [string]$Password, [string]$HostName, [string]$Db) {
  # Credentials with special characters (@ : / ? # etc.) must be URL-encoded: raw interpolation
  # would silently connect to the WRONG host/database. Both user and password are encoded.
  $u = [System.Uri]::EscapeDataString($User)
  $p = [System.Uri]::EscapeDataString($Password)
  $h = Format-UrlHost $HostName
  return "postgresql+psycopg://${u}:$p@${h}:5432/$Db"
}
function Assert-LiveTarget([string]$ExpectedDb, [string]$ExpectedRole, [string]$PgPassword, [string]$ExpectedHost) {
  # Connect to the TARGET database itself and ask the server who/where we are.
  # Connection-string pattern matching alone is NOT sufficient. Credential handling is delegated
  # to Invoke-GuardedPsql, which restores the caller's environment in a finally block.
  $row = Invoke-GuardedPsql -Role $ExpectedRole -Password $PgPassword -HostName $ExpectedHost -Db $ExpectedDb -Sql "SELECT current_database() || '|' || current_user || '|' || COALESCE(inet_server_addr()::text,'socket');"
  $liveDb, $liveRole, $liveSrv = $row.Trim() -split '\|'
  if ($liveDb -ne $ExpectedDb) { throw "Refusing: live database '$liveDb' != expected '$ExpectedDb'. Aborting." }
  if ($liveRole -ne $ExpectedRole) { throw "Refusing: live role '$liveRole' != expected '$ExpectedRole'. Aborting." }
  if (-not (Test-HostMatch $liveSrv $ExpectedHost)) { throw "Refusing: live server '$liveSrv' does not verify against expected host '$ExpectedHost' (fail-closed DNS/loopback-aware match). Aborting." }
}
function Assert-ExpectedRoles() {  # Environment values must not silently substitute unexpected roles: the owner and app test roles
  # are FIXED names. Anything else aborts before any database command runs.
  if ($env:TEST_DB_OWNER -ne 'scnc_test_owner') { throw "Refusing: TEST_DB_OWNER must be exactly 'scnc_test_owner' (current: '$($env:TEST_DB_OWNER)'). Aborting." }
  if ($env:TEST_DB_APP -ne 'scnc_app_test') { throw "Refusing: TEST_DB_APP must be exactly 'scnc_app_test' (current: '$($env:TEST_DB_APP)'). Aborting." }
}
$script:ownedEnv = @{}
function Save-EnvBaseline([string[]]$Names) {
  # Snapshot caller-owned environment BEFORE this procedure assigns anything, so cleanup can
  # restore pre-existing values instead of deleting them. Called once, before any assignment.
  foreach ($n in $Names) {
    if (-not $script:ownedEnv.ContainsKey($n)) {
      if (Test-Path "Env:\$n") { $script:ownedEnv[$n] = @{ existed = $true; value = (Get-Item "Env:\$n").Value } }
      else { $script:ownedEnv[$n] = @{ existed = $false; value = $null } }
    }
  }
}
function Restore-EnvBaseline([string[]]$Names) {
  # Cleanup counterpart: pre-existing caller values are RESTORED (never deleted); only values this
  # procedure itself created are removed. Safe to call on exceptions and failed commands.
  foreach ($n in $Names) {
    if ($script:ownedEnv.ContainsKey($n)) {
      $s = $script:ownedEnv[$n]
      if ($s.existed) { Set-Item -Path "Env:\$n" -Value $s.value }
      else { Remove-Item "Env:\$n" -ErrorAction SilentlyContinue }
    } else { Remove-Item "Env:\$n" -ErrorAction SilentlyContinue }
  }
}

if (-not $env:TEST_DB_NAME) { throw "TEST_DB_NAME is not set. Aborting (caller must set it)." }
Assert-ExpectedRoles  # fixed role names first: no silent substitution, before any database command
Save-EnvBaseline @('ALEMBIC_DATABASE_URL','DATABASE_URL')  # snapshot caller state before we assign anything (PGPASSWORD is excluded: Invoke-GuardedPsql is its sole writer and restores it per call)
Assert-DisposableTarget $env:TEST_DB_NAME $env:TEST_DB_HOST
# All psql traffic below goes through Invoke-GuardedPsql (sole PGPASSWORD owner, per-call
# try/finally). No direct `psql` invocations and no direct $env:PGPASSWORD assignments appear below,
# so no outer PGPASSWORD cleanup exists or is needed here â€” there is nothing for it to clean.
# (a) Verify the MAINTENANCE connection separately: who/where are we, before anything destructive.
Assert-LiveTarget -ExpectedDb 'postgres' -ExpectedRole $env:TEST_DB_OWNER -PgPassword $env:TEST_DB_OWNER_PASSWORD -ExpectedHost $env:TEST_DB_HOST
# (b) Safe existence + ownership check (read-only). The name is already restricted by the disposable
#     pattern to lowercase letters/digits/underscore, so interpolating it here is injection-safe by
#     construction; any pattern bypass would have aborted in Assert-DisposableTarget above.
$ownerRow = Invoke-GuardedPsql -Role $env:TEST_DB_OWNER -Password $env:TEST_DB_OWNER_PASSWORD -HostName $env:TEST_DB_HOST -Db 'postgres' -Sql "SELECT COALESCE(pg_get_userbyid(datdba),'?') FROM pg_database WHERE datname = '$($env:TEST_DB_NAME)';"
$ownerRow = $ownerRow.Trim()
if ($ownerRow -eq '') {
  # Target does not exist: this EXPECTED condition is NOT a successful verification â€” it only selects
  # the creation path. Server, role, name-pattern, and allowlist were verified in (a); ownership will
  # be asserted after CREATE (new DB must be owned by the expected owner).
  Write-Output "Target '$($env:TEST_DB_NAME)' absent â€” creation path (no pre-drop identity to verify)."
} else {
  if ($ownerRow -ne $env:TEST_DB_OWNER) { throw "Refusing: existing target '$($env:TEST_DB_NAME)' is owned by '$ownerRow', not expected owner '$($env:TEST_DB_OWNER)'. Aborting â€” will not drop another role's database." }
  Write-Output "Target '$($env:TEST_DB_NAME)' exists and is owned by expected owner â€” verified, proceeding to drop."
  Invoke-GuardedPsql -Role $env:TEST_DB_OWNER -Password $env:TEST_DB_OWNER_PASSWORD -HostName $env:TEST_DB_HOST -Db 'postgres' -Sql "DROP DATABASE `"$($env:TEST_DB_NAME)`";"
}
Invoke-GuardedPsql -Role $env:TEST_DB_OWNER -Password $env:TEST_DB_OWNER_PASSWORD -HostName $env:TEST_DB_HOST -Db 'postgres' -Sql "CREATE DATABASE `"$($env:TEST_DB_NAME)`" OWNER `"$($env:TEST_DB_OWNER)`";"
# (c) Post-creation identity check: connect to the NEW target itself and verify database + owner role.
Assert-LiveTarget -ExpectedDb $env:TEST_DB_NAME -ExpectedRole $env:TEST_DB_OWNER -PgPassword $env:TEST_DB_OWNER_PASSWORD -ExpectedHost $env:TEST_DB_HOST
# No outer PGPASSWORD cleanup here by design: the helper above restored its own per-call value.
# Least-privilege app test role (`scnc_app_test`: CONNECT + DML on app tables only; explicitly NO DDL â€”
# no CREATEDB/CREATEROLE, does not own the test DB; no access to non-allowlisted hosts) is granted by
# Phase 1 migration/seed scripts. Suite 7 asserts CREATE TABLE as scnc_app_test is denied.

# 3. OWNER step â€” migrate the test DB to head (connects as scnc_test_owner, never as app role).
#    Contract (Phase 1 MUST implement, verified by suite 7): backend/alembic/env.py reads
#    ALEMBIC_DATABASE_URL and ONLY that variable whenever ENV=test (it aborts if unset); it MUST NOT
#    silently fall back to DATABASE_URL, to alembic.ini's sqlalchemy.url, or to any compiled-in/default
#    URL â€” any fallback path that could resolve to a production database is forbidden and fails review.
#    alembic.ini ships a placeholder URL only (e.g. driver://placeholder-invalid â€” never a real server).
#    Before running any migration, env.py asserts server-side, against the LIVE connection: ENV=test,
#    current_user = expected owner, current_database matches ^scnc_test(_[a-z0-9]+)?$, host allowlisted
#    (same loopback-aware, DNS-resolving match as Test-HostMatch), and aborts otherwise. The steps below
#    assert the same client-side first, so a misconfigured env.py can never silently migrate the wrong DB.
#    URL-encoding (Build-SafeDbUrl) guarantees credentials with special characters cannot silently
#    redirect the connection to the wrong host/database.
$env:ALEMBIC_DATABASE_URL = Build-SafeDbUrl -User $env:TEST_DB_OWNER -Password $env:TEST_DB_OWNER_PASSWORD -HostName $env:TEST_DB_HOST -Db $env:TEST_DB_NAME
# $env:ALEMBIC_DATABASE_URL must never be printed or logged.
try {
Assert-LiveTarget -ExpectedDb $env:TEST_DB_NAME -ExpectedRole $env:TEST_DB_OWNER -PgPassword $env:TEST_DB_OWNER_PASSWORD -ExpectedHost $env:TEST_DB_HOST
alembic -c backend\alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed (exit $LASTEXITCODE). Aborting before tests." }
} finally { Restore-EnvBaseline @('ALEMBIC_DATABASE_URL') }  # restore caller value if pre-existing, else remove ours

# 4. APP step â€” run the suites (connects as scnc_app_test, the normal application role).
$env:DATABASE_URL = Build-SafeDbUrl -User $env:TEST_DB_APP -Password $env:TEST_DB_APP_PASSWORD -HostName $env:TEST_DB_HOST -Db $env:TEST_DB_NAME
$env:STORAGE_ROOT = "D:\HONEY\Projects\scnc\.test_storage"
try {
Assert-ExpectedRoles  # re-assert fixed role names on the test path too: no silent substitution
Assert-LiveTarget -ExpectedDb $env:TEST_DB_NAME -ExpectedRole $env:TEST_DB_APP -PgPassword $env:TEST_DB_APP_PASSWORD -ExpectedHost $env:TEST_DB_HOST
pytest backend\tests -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed (exit $LASTEXITCODE). See log; fix before any gate passes." }
# focused suites (same app-role connection; each fixture re-asserts the live target first):
pytest backend\tests\test_posting_invariants.py backend\tests\test_idempotency.py backend\tests\test_allocations_concurrency.py -v
if ($LASTEXITCODE -ne 0) { throw "focused suite failed (exit $LASTEXITCODE). Aborting." }
pytest backend\tests\test_rbac.py backend\tests\test_reconciliation.py -v
if ($LASTEXITCODE -ne 0) { throw "focused suite failed (exit $LASTEXITCODE). Aborting." }
pytest backend\tests\test_voucher_line_immutability.py backend\tests\test_draft_edit.py backend\tests\test_reversal_auth.py backend\tests\test_backup_restore.py -v
if ($LASTEXITCODE -ne 0) { throw "focused suite failed (exit $LASTEXITCODE). Aborting." }
} finally { Restore-EnvBaseline @('DATABASE_URL') }  # restore caller value if pre-existing, else remove ours â€” including on failure
```

Frontend (Phase 1+): `npm ci` in `frontend\`; `npm test`; Playwright LAN smoke only against a disposable instance. Each run starts from a fresh `scnc_test` schema (`alembic upgrade head` after drop) and DEMO seed tagged `is_demo=true`; production data and DEMO data never share a database.

## 3. Required acceptance suites (suite 4 Authorization executed at the Phase 2 gate and a draft-voucher save suite executed at the Phase 3 partial gate - see section 5; the posting/approval/reversal suites remain Planned; evidence required to pass a gate)

1. **Financial invariants (Phase 3 gate):** unbalanced journal rejected; single-line voucher rejected; one-sided-line CHECK holds; Î£Dr=Î£Cr>0 per posted voucher (DB dump assertion); TB sums to zero; P&L/BS agree to ledger; closed-period posting rejected; backdated-to-closed rejected; reversal creates linked negating voucher, original untouched.
1A. **Voucher-line immutability (Phase 3 gate; all as the normal `scnc_app_test` role, never owner/superuser):** (a) direct `INSERT` of a voucher or line as app role â†’ denied by grant (all writes go through functions); (b) `INSERT` a new line into a `posted` voucher â†’ rejected; (c) `UPDATE` a line amount/narration/account on a `posted` voucher â†’ rejected; (d) `DELETE` a line from a `posted` voucher â†’ rejected; (e) `UPDATE` any column of a `posted` voucher row (narrative, dates, number) except the narrow posting/reversal transitions â†’ rejected; (f) direct `status` flip by raw SQL as app role â†’ rejected; (g) the single-transaction posting sequence itself (`fn_post_voucher`: lock â†’ validate complete journal â†’ subledger writes â†’ flip to `posted`, per DATABASE.md Â§3) succeeds and afterwards (b)â€“(f) are rejected; (h) authorized reversal **through the service** (with `vouchers.reverse` + bound pair approval) succeeds and posts a linked negating voucher while original lines are byte-identical. Each negative case asserts the database error/rollback AND that row counts and sums are unchanged.
1B. **Draft-edit confinement (Phase 3 gate; as `scnc_app_test` unless stated):** (a) authorized maker edits a `draft` voucher/line **through the draft functions with their own live session token** (DATABASE.md Â§2B) â†’ succeeds with audit attributed to the resolved user; (b) same edit after the voucher is `posted` â†’ rejected; (c) edit by a session lacking the module permission â†’ 403, no rows changed; (d) direct SQL `INSERT`/`UPDATE`/`DELETE` on vouchers/lines as app role (bypassing the functions) â†’ rejected by grant; (e) function call with a mismatched `p_actor` (not the token's owner) â†’ rejected; (f) call with a revoked/unknown/expired session token, or with no token â†’ rejected; (g) one session's token used with another user's `p_actor` â†’ rejected (impersonation tripwire).
1C. **Reversal-function authorization (Phase 3 gate):** (a) direct `SELECT fn_apply_reversal(â€¦)` as `scnc_app_test` â†’ denied (`permission denied`, no state change); (b) membership denial asserted separately per role â€” `pg_has_role('scnc_app_test','scnc_reversal_invoker','MEMBER')` is false, and separately `pg_has_role('scnc_app','scnc_reversal_invoker','MEMBER')` is false â€” and `SET ROLE scnc_reversal_invoker` as `scnc_app_test` â†’ denied (no membership path exists for the test role); (c) invoker-credential call with unapproved/missing approval proof, wrong state (original not `posted`, reversing voucher unbalanced or already linked) â†’ rejected with rollback; (d) approval bound to DIFFERENT vouchers, expired/consumed approval ref, or self-approved reversal (approver == requester/checker) â†’ rejected with rollback; (e) invocation with a revoked/unknown session token â†’ rejected (actor binding); (f) call attempting to change amounts/accounts/lines (not just the single flag) â†’ rejected (function has no such DML); (g) static test: `REVERSAL_DATABASE_URL` referenced only in the reversal service module (credential-scope confinement); (h) enforceable proxies for the grant/trigger layer: `has_table_privilege('scnc_app_test','vouchers'/'voucher_lines'/'audit_log','UPDATE,DELETE')` all false (and likewise for the invoker role), both triggers present and enabled, function owner is the migration role with fixed `search_path` and EXECUTE grantees exactly `{scnc_reversal_invoker}` â€” hostile-superuser bypass is a documented limitation (DATABASE.md Â§2A.5: controlled + detected, not prevented), not a testable behavior from a least-privilege role; (i) full authorized service reversal via the invoker connection (bound approval + actor + states + balance re-validated in-txn) â†’ succeeds: new negating voucher posted, original `postedâ†’reversed` exactly once, approval consumed (reuse rejected), original lines byte-identical, audit row written, double-reversal rejected; (j) direct `INSERT INTO audit_log` as `scnc_reversal_invoker` AND as `scnc_app_test` â†’ both denied by grant (no broader privileges granted to compensate); authorized reversal â†’ exactly one matching audit row committed atomically with the flag flips, and a failed/aborted reversal leaves zero new audit rows (asserted by audit-row diff before vs after).
1D. **Save / edit-approval / posting lifecycle (Phase 3 gate; canonical states in DATABASE.md Â§2):** (1) accountant saves a voucher via creation + `fn_submit_voucher` â†’ status `pending_approval`, NOT posted; (2) the saved voucher's lines are excluded from GL/TB/Income-Expenditure/Balance-Sheet queries (report totals unchanged vs pre-save snapshot); (3) creator attempts direct edit of the saved voucher â†’ denied by grant/trigger; (4) edit request opened then REJECTED via `fn_decide_edit_request` â†’ voucher back to `pending_approval` byte-identical (version/hash unchanged); (5) edit request AUTHORIZED + applied via `fn_apply_authorized_edit` â†’ ONLY the whitelisted authorized changes applied (injected extra changes ignored/rejected), version incremented, voucher returned to `pending_approval`, before/after audit written; (6) after edit authorization, voucher is still NOT posted (GL unchanged; `fn_post_voucher` without a posting approval aborts); (7) authorized approver records a bound posting approval + `fn_post_voucher` on a valid balanced voucher â†’ `posted`, GL/TB move by exactly the journal amounts; (8) each of these is rejected with rollback: unbalanced journal, unauthorized actor (no permission), closed-period voucher, illegal transition â€” an ORDINARY draft voucher must never bypass posting approval, so `draftâ†’posted` with no bound reversal approval, `pending_approvalâ†’posted` skipping approval, and `postedâ†’pending_approval` are all rejected; the SOLE `draftâ†’posted` exception is the reversing/adjusting leg inside `fn_apply_reversal` (or the adjustment linker) with a bound, unconsumed approval naming that exact reversing voucher plus all in-function checks â€” tested positive (authorized reversal posts its reversing leg) and negative (same transition by direct SQL, or with missing/consumed/cross-voucher approval, is rejected), with direct SQL status updates denied to app and invoker roles throughout; (9) creator attempts self-approval of own voucher (posting or edit) with segregation-of-duties enforced â†’ rejected; (10) direct `UPDATE vouchers SET status=â€¦` and any direct financial-table write as app/invoker roles â†’ denied by grant; (11) posting and reversal posting each commit voucher + lines + subledger + approval-consumption + audit atomically (concurrency harness: no partial state observable); (12) `UPDATE`/`DELETE` on `posted` voucher/lines via ordinary application operations â†’ rejected (grants + triggers); corrections only via linked reversal/adjustment with own approval + audit; (13) concurrent edit requests on the same voucher (second request while one is open â†’ rejected; approval after the voucher changed under review â†’ stale-abort on version/hash mismatch; parallel posting attempts with one idempotency key â†’ exactly one posting); (14) failed posting (e.g. period closed mid-flight, allocation shortfall) leaves NO partial ledger entries, NO consumed approval, and the voucher status unchanged â€” asserted by row-count/sum/balance comparison before vs after.
2. **Duplicate submissions (Phases 3/4/6 gate):** same `Idempotency-Key` replayed sequentially and in parallel (â‰¥10 threads) yields exactly one posted voucher/receipt/payment; second response returns original number, no new rows. Cross-module with kind-specific keys (DATABASE.md Â§6): the SAME UTR submitted through college-fee AND hostel paths with DIFFERENT entered dates/banks â†’ exactly one posting, the other rejected (UTR identity is bank/date-agnostic by design); the same cheque number on DIFFERENT banks â†’ both post (independent events); the same cheque + bank + account re-entered with a different date â†’ rejected (one leaf, one event); the same cheque number on the SAME bank but DIFFERENT accounts both post (account-level identity `ux_src_chq_acct`); cheque intake with unknown account follows the documented exception only (`ux_src_chq_bank` key `(kind, bank_id, ref_normalized)` with NULL account, checker-confirmed, exceptions register); unknown-account same bank + same normalized number entered with a DIFFERENT event date is BLOCKED (not accepted as distinct merely for differing dates); identical cash slip numbers from DIFFERENT collection points or FYs â†’ both post; `other`-kind refs collide only on full match (documented fallback limitation; intake classification tested separately). NULL-scope hardening (per kind, incl. concurrency): cash slip with NULL collection point or NULL FY â†’ rejected by CHECK; cheque/DD with NULL `bank_id` â†’ rejected; `other` with NULL FY (or any scope column set) â†’ rejected; UTR row with ANY scope column set (`collection_point_id`, `fy_id`, or `bank_id` non-NULL) â†’ rejected by CHECK. Date/metadata clarification: `event_date` is required on every row but is NOT part of UTR, cheque, or cash identity â€” so the same normalized UTR recorded with a DIFFERENT date still collides on `ux_src_utr` and the resubmission is rejected, while variant recorded dates never create false independence. Bank-identity tests: two textual variants of the same bank ("SBI" vs "State Bank of India  ") submitted for intake resolve to ONE `banks` directory row (free-text bank entry is forbidden for key purposes), so the same cheque number against both variants collides; genuinely different directory banks stay independent. Alias/directory enforcement: registering one alias for TWO different banks is rejected (global alias uniqueness); changing a `banks.code` once referenced is rejected (code immutability); intake with unresolved bank text cannot form a key (must register the alias first via approved configure flow); alias registration and intake resolution both exercise the single `fn_normalize_bank_text` (normalization edges: "SBI", "sbi ", "S.B.I", "S  B   I" all resolve identically; empty/punctuation-only rejected at both layers). Bank-creation concurrency: two concurrent `fn_register_bank` calls for the same institution yield exactly ONE `banks` row (+ alias), the loser returns the existing row (advisory-lock serialization asserted; no duplicate canonical rows under ≥10-thread contention); pre-existing near-duplicates are handled only via the approved merge path with history preserved, never by silent insert. Exception lifecycle paths (each PLANNED): (a) initial unknown-account event with NO approved exception → posting aborted; with dual-approved exception → single-claim posting succeeds; (b) potential duplicate blocked → candidate row durable with full identity fields, and NO second voucher exists while unresolved (asserted by voucher-count diff); (c) confirmed-same → enrichment updates the ORIGINAL event row with re-validation, zero new postings; (d) confirmed-distinct → dual-approved audited resolution authorizes exactly ONE claim consuming exactly one candidate; a second claim against the same resolution is rejected. Dual-approval structure: one approver record alone (or the same actor twice) can never move an exception to `approved` (counted in-transaction; self-approval structurally impossible); any single rejection moves it to `rejected`. Duplicate VALID identities â†’ rejected sequentially and concurrently (â‰¥10 threads, exactly one winner per key); legitimate identities in different required scopes â†’ accepted; UTR matching verified bank/date-agnostic; equal amounts with different keys â†’ both post. Rejections surface as 409 on the unique-constraint violation asserted in-ledger; the same key submitted concurrently on two paths â†’ exactly one wins. Amount-independence: two events of EQUAL amount with DIFFERENT source keys both post normally (amounts alone never dedupe â€” legitimate independent transactions preserved). Cross-path insertion orders (both PLANNED): unknown-account row first then the same instrument WITH account → second submission blocked, routed to enrichment review, resolved by supplying the account (original row updated in-transaction with re-validation) with full history; known-account first then unknown-account submission → likewise blocked and routed (symmetric search-then-block — the partial indexes alone are never relied on); concurrent unknown+known submissions for one instrument → advisory-lock serialization yields exactly one posted event plus one blocked review, never two postings. Normalization edges: "SBI", "sbi ", "S.B.I.", "S  B   I" all resolve to one directory row; empty/punctuation-only input rejected; unresolvable bank text rejected to the register-alias task (never guessed). Alias enforcement: same alias registered for a second bank → rejected; bank code change after first reference → rejected; intake with free-text bank bypassing aliases → rejected. Exception lifecycle: request → confirm (self-confirmation denied) → resolve, each audited; posting an account-unknown cheque/DD with NO approved exception → aborted; open-exception queue and approved-exceptions register both report correctly; enrichment appends history without rewriting prior rows.
3. **Allocation concurrency (Phases 4/6 gate):** two parallel allocations whose sum exceeds the remaining due/invoice balance â†’ exactly one wins (or partial split only if policy allows), loser gets 409 with no rows; final `paid â‰¤ due âˆ’ concession` and `Î£ allocations = paid`; test uses `SELECT FOR UPDATE` paths with â‰¥20 workers and asserts no over-allocation across 50 seeds.
4. **Authorization (Phase 2 gate, re-run every phase):** matrix of roleÃ—endpoint (allowed 200 vs denied 403) via direct API calls; deactivated/revoked session rejected within one request; self-approval (same user as maker+checker/approver) rejected; last-active-Super-Admin delete/deactivate rejected; Super Admin PATCH/DELETE of posted voucher or audit row rejected; permission grant without `roles.administer` rejected; limit-exceeding approval rejected.
5. **Reconciliation (Phases 4/6/7/10 gates):** student subledger Î£ (fee dues, PLUS hostel dues if and only if the unified `AR-STUDENT` mapping is approved â€” separate mapping excludes them) vs `AR-STUDENT` GL = 0; hostel dues Î£ vs the mapped receivables control (`AR-HOSTEL` or `AR-STUDENT` per the approved B15 mapping â€” tests run under the approved mapping) = 0 with a no-double-count cross-check (hostel-tagged postings under exactly one control; the two reconciliations cross-check with zero overlap and zero omission); held deposits Î£ vs deposit-liability GL = 0; supplier open Î£ vs `AP-SUPPLIER` = 0; per-account cash/bank GL vs book = 0 and consolidated cash/bank vs Î£ accounts = 0; department slices + Unassigned sum exactly to consolidated GL; cash/bank GL vs bank-book with unmatched ageing; fee-structure edit creates new version, historic dues unchanged; concession/refund require approval and appear in restricted register; all six documents generate with frozen template version + reprint/cancel history; unauthorized issuance blocked.
6. **Backup/restoration (Phase 9 gate):** full backup (DB + attachments) â†’ wipe host â†’ clean restore â†’ hash verification + TB/subledger equality vs pre-backup snapshot; Pre-restore-backup + dual-approval + audit verified; drill log attached.
7. **Migrations and privilege boundaries (every phase):** `upgrade head` + `downgrade -1` + `upgrade head` on a copy succeeds with row-count parity for posted/audit tables; ad-hoc DDL outside Alembic fails review; `CREATE TABLE` as `scnc_app_test` â†’ denied (no DDL); substituted role names (`TEST_DB_OWNER`/`TEST_DB_APP` set to anything but the fixed roles) â†’ abort before any database command; `scnc_app` is not a member of `scnc_reversal_invoker`; env.py with `ALEMBIC_DATABASE_URL` unset in test mode â†’ aborts (no fallback to `DATABASE_URL`/`alembic.ini`/defaults); env.py pointed at a non-`scnc_test*` database, wrong role, or non-allowlisted host â†’ aborts before any DDL; drop step against a target owned by another role â†’ aborts without dropping; absent target follows the creation path (no false verification claim); each fixture asserts live `current_user`/`current_database()` before running.
8. **Hostel / bank-cash / department acceptance (Phases 3/4/7 gates; ALL PLANNED â€” none implemented or executed):** (1) create 2+ bank accounts and 2+ cash accounts (incl. fee-counter cash) with no count limit enforced or assumable; (2) deactivate an account with posted history â†’ history intact and queryable, new postings to it rejected, deletion blocked; (3) account-master create/modify/deactivate/opening-change by an unauthorized actor â†’ denied + audited with old/new values; (4) contra transfer posts balanced Dr/Cr across the two masters, and an unbalanced transfer is rejected with rollback (money neither created nor destroyed â€” asserted by GL-sum invariance); (5) per-account opening `opening_batch_lines(bank_cash)` reconcile line-by-line to GL cash/bank before sign-off (any mismatch blocks), sign-off with a descriptive `opening_balance` differing from the posted line amount is rejected (the check runs at sign-off, never at master creation â€” creation precedes the batch by design), duplicate lines for one master are rejected, and report totals are invariant to the descriptive field alone; line-uniqueness matrix (all PLANNED): multiple `other_gl` lines for DIFFERENT GL accounts in one batch â†’ accepted; duplicate `other_gl` lines for the SAME account + batch â†’ rejected; duplicate `student_due` / `supplier_balance` / `bank_cash` logical targets per batch â†’ each rejected; valid balances for different masters/accounts in one batch â†’ accepted; lines with missing keys for their type (e.g. `bank_cash` without `master_id`, `other_gl` without `gl_account_id`) â†’ rejected by CHECK; concurrent duplicate line creation â†’ exactly one wins per partial unique index; (6) bank reconciliation matches statement lines with unmatched ageing, and cash-book/cash-count reconciliation tracks differences open until resolved (never silent adjustments); (7) hostel demand â†’ collection, deposit receipt (liability, not income), approved refund, and hostel supplier expense each post correct entries with hostel-wise reports tying out under the approved receivables mapping (no double-count across controls); (8) the same scoped source event submitted across fee/hostel/supplier paths posts exactly once (scoped `source_events` registry + per-record voucher uniqueness, DATABASE.md Â§6) while same-number-different-scope events and equal-amount events with different source keys both post; (9) department/cost-centre income/expense slices + Unassigned reconcile exactly to consolidated GL totals; (10) deactivating a department leaves all historical reports byte-identical on rerun; (11) unassigned-NULL lines are accepted by default, reported under Unassigned, and remain valid if a later rule makes assignment mandatory (no retroactive invalidation).

## 4. Status discipline: planned vs executed

- `Planned` = specified above, not run. `Implemented` = code exists, not yet tested. `Tested successfully` = log + commit + DB + counts cited below. `Blocked/Unverified` = cannot run or evidence missing. No phase is marked complete without the cited evidence.

## 5. Executed results

- 2026-10-16, commit `b2439b0`, Python 3.11.8 / psql 16.15 / node v24.15.0,
  `DATABASE_URL` host `127.0.0.1:5434/scnc_test` as `scnc_app_test`:
  `pytest backend/tests -q` → **16 passed**.
- 2026-10-16, same environment + roles: security-hardening + periods/accounts
  suites added; results recorded per run below. Fabrication is forbidden.
- 2026-10-17, Python 3.11.8 / PostgreSQL 16.15 (psql) / node v24.15.0 / npm 11.12.1,
  `DATABASE_URL` host `127.0.0.1:5434/scnc_test` as `scnc_app_test` (live-verified:
  `current_database()`=`scnc_test`, `current_user`=`scnc_app_test`):
  `pytest backend/tests -q` -> **57 passed** (includes the 0001/0002 downgrade/upgrade
  roundtrip on scratch `scnc_test_migcheck` as `scnc_test_owner`).
- 2026-10-17, same environment: the two concurrency suites now force a deterministic
  rendezvous through a test-only hook (`accounting_service._create_barrier`: `None` and
  inert in production) and a duplicate-insert race maps the unique-index `IntegrityError`
  to the SAME clean 400 a sequential duplicate returns (no 500). Real-commit tests delete
  ONLY the rows they create (no blanket table wipes); the session cleanup is prefix-scoped
  and ABORTS on unexpected committed users rather than deleting them.
- 2026-10-17, same environment: frontend `npm run build` (`tsc -b` + vite v8.3.4) -> success;
  `npm run lint` (oxlint) -> 0 errors, 1 pre-existing fast-refresh warning.
- 2026-10-17, same environment: test-safety corrections. Cleanup now deletes audit rows by
  `actor_id` scope only (the blanket `action LIKE 'stress.%'` delete in `scrub_test_users`
  and `test_audit` is removed; a regression test asserts the emitted SQL never uses an action
  pattern). `create_period`/`create_account` translate ONLY the expected duplicate-code unique
  violation (server SQLSTATE `23505` on `uq_financial_periods_code`/`uq_accounts_code`) into the
  clean 400; any other `IntegrityError` is rolled back and propagated (new tests cover both the
  expected duplicate and a foreign-key failure that must not be masked). The migration roundtrip
  asserts the scratch database name is disposable before any DROP/CREATE. `pytest backend/tests -q`
  -> **57 passed**; the deterministic concurrency suites passed 5/5 consecutive runs.
- 2026-10-17, same environment: draft voucher/journal-line save foundation added
  (`alembic 0003`: `number_sequences`/`vouchers`/`voucher_lines`; `voucher_service.create_draft_voucher`
  with period/account/amount/line validation, one-positive-side rule, per-`(voucher_type, fy_id)`
  advisory-lock numbering, atomic insert, and audit; `GET`/`POST` `/vouchers` gated on
  `vouchers.view`/`vouchers.create`). New focused suite `backend/tests/test_vouchers.py` -> **19 passed**
  (auth 401/403, invalid type/period/date/closed-period/inactive+unknown account, negative/>2dp,
  one-sided line, no-partial-rows on failure, audit-failure rollback, scoped sequential numbering,
  draft-stays-draft with no mutating/posting route, list pagination). Full `pytest backend/tests -q`
  -> **76 passed**; `0001/0002/0003` downgrade/upgrade roundtrip green; the deterministic concurrency
  suites passed 5/5 consecutive runs. No posting, approval, or reversal path exists yet and none is claimed.

## 6. Coverage limitations (acknowledged)

Concurrency suites prove behavior under test-level parallelism, not all production races; hash chain is tamper-evident, not tamper-proof; backup drills prove restorability of the drilled snapshot only; statutory suites do not substitute CA sign-off (plan.md Â§10B).

## 7. Audit checkpoint design (future mechanism - NOT implemented)

Limitation: a hash chain alone cannot detect deletion of its own tail, nor rewrite by a database owner/superuser. No external checkpoint exists today, and none is pretended. The designed future mechanism (Phase 9 scope): a scheduled job records max_id, tip_hash and timestamp after each successful backup into the backup manifest stored OFF the database server; restore and periodic verification pass these values as expected_tip_hash/expected_max_id to verify_chain, which reports tip_ok. A mismatch means the live chain no longer descends from the checkpointed tip - investigate before proceeding. Until implemented, tail-truncation and superuser rewrite are accepted residual risks covered only by access control, not by cryptography.