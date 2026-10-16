# ARCHITECTURE.md â€” SCN College Accounting Application (Canonical, Rev 5)

**Status:** CANONICAL PROPOSAL â€” Phase 0 Rev 5. No code implemented. No tests run.
**Version:** Phase 0 Rev 5 â€” **Date:** 2026-10-15 (UTC)
**Governs with:** `README.md`, `plan.md`, `DATABASE.md`, `PERMISSIONS.md`, `TESTING.md`
**Frozen inputs:** `SCN_README.md`, `SCN_plan.md` (do not edit)

## 1. Stack (unchanged, pinned in Phase 1)

React + TypeScript frontend; Python + FastAPI + Pydantic v2 backend; SQLAlchemy 2.x + Alembic; PostgreSQL 16+; Argon2id (`argon2-cffi`); opaque server-side sessions (JWT deferred); ReportLab; openpyxl; pytest + HTTPX (+ frontend/browser tests from Phase 1 per plan.md and TESTING.md Â§2). No gateway/inventory/payroll. Exact pinned versions recorded in Phase 1 (`requirements.txt` / `package.json`); no unapproved dependencies.

## 2. Canonical phases (consistent with plan.md)

Phase 0 requirements â†’ Phase 1 secure foundation â†’ **Phase 2 authN/authZ (before any money)** â†’ Phase 3 accounting engine (incl. department/cost-centre dimension + cash/bank masters) â†’ Phase 4 enrollment/fees/hostel â†’ Phase 5 documents â†’ Phase 6 suppliers â†’ Phase 7 assets/banking/reports (account-wise books, bank/cash reconciliation, department/hostel reporting) â†’ Phase 8 statutory â†’ Phase 9 deploy/recovery â†’ Phase 10 pilot/go-live. Earlier drafts placing accounting before RBAC are superseded; rationale: financial endpoints must never exist without enforced sessions, RBAC, and audit.

## 3. Request flow and trust boundaries

```
Browser (LAN) â†’ TLS (preferred; HTTP only behind LAN firewall) â†’ FastAPI
  [validate â†’ authenticate (session) â†’ authorize (permission + state + period + ownership)
   â†’ service transaction (locks â†’ post â†’ subledger â†’ audit) â†’ commit]
  â†’ PostgreSQL + protected file storage
```

1. Browserâ†”API: backend authoritative; UI hiding is cosmetic.
2. APIâ†”DB: three separated least-privilege roles â€” `scnc_test_owner`/owner (DDL/migrations only), `scnc_app` (normal traffic: no DDL, no UPDATE/DELETE on posted/audit tables â€” Â§7), `scnc_reversal_invoker` (approved reversals only on a dedicated connection: no UPDATE/DELETE grants, no DDL, no app-role membership â€” DATABASE.md Â§3); migrations run as owner only.
3. APIâ†”storage: files outside web root, API-mediated audited downloads, SHA-256 in `attachments`, MIME/size validation at API + storage layers.
4. LANâ†”outside: PostgreSQL not exposed; firewall allow-list; secrets in env only.

## 4. Backend layout (proposal; created in Phase 1, no code yet)

```
backend/app/{main.py, core/{config,security,permissions,logging_config},
  db/{base,session}, models/{users_roles,audit,periods,accounts,students_enrollment,
  fees,hostel,departments,cashbank,documents,suppliers,assets_banking,sequences}, schemas/*,
  api/v1/{setup,admin_users,admin_roles,admin_audit,admin_backup,students,
  enrollment,fees,receipts,hostel,departments,banking,documents,suppliers,payables,accounting,reports},
  services/{posting,period,fee,receipt,hostel,department,cashbank,document,supplier,payment,allocation,
  depreciation,reconciliation,numbering,backup}, templates/*, storage/*}
backend/{alembic/, tests/, requirements.txt}
frontend/src/{pages,components,hooks,api,auth,reports,print}
scripts/{backup,restore,verify_hashchain}  # documented in Phase 9
```

Rules: accounting math only in `services/`; routers validate + call services; no business rules in frontend.

## 5. Core flows (normative summaries; detail in DATABASE.md / PERMISSIONS.md)

- **Bootstrap â†’ auth:** one-time setup token â†’ first Super Admin â†’ roles/permissions â†’ sessions; every later call checks session validity + permission + entity state.
- **Voucher lifecycle (canonical states in DATABASE.md Â§2):** `draft` (maker enters via `fn_create_draft_voucher`/`fn_draft_*`) â†’ `pending_approval` (`fn_submit_voucher`; saved but NOT in GL) â†’ optional `edit_requested` â†’ back to `pending_approval` (only via authorized + applied edit request) â†’ `approved_for_posting` (bound approval for the exact version+hash) â†’ `posted` (only via `fn_post_voucher`; the ONLY state feeding GL/reports), with `rejected`/`cancelled`/`reversed` terminal branches. Saved â‰  posted: nothing but `posted` rows feeds ledgers or statements. Edit authorization never authorizes posting; posting requires its own bound approval; self-approval denied by default.
- **Posting (all money, ONE `fn_post_voucher` transaction â€” DATABASE.md Â§3):** token-bound actor + permission â†’ lock voucher/lines/period/sequence/subledger rows â†’ assert `approved_for_posting` with bound unconsumed approval for the exact version+hash â†’ validate COMPLETE journal + all controls â†’ write subledger/allocation rows â†’ flip to `posted` (lines freeze) â†’ consume approval â†’ append `audit_log` â†’ commit; any failure rolls everything back. Idempotency key dedupes retries; the scoped shared `source_events` claim in the same transaction dedupes one real-world event submitted through several workflows (same slip number at different counters/FYs stays distinct; amounts alone never dedupe). The numbered fee receipt is issued ONLY after this transaction commits (DATABASE.md Â§4). No application credential holds direct write grants on financial tables â€” all mutations run inside the Â§2C transition functions.
- **Enrollment lifecycle:** `students` (identity, one row per person) + `student_enrollments` (one row per academic-year registration; admission/promotion/repeat/graduation/transfer/leaving as new/closing rows, never overwrite). Fee assessments FK to `enrollment_id`. See DATABASE.md Â§5.
- **Hostel accounting (accounting-level only):** hostel demands/collections/deposits/refunds/expenses post through the SAME voucher lifecycle and central ledger as college fees (one journal per economic event; shared idempotency + allocation guards prevent duplicates). Deposits are liabilities, never income, until a CA-approved mapping says otherwise. Operational hostel management (rooms, beds, attendance, mess) is OUT of scope. See DATABASE.md Â§Â§4/5B.
- **Departments / cost centres (reporting dimension, single ledger):** every voucher line MAY carry one `department_id`; multi-unit transactions use split balanced lines; NULL means Unassigned (allowed unless a configured rule requires otherwise). Dept breakdowns + Unassigned MUST sum to the consolidated GL total â€” the dimension can never fork the ledger. Deactivation never rewrites history. See DATABASE.md Â§5C.
- **Bank / cash accounts (unlimited masters):** each `cash_bank_accounts` row owns exactly one GL account; receipts/payments/contra post against the specific master's account; contra transfers are balanced (money is never created or destroyed); per-account books + bank/cash reconciliation derive from posted lines; deactivation preserves history. No account-count limit; counts are college data, not a decision. See DATABASE.md Â§5D.
- **Opening receivables:** no manual balance column. Controlled `opening_batches` import posts proposed opening journals (account mapping UNCONFIRMED until CA sign-off) and creates matching `fee_dues` rows in one transaction, then reconciliation report must tie to zero difference before sign-off. See DATABASE.md Â§5.
- **Numbering:** FY-scoped business numbers via locked `number_sequences` rows; `UNIQUE(type, fy_id, number)`; internal `id` is global PK. See DATABASE.md Â§6.
- **Allocations:** locked recomputation of remaining balance per transaction; never cross-row CHECK. See DATABASE.md Â§6.

## 6. Line constraints and statements (summary)

Each voucher: â‰¥2 lines; each line exactly one side > 0 (`CHECK (debit>=0 AND credit>=0 AND ((debit>0)::int+((credit>0)::int)=1))`); accounts active and posting-allowed; Î£Dr = Î£Cr > 0 verified in-service within the posting transaction and re-asserted by tests/reports. TB and statements are pure aggregations over posted `voucher_lines` (TB = Î£(Drâˆ’Cr) by account; P&L/BS by account-type mapping); department/hostel/account filters are reporting slices that MUST reconcile to the unfiltered totals; any reportâ†”ledger mismatch is a release blocker. Full entries + reconciliation queries in DATABASE.md Â§Â§4,7.

## 7. Immutability, drafts, reversals, and audit (summary; normative spec in DATABASE.md Â§Â§2Aâ€“2C/Â§3, behavior in PERMISSIONS.md Â§6)

Once a voucher leaves `draft`, its lines accept NO further direct writes â€” enforced by revoked write grants on financial tables for all application credentials plus `trg_voucher_line_locked` (parents outside `draft`/`edit_requested` reject all line writes, including writes issued inside definer functions). Saved vouchers change only through the Â§2C transition functions (submit / edit-request / authorize / apply / approve-for-posting / post / cancel / resubmit / reverse), each with token-bound actors, in-function permission/state/period/balance checks, version+hash staleness guards, and audit. Posted voucher rows accept no UPDATE/DELETE except the trigger-listed single-step transitions, reachable in practice only through those functions. The trigger cannot identify its caller and this spec does not claim otherwise; direct owner/superuser bypass is controlled + detected per DATABASE.md Â§2A.5. Corrections = new reversal/adjustment vouchers with links. Super Admin uses the same API and roles and is equally blocked from silent edits. Hash chain is tamper-evident only. Acceptance tests for lifecycle, posting, draft/edit confinement incl. impersonation tripwires and stale-version guards, and reversal authorization incl. no-membership (as the normal app role) are required in TESTING.md Â§3 suites 1Aâ€“1D.

## 8. Deployment (LAN-first, portable)

Dev on Windows (see TESTING.md Â§2); prod LAN hardened server; daily encrypted off-server backups; restore drill required. Portable via env config; `.env.example` placeholders only.

## 9. Decisions and blockers

Stack sessions-over-JWT and auth-before-accounting per Â§2 rationale. Open college/CA items listed in plan.md Â§10A/10B and not invented here â€” all accounting/statutory treatments stay UNCONFIRMED until written approval. Flet clause moot (no Flet code in repo).
