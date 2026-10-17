# PERMISSIONS.md â€” SCN College Accounting Application (Canonical, Rev 5)

**Status:** Phase 1+2+3 partial (2026-10-17): RBAC roles/permissions, sessions, and the last-active-Super-Admin guard are implemented and enforced server-side with passing pytest; voucher approval workflows are not yet built.
**Version:** Phase 0 Rev 5 â€” **Date:** 2026-10-15 (UTC)
**Governs with:** `README.md`, `plan.md`, `ARCHITECTURE.md`, `DATABASE.md`, `TESTING.md`

## 1. Principles (non-negotiable)

1. Backend authorizes every protected operation; frontend hiding is cosmetic.
2. Least privilege + dual control (Maker â‰  Checker â‰  Approver); no self-approval at any stage.
3. Posted vouchers and audit rows are immutable through the API for **all** roles including Super Admin; corrections only via reversal/adjustment workflows.
4. Last active Super Admin cannot be removed or deactivated (service guard + test; DB partial-index backstop).
5. Permission/role/session/period/template/backup actions are audited with actor, old/new values, and hash chain.
6. Sessions are server-side and revalidated per request; deactivation/revocation takes effect immediately.

## 2. Permission model

Code shape `{module}.{action}`. Modules (canonical, matches plan.md Â§4): `users, roles, students, enrollment, fees, hostel, receipts, documents, suppliers, invoices, payments, accounts, banking, departments, exceptions, vouchers, periods, assets, tax, reports, backup, settings`. Actions: `view, create, edit, submit, check, approve, post, reverse, cancel, print, export, configure, administer`.

Examples: `enrollment.create`, `fees.structure.approve`, `hostel.charge.approve`, `hostel.deposit.refund`, `receipts.create`, `receipts.post`, `banking.account.configure`, `banking.reconcile`, `departments.configure`, `documents.bonafide.approve`, `invoices.approve`, `payments.post`, `vouchers.reverse`, `periods.configure`, `backup.administer`, `roles.administer`.

Sensitive-field scope: `supplier.bank.view`, `concession.amount.view`, `reports.concession.view` denied by default; granted only by explicit permission and enforced in serializers (masked otherwise). Cash/bank master changes, opening-balance changes, and hostel deposit handling additionally require `configure`-level grants with re-authentication where configured, and are always audited with old/new values.

## 3. Starting roles (configurable; not hard limits)

| Role | Intended grants |
|---|---|
| Super Admin | Full administration (users/roles/settings/backup/audit/periods/templates) **except** silent financial/audit rewrite (technically blocked, Â§6). Financial post/approve only if separately granted under dual-control policy and never self-approved |
| System Administrator | users/roles/settings/backup ops; no financial post/approve/reverse |
| Accountant | accounts/vouchers post/reverse within open periods, reconciliation, reports |
| Maker | create/submit drafts (enrollment, fee structures, invoices, documents, refunds) |
| Checker | check/return drafts; cannot final-approve own or others' checked items for posting |
| Approver | approve/post within `approval_limits`; cannot approve items they made or checked |
| Fee Counter Staff | `receipts.create` + `receipts.print` + dues `view` under the approved counter policy (plan.md Â§10B decides full vs streamlined); no approve/reverse |
| Admission Staff | `students`/`enrollment` create/edit/submit; admission-letter submit only |
| Auditor / Viewer | read-only `view`/`export` on permitted reports; concession register only if explicitly granted |

Custom roles permitted from Phase 2 (e.g. a hostel-handling custom role may be created through this mechanism â€” no hostel roles are hard-coded). `approval_limits(role, module, max_amount NUMERIC, effective_from/to)` versioned; above-limit items escalate automatically. The standard voucher lifecycle (Â§2C functions, no self-approval, bound approvals) applies identically to hostel vouchers, contra transfers, and department-tagged lines; a department/cost-centre tag never substitutes for an approval.

## 4. Approval workflows

Default sensitive flows Maker â†’ Checker â†’ Approver â†’ Posted: fee-structure publish, concession/scholarship, refund, supplier invoice, supplier payment, admission/seat letter, bonafide, asset disposal, period close/reopen, opening batch posting. Fee-counter collection follows the college's chosen policy (`approval_policies` row: either full Mâ†’Câ†’A or counter-post + same-day checker review); system supports both, default assumes nothing â€” decision in plan.md Â§10B. Voucher state machine is the canonical lifecycle in DATABASE.md Â§2 (`draftâ†’pending_approvalâ†’edit_requestedâ†’pending_approvalâ†’approved_for_postingâ†’posted`, with `rejected`/`cancelled`/`reversed` branches; checker/approver sign-offs are `posting_approvals` rows, not statuses); illegal transitions rejected with 409 + audit. Edit authorization never authorizes posting; posting requires its own bound approval. Exception distinctness decisions (DATABASE.md §6D) require TWO distinct approvers holding `exceptions.approve`, both different from the requester — counted structurally, so one actor can never satisfy both steps; bank-alias registration/retirement and bank creation require `banking.configure` with approval + audit (alias retirement additionally dual-approved). Self-approval is denied by default (creator â‰  checker/approver/poster) unless a documented, explicitly approved policy permits a named exception.

## 5. First-Super-Admin bootstrap and recovery (no hard-coded credentials)

**Bootstrap (fresh install, Phase 2):**
1. Installer generates a cryptographically random setup token (â‰¥256-bit), stores only its Argon2id hash + expiry (e.g. 2h, single-use) in `system_settings`, and prints the plaintext **once** to the server console / restricted setup file (never committed, never logged).
2. Operator opens local `/setup` with the token and creates the first Super Admin (username + strong password â‰¥12 chars, breached-password screen, optional TOTP enrollment).
3. Token burned on success or expiry; event audited (actor `system`, outcome). Further admins are created only by an existing Super Admin. Setup endpoint disabled once an active Super Admin exists (returns 403).

**Recovery (all admins lost or locked):**
1. Requires physical/OS-level access to the LAN server by the designated custodian(s) (plan.md Â§10B, backup/server item).
2. Custodian runs the Phase 9-documented CLI (`create-setup-token --reason â€¦`) which requires OS authentication, enforces dual-person approval where configured, issues a new single-use token with short expiry, and writes an audit row on next successful use.
3. There is **no API** to self-issue a setup token; the recovery path never bypasses audit once the system is reachable. If the database itself is lost, recovery is via Phase 9 backup-restore, not via bootstrap.

## 6. Change semantics: permissions, sessions, escalation, limits, immutability

- **Permission/role changes:** require `roles.administer` + fresh re-authentication; service records old/new grants in `audit_log`; changes apply to **subsequent authorization checks immediately** (permissions resolved per request from DB, never cached beyond the request); operator cannot grant themselves a permission they lack (escalation attempt rejected + audited); granting `super-admin`, `backup.administer`, or raising `approval_limits` additionally requires a second active Super Admin/Approver confirmation + reason.
- **Session revocation:** `sessions(id, token_hash, user_id, expires_at, revoked_at, ip, user_agent)`; every request validates `revoked_at IS NULL AND expires_at > now() AND user.is_active`; user deactivation, password reset, or explicit revoke sets `revoked_at` on all live sessions in the same txn as the change; frontend `/me/permissions` is advisory only.
- **Self-approval:** the service AND the transition functions compare `created_by / checked_by / approved_by / posted_by` ids across the workflow; any overlap in Maker/Checker/Approver for the same entity â†’ 403/abort + audit, unless a documented explicitly approved policy exception applies. Tests prove this (TESTING.md Â§3 suites 4, 1C, 1D).
- **Approval-limit changes:** versioned rows (old rows end-dated, never overwritten); change requires `roles.administer` (or `periods.configure` for period-linked limits) + re-auth + second approver + audit; postings above the requester's current limit are rejected even if the UI was bypassed.
- **Posted/audit protection (normative DB spec in DATABASE.md Â§Â§2Aâ€“2C/Â§3):** the normal application role has no `UPDATE`/`DELETE` grant on `vouchers`/`voucher_lines`/`audit_log`, and migration-owned triggers reject any residual path: `trg_voucher_line_locked` blocks ALL of INSERT/UPDATE/DELETE on lines of a posted/reversed/void voucher (while permitting line writes during the initial posting sequence when the parent is still editable); `trg_voucher_immutable` permits only the posting flip and the single `posted â†’ reversed` flip with all other columns unchanged plus a linked posted reversing voucher in the same transaction. Stated without over-claim: triggers enforce transition SHAPE and cannot identify their caller â€” the caller restriction comes from the grants (neither app nor invoker role can issue the UPDATE at all), and direct owner/superuser bypass remains possible but is CONTROLLED + DETECTED per DATABASE.md Â§2A.5 (sealed credentials, logged owner access, hash-chain + reconciliation detection). Draft edits are possible ONLY through the `fn_draft_*` functions, which bind the actor server-side from the live session token (`p_actor` never trusted alone â€” mismatch aborts) and re-check permission/state/period in-transaction; direct DML stays denied. Reversal privilege separation is by CREDENTIAL, not membership: `scnc_app` is never a member of `scnc_reversal_invoker` (`SET ROLE` forbidden); the service opens the approved reversal transaction on a dedicated connection as the invoker (credential held only in the reversal module's connection factory, narrow grants: no UPDATE/DELETE/DDL), re-validates the token-bound actor, the bound approval (exact voucher pair + amount, completed, unconsumed, no self-approval), state, balance, and period in-txn, and the hardened function (fixed `search_path`, flips only the flag, consumes the approval, writes audit) completes it. Direct app-role calls are denied. This applies equally to Super Admin API calls. Posting/draft/edit-approval/reversal tests (TESTING.md Â§3 suites 1Aâ€“1D, incl. no-membership, impersonation-tripwire, stale-version, and grant/trigger/attribute proxies) run as the normal app role. All voucher state changes execute inside the Â§2C transition functions (token-bound actor, in-function permission/state/period/balance checks, audit); there is no direct-update path for any application credential.

## 7. Backup/restore authorization and audit

Backup requires `backup.administer`; scheduled backups record `backup_history(location, sha256, outcome)` + audit. Restore is a privileged dual-control action: `backup.administer` + re-auth + second-approver reason + mandatory pre-restore backup; restore drills on a clean host are required before go-live (Phase 9) and each drill is audited with its verification result. Attachment restores are included and hash-verified.

## 8. Enforcement points (implemented and tested in Phase 2; none exist yet)

FastAPI dependencies `require(permission)`, `deny_self_approval`, `check_period_open`, `check_entity_state`, field-masking serializers. Required negative tests listed in TESTING.md Â§3 (direct-API 403s, revoked-session rejection, last-admin guard, limit enforcement, posting/draft/edit-approval/reversal suites 1Aâ€“1D, posted-immutability).

## 9. Open decisions (plan.md Â§10A/10B)

Named Super Admins, staffâ†’role mapping, counter policy, concession/refund/document authorities + limits, MFA mandate, backup custodian. All UNCONFIRMED until written college/CA approval; nothing here is policy.
