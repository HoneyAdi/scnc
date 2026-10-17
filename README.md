# README.md â€” SCN College Accounting Application (Canonical)

**Institution:** Shri Chamatkari Sant Ji College of Nursing, VPO Girawar, Tehsil Meham, Rohtak, Haryana
**Status:** Phase 1+2+3 partial (2026-10-17): 76 pytest pass on an isolated PG16 test DB; auth/RBAC/audit, periods/accounts, and a draft voucher/journal-line save foundation are implemented; posting/approval/reversal are not. Phase 0 remains UNAPPROVED; no production-readiness claim.
**Version:** Phase 0 Rev 5 â€” **Date:** 2026-10-15 (UTC)

> This is the canonical project entry point. It supersedes execution guidance in earlier drafts where they conflict. No statement here certifies implementation.

## 1. Canonical document set (conflict resolved)

The repository previously contained `SCN_README.md` / `SCN_plan.md` while the Master Instruction referenced `README.md` / `plan.md`.

**Resolution (Phase 0 Rev 5; Revs 2-4 established the set and scope, Rev 5 carries targeted consistency corrections on â€” history in `plan.md` Â§11 is preserved as written):**

| File | Role |
|---|---|
| `README.md` (this file) | Canonical overview, features, setup pointers, acceptance summary |
| `plan.md` | Canonical phased delivery plan and acceptance gates |
| `ARCHITECTURE.md` | Canonical architecture, components, boundaries, flows |
| `DATABASE.md` | Canonical entities, constraints, entries, reconciliation, migrations |
| `PERMISSIONS.md` | Canonical roles, permissions, approvals, bootstrap, session rules |
| `TESTING.md` | Canonical test strategy, Windows reproducibility, acceptance suites |
| `SCN_README.md` | **Frozen source input** â€” retained for traceability, do not edit further |
| `SCN_plan.md` | **Frozen source input** â€” retained for traceability, do not edit further |

If any frozen source conflicts with a canonical doc, the canonical doc governs and the conflict is noted in `plan.md` Â§Change-log.

## 2. Purpose and scope

One reliable ledger for college finance and student administration: double-entry GL, student receivables with enrollment history, reusable fee structures, dues/notices/receipts/concessions/refunds, hostel fee demands/collections/deposits/refunds with hostel-wise reporting (accounting-level only), configurable departments/cost centres with consolidated + unit-wise reporting from the single ledger, unlimited configurable bank/cash accounts with contra transfers and bank/cash reconciliation, 6 controlled student documents, supplier payables, fixed assets + depreciation, configurable GST/TDS registers, Super Admin + granular RBAC + audit, PDF/Excel reports, LAN deployment, backup/restore.

Initial courses: B.Sc. Nursing, Post Basic B.Sc. Nursing, GNM, ANM. Student population: PENDING COLLEGE CONFIRMATION â€” recorded estimates conflict (frozen `SCN_README.md` states approximately 250â€“300; a separate project requirement indicated 500â€“1,000), so no figure is adopted here. No student-count limit is hard-coded anywhere: the system must remain configurable for any enrollment size. See `plan.md` Â§10B (capacity confirmation). Likewise no bank/cash account count is required at planning stage â€” account masters are unlimited configurable rows, not fixed settings.

**Deferred unless separately approved:** inventory, payroll, payment gateways, third-party integrations, and operational hostel management (room allocation, bed availability, hostel attendance, mess management).

## 3. Canonical phase order (consistent everywhere)

Execution order is now identical in `README.md`, `plan.md`, `ARCHITECTURE.md`, `DATABASE.md`, `PERMISSIONS.md`, `TESTING.md`:

- **Phase 0** â€” Requirements & architecture (this revision; approval gate)
- **Phase 1** â€” Secure project foundation (skeletons, env, logging, migration/test infra, docs; no financial logic)
- **Phase 2** â€” Authentication & authorization (first-Super-Admin bootstrap, RBAC, sessions, audit) â€” **must complete before any financial operation is accessible**
- **Phase 3** â€” Accounting foundation (COA, journal engine, periods, posting/reversal, trial balance, department/cost-centre dimension, cash/bank masters)
- **Phase 4** â€” Students, enrollment history, fees, hostel accounting, opening receivables
- **Phase 5** â€” Student documents (all six)
- **Phase 6** â€” Suppliers and payables
- **Phase 7** â€” Assets, banking (incl. unlimited bank/cash masters, contra, bank/cash reconciliation), department/hostel reporting, report validation
- **Phase 8** â€” Statutory registers and period/export controls
- **Phase 9** â€” LAN deployment, backup, restoration, operations
- **Phase 10** â€” Data migration, pilot, go-live gate

This adopts the Master Instruction order (auth before accounting) and corrects the earlier README/plan drafts that placed accounting before RBAC. Rationale: no voucher, receipt, or report endpoint may exist without server-side authN/authZ, session revocation, and audit already enforced and tested.

## 4. Critical business rules (summary; normative detail in DATABASE.md / PERMISSIONS.md)

1. Every posted journal balances (Î£Dr = Î£Cr > 0); `NUMERIC(14,2)` / `Decimal` only.
2. Saved â‰  posted: vouchers move `draft â†’ pending_approval â†’ approved_for_posting â†’ posted` (with edit-request, rejected, cancelled, reversed branches; DATABASE.md Â§2). Only `posted` rows feed ledgers and reports. Saved vouchers change only through authorized edit-request/approval flows; posting needs its own bound approval; no direct writes exist for any application credential (narrow `SECURITY DEFINER` functions + revoked grants + shape-checking triggers, DATABASE.md Â§Â§2Aâ€“2C/Â§3). Posted corrections only via linked reversal/adjustment; even Super Admin cannot silently edit.
3. Closed financial periods reject ordinary postings; reopen is restricted, justified, audited.
4. No manual `students.opening_balance` column as a source of truth; opening receivables enter only via a controlled opening batch that posts to the GL and reconciles (see DATABASE.md Â§5).
5. Student progression recorded in `student_enrollments` history (admission â†’ enrollment â†’ promotion â†’ graduation/transfer/leaving); fee assessments link to an enrollment row.
6. Receipt/payment numbers are unique **within** `(type, financial-year)` scope; global surrogate `id` is internal only (see DATABASE.md Â§6). A numbered fee receipt is issued ONLY after its posting transaction commits â€” unposted slips are never final receipts.
7. Allocation over-subscription is prevented by transactional service checks + row locking, not by cross-row CHECK constraints.
8. Backend authorization on every protected operation; no self-approval; last active Super Admin protected.
9. Audit log append-only with tamper-evident hash chain (not "tamper-proof").
10. Test DB isolated; DEMO seed clearly labelled; never mixed with real data.
11. One central ledger only: department/cost-centre and hostel slices MUST reconcile to consolidated GL totals; no disconnected ledgers, no duplicate entries for one economic event.
12. Security deposits are liabilities, never income, until a CA-approved mapping says otherwise; contra transfers are balanced and cannot create or destroy money; account/department deactivation preserves history (never delete-then-lose).

## 5. Setup pointer (reproducible detail in TESTING.md Â§2)

Windows + Python 3.12 + PostgreSQL 16 + Node 20 LTS; venv; `pip install`; fail-safe disposable test-DB procedure + owner migration + app-role `alembic upgrade head` + `pytest` (normative commands in TESTING.md Â§2: the caller pre-sets `ENV=test` with exact fixed role names; a single guarded helper owns `PGPASSWORD` within per-call `try/finally`; URL-encoded connection strings; the script verifies the allowlisted host with loopback-aware matching and the LIVE `current_database()`/`current_user` on the target itself before every destructive, migration, and test step, with pre-drop ownership checks and no-fallback `ALEMBIC_DATABASE_URL`). Production LAN install, backup, and restore procedures are defined in Phase 9 and must pass a clean-restore drill before go-live. `.env.example` will contain placeholders only (Phase 1).

## 6. Acceptance summary (normative checklists in plan.md / TESTING.md)

No production release until: authZ proven at API level; journals balance; duplicates rejected; allocations concurrency-safe; subledgers reconcile to GL; all six documents issuable with history; supplier checks pass; reports reconcile; backup restores including attachments; college management + accountant sign off policies and opening balances.

## 7. Unresolved decisions (require college / CA input â€” not invented)

Legal entity + accounting basis; academic calendar; fee heads/amounts/instalments; hostel categories + hostel GL mappings (incl. deposit-liability handling); department/cost-centre structure + mandatory-assignment policy; opening dues/balances; GST/TDS applicability; named Super Admins + role mapping; counter workflow choice; concession/refund/document authorities; templates/signatories; server/LAN/backup ownership; depreciation policy; refund/concession GL treatment sign-off. Bank/cash account counts are NOT required â€” unlimited configurable masters. Full list split by gate in `plan.md` Â§10A (Phase 1) / Â§10B (financial workflows + go-live). All treatments UNCONFIRMED until written approval â€” nothing here invents policy, amounts, or rates.

## 8. Implementation status

**Phase 1+2+3 partial (2026-10-17):** auth/RBAC/sessions/audit and financial periods/chart-of-accounts are implemented with 76 passing pytest cases on an isolated PG16 test DB; migrations 0001/0002/0003 exist. A draft voucher/journal-line **save** foundation (create/list/get drafts, atomic, permission-checked, audited, controlled per-period numbering) is implemented; the posting/approval/reversal engine and all ledger effects are NOT built, and the draft slice uses the normal application-role path (the DATABASE.md 2A-2C privilege-confinement target remains unimplemented - see that file). Phase 0 remains UNAPPROVED. See `plan.md` progress table and `TESTING.md` 5 Executed-results (latest run recorded there).
