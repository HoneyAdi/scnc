# SCN College Accounting Application --- Development Plan

**Institution:** Shri Chamatkari Santji College of Nursing\
**Location:** VPO Girawar, Tehsil Meham, Rohtak, Haryana\
**Deployment target:** Browser-based application on the college LAN\
**Status:** Revised target plan; implementation status must be verified
against the actual repository.

## 1. Purpose and Scope

Deliver one centralised accounting application for college finance and
student administration. It must preserve a single accounting ledger and
support student receivables, reusable fee structures, due notices, fee
receipts, student documents, supplier payables, configurable permissions
and Super Admin control.

### Included in the initial scope

-   Double-entry accounting and financial reports.
-   Student master and student debtor ledgers.
-   Course-wise/academic-year-wise reusable fee structures.
-   Fee dues, notices, receipts, payment allocation and approved
    concessions/refunds.
-   Customisable PDF templates and six student document types.
-   Supplier master, invoice approvals, payments, allocations and
    ageing.
-   Super Admin, custom roles, granular permissions and audit logs.
-   Fixed assets, depreciation, bank reconciliation and applicable tax
    registers.
-   Browser frontend, LAN deployment, backups and recovery testing.

### Deferred unless separately approved

-   Inventory management.
-   Payroll.
-   External payment gateway integration.
-   Other third-party integrations not required for the first release.

## 2. Technical Direction

-   **Frontend:** React-based browser interface.
-   **Backend:** Python/FastAPI.
-   **Database:** PostgreSQL.
-   **ORM/migrations:** SQLAlchemy 2.x and Alembic.
-   **PDF/Excel:** ReportLab and openpyxl.
-   **Tests:** pytest, HTTPX, frontend/browser tests.
-   **Deployment:** Secured college LAN server.

The existing Flet client may remain during transition if it uses the
same backend and ledger. Do not create a second database or duplicate
accounting logic.

## 3. Phase 0 --- Repository Audit and Security Baseline

### Tasks

-   Inspect repository structure, current implementation, `README.md`,
    tests and configuration.
-   Verify which documented features are actually implemented.
-   Run tests against the current commit and a separate test database.
-   Review authentication, authorisation, voucher posting, audit logging
    and file access.
-   Rotate exposed/default credentials and secrets.
-   Review schema changes and replace ad hoc production schema upgrades
    with Alembic migrations.
-   Check upload limits and file validation consistently across
    frontend, API and storage.
-   Back up the database and attachments, then demonstrate restoration
    to a clean environment.
-   Record known defects and a baseline test report.

### Exit criteria

-   Current implementation status is documented.
-   Critical credentials/security defects are fixed.
-   A verified backup and successful restore are demonstrated.
-   No production schema changes occur without a tested migration and
    backup.

## 4. Phase 1 --- Accounting Foundation

### Tasks

-   Review chart of accounts, opening balances, vouchers and ledger
    posting.
-   Enforce balanced debit/credit totals and valid active accounts.
-   Implement atomic, idempotent posting and duplicate request
    protection.
-   Enforce immutable posted vouchers; correct them through approved
    reversal/adjustment workflows.
-   Implement financial-period open/closed controls.
-   Validate student-fee and supplier control-account reconciliation
    design.
-   Standardise monetary calculations using decimal types.
-   Add source links, approval state, unique numbering and audit events.

### Exit criteria

-   All posted vouchers balance.
-   Duplicate requests cannot post twice.
-   Posted entries cannot be silently modified or deleted.
-   Period locks and reversal controls pass tests.
-   Trial balance agrees with ledger totals.

## 5. Phase 2 --- Super Admin, User Management and RBAC

### Tasks

-   Create a secure first-Super-Admin setup flow.
-   Support user creation, update, activation/deactivation and session
    revocation.
-   Support system and custom roles.
-   Define permissions by module, action, record scope and sensitive
    fields.
-   Add permissions for
    view/create/edit/submit/check/approve/post/print/export/cancel/reverse/configure.
-   Add approval limits and module-specific access.
-   Prevent self-approval and protect the last active Super Admin.
-   Audit role/permission changes, account changes, privileged actions
    and security events.
-   Require re-authentication for sensitive administrative changes; add
    MFA for privileged users if feasible.

### Exit criteria

-   Backend tests prove that restricted users cannot access unauthorised
    endpoints.
-   The UI reflects permissions, but API enforcement remains
    authoritative.
-   Super Admin can administer roles without bypassing financial
    immutability.
-   Deactivated users cannot continue using valid sessions.

## 6. Phase 3 --- Browser-Based LAN Application

### Tasks

-   Build secure login/logout and session-expiry handling.
-   Create role-aware dashboard and navigation.
-   Implement reusable form, table, search, filter, validation and
    pagination patterns.
-   Create Maker, Checker and Approver work queues.
-   Display approval status, decline reason and audit history.
-   Add accessible printing and PDF/Excel download flows.
-   Configure LAN host, firewall and service startup.
-   Keep PostgreSQL inaccessible directly from client computers.

### Exit criteria

-   Authorised staff can complete assigned workflows in a browser.
-   Unauthorised controls and direct API requests are rejected.
-   Application is usable from intended LAN computers.
-   No secrets are embedded in frontend code.

## 7. Phase 4 --- Student Master and Fee Management

### Tasks

-   Implement student records for B.Sc. Nursing, Post Basic B.Sc.
    Nursing, GNM and ANM.
-   Maintain course, batch, academic year, student status and
    admission/registration numbers.
-   Implement student debtor ledger and opening balances.
-   Create reusable, versioned fee structures by course, academic year,
    year/semester, fee head and installment.
-   Apply fee structures to students and generate fee assessments.
-   Generate Fee Due Notices with charges, payments and balances.
-   Record payments, payment modes, references and allocations.
-   Generate final numbered receipts only when payment meets the
    configured posting conditions.
-   Implement approved concessions, scholarships, refunds and
    adjustments.
-   Reconcile student subledger balances with general-ledger
    receivables.

### Exit criteria

-   Fee structures can be reused without retyping all fee heads.
-   Changing a structure does not silently rewrite historic assessments.
-   Partial payments and multiple fee heads calculate correctly.
-   Fee dues, receipts and the GL reconcile.
-   Student history is retained when a student leaves or graduates.

## 8. Phase 5 --- Document Templates and Issuance

### Required documents

1.  Fee Receipt / Payment Acknowledgement.
2.  Admission / Seat Allotment Confirmation Letter.
3.  College Identity Card.
4.  Enrollment / Registration Number Slip.
5.  Fee Concession / Scholarship Order.
6.  Bonafide Certificate.

### Tasks

-   Create editable templates for logo, college details, fields, layout,
    signatures, footer and print settings.
-   Populate documents from saved student and fee records.
-   Add unique numbering, issue date, academic year and template
    version.
-   Add approval controls for admission letters, concessions and
    bonafide certificates.
-   Store issuance, cancellation, supersession and reprint history.
-   Restrict document generation and access by role.

### Exit criteria

-   All six document types can be generated as PDFs.
-   Template changes do not alter previously issued document records.
-   Unauthorised users cannot issue restricted documents.
-   Reprints and cancellations are traceable.

## 9. Phase 6 --- Supplier and Accounts Payable

### Tasks

-   Create supplier master with applicable tax details and restricted
    bank data.
-   Create supplier invoice draft with invoice number/date, line items,
    taxes, due date and attachments.
-   Add duplicate invoice checks and validation.
-   Implement Maker → Checker → Approver → Posting workflow.
-   Post approved invoices to the correct expense/asset and payable
    accounts.
-   Record payments and allocate them to invoices.
-   Prevent invalid over-allocation and duplicate payment posting.
-   Produce supplier ledger, open payables, ageing and reconciliation
    reports.

### Exit criteria

-   Invoice and payment workflows enforce permissions and approvals.
-   Supplier balances reconcile with the GL.
-   Duplicate invoice/payment checks work.
-   Attachments are access-controlled and included in recovery
    procedures.

## 10. Phase 7 --- Other Accounting Modules and Reporting Validation

### Tasks

-   Review and validate chart of accounts and opening balances.
-   Validate payment, receipt, journal and contra vouchers.
-   Validate fixed asset register and WDV/SLM depreciation calculations.
-   Validate bank statement matching and reconciliation.
-   Validate Trial Balance, Income and Expenditure, Balance Sheet,
    ledgers, cash/bank books and voucher registers.
-   Validate applicable GST/TDS registers with the college's CA or tax
    adviser.
-   Add academic-year and financial-year report filters.
-   Validate PDF and Excel exports against on-screen reports.

### Exit criteria

-   Reports reconcile to the underlying ledgers.
-   Depreciation and tax treatment are reviewed and approved.
-   Financial statement outputs are signed off by the responsible
    accountant/management.

## 11. Phase 8 --- Security, Deployment and Recovery

### Tasks

-   Configure production secrets outside source control.
-   Restrict service and database network access.
-   Configure TLS where appropriate for the LAN deployment.
-   Validate session expiry, lockout, revocation and permission checks.
-   Protect attachments and audit their access.
-   Schedule encrypted backups to a separate protected location.
-   Test database and file restoration.
-   Document server startup, shutdown, backup, restore and incident
    procedures.
-   Check logs for accidental exposure of passwords, tokens or sensitive
    student data.

### Exit criteria

-   Clean installation and deployment are documented.
-   Backup restoration succeeds.
-   The college can recover required database records and attachments.
-   Critical security tests pass.

## 12. Phase 9 --- Data Migration, Pilot and Go-Live

### Tasks

-   Confirm legal entity, accounting basis, financial year and academic
    calendar.
-   Clean and approve student master data and fee schedules.
-   Reconcile opening student dues, supplier balances, bank balances and
    general-ledger balances.
-   Import only approved data with a traceable import log.
-   Train Super Admins and staff by role.
-   Run a controlled pilot and compare outputs against existing records.
-   Resolve differences before production cutover.
-   Obtain written approval from college management and the accountant.

### Exit criteria

-   Opening balances and subledgers reconcile.
-   Staff understand approval and correction workflows.
-   Required reports and documents are accepted.
-   Backup/restore and operational support arrangements are signed off.

## 13. Phase 10 --- Deferred Enhancements

Only after the initial release is stable: - Inventory and stock
tracking. - Payroll. - Payment gateway integrations. - Additional
analytics and management dashboards. - Other integrations approved by
the college.

Each enhancement needs a separate scope, impact assessment, tests and
acceptance criteria.

## 14. Cross-Cutting Acceptance Tests

### Super Admin and permissions

-   Create/deactivate users and assign custom roles.
-   Confirm restricted users are blocked at the API.
-   Confirm the last active Super Admin cannot be removed accidentally.
-   Confirm sensitive administrative actions are logged.
-   Confirm Super Admin cannot silently alter posted financial history.

### Accounting

-   Balanced journals, valid accounts and locked periods.
-   Idempotent posting and duplicate request rejection.
-   Reversal and correction workflows retain history.
-   Reconciliation of student/supplier subledgers to GL.

### Student fees and documents

-   Reusable fee structure calculations.
-   Partial payment, concession, refund and outstanding balance tests.
-   Correct Fee Due Notice and final receipt generation.
-   All six student documents and their approval/reprint histories.

### Supplier/payables

-   Duplicate invoice checks.
-   Approval, posting, payment allocation and ageing.
-   Supplier-to-GL reconciliation.

### Operations

-   Test database isolation.
-   Backup and restore of database plus attachments.
-   LAN access restrictions.
-   No exposed production secrets.

## 15. Decisions That Must Be Confirmed

1.  Legal entity and accounting basis.
2.  Official academic-year calendar and fee schedule.
3.  Opening balances, student dues and supplier balances.
4.  Applicable GST/TDS registration and treatment.
5.  Named Super Admins and staff role assignments.
6.  Fee-counter approval workflow.
7.  Authorities for concessions, refunds and certificates.
8.  Official document templates and signatories.
9.  Server, LAN access and backup destination.

## 16. Release Gate

**Do not go live solely because the README reports a passing test count
or completed phases.** Verify the actual source code and current test
results, rotate exposed credentials, run migrations against a test copy,
reconcile financial outputs and demonstrate a clean restore before
production use.
