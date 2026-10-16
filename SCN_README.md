# SCN College Accounting Application

**Institution:** Shri Chamatkari Santji College of Nursing\
**Location:** VPO Girawar, Tehsil Meham, Rohtak, Haryana\
**Purpose:** Centralised accounting, student fee management,
supplier/payables management, document generation, and controlled
administration.

> **Project status:** This README describes the intended revised system
> and acceptance requirements. It does not certify that every feature is
> already implemented. Verify the repository, tests, deployment
> configuration, and database before treating the application as
> production-ready.

## 1. Objectives

The application is intended to provide one reliable source of truth for
college finance and related student administration:

-   Double-entry accounting and general ledger.
-   Student master records and student receivables/debtor ledgers.
-   Reusable course-wise and academic-year-wise fee structures.
-   Fee assessments, due notices, collections, receipts, concessions,
    refunds, and outstanding dues.
-   Customisable document templates and controlled issuance of student
    documents.
-   Supplier master, invoices, payments, allocations, and payable
    ageing.
-   Fixed assets, depreciation, bank reconciliation, and applicable tax
    registers.
-   Super Admin, user administration, granular role-based access,
    approval workflows, and audit history.
-   Financial reports, exports, backups, and recovery procedures.
-   Browser access from authorised computers on the college LAN.

Initial courses to support: - B.Sc. Nursing - Post Basic B.Sc. Nursing -
GNM - ANM

The initial expected student population is approximately 250--300. The
system should remain configurable as enrolment and requirements change.

## 2. Proposed Technical Architecture

  -----------------------------------------------------------------------
  Layer                               Proposed technology
  ----------------------------------- -----------------------------------
  Web interface                       React-based browser frontend

  API/backend                         Python with FastAPI

  Database                            PostgreSQL

  ORM and schema migrations           SQLAlchemy 2.x and Alembic

  Authentication                      Secure sessions or short-lived JWT
                                      access tokens; strong password
                                      hashing

  PDF generation                      ReportLab

  Excel export                        openpyxl

  Tests                               pytest, HTTPX, frontend and browser
                                      tests

  Deployment                          College server accessible over the
                                      secured LAN

  File storage                        Protected local/server storage with
                                      metadata and integrity hashes
  -----------------------------------------------------------------------

**Request flow:** Browser → FastAPI → PostgreSQL and protected document
storage.

An existing Flet client may be retained during transition if it uses the
same backend and accounting records. Do not create a second ledger or
duplicate accounting rules in the frontend.

## 3. Core Modules

### 3.1 Super Admin and permissions

The Super Admin has full system-administration rights, including:

-   Create, edit, deactivate and reactivate user accounts.
-   Assign roles and permissions; create custom roles.
-   Control access to modules, actions, records and sensitive fields.
-   Configure approval rules, document templates, numbering, academic
    years and financial periods.
-   Review user activity, audit records and security events.
-   Revoke sessions and initiate approved backup/recovery procedures.
-   Manage system settings and review application health.

**Financial safeguard:** Super Admin privileges must not silently
overwrite or erase posted transactions or audit records. Posted entries
must be corrected through controlled reversals, adjustments or edit
requests. Every privileged action must be audited.

Suggested starting roles: - Super Admin - Admin / System Administrator -
Maker - Checker - Approver - Accounts Staff - Admission Staff - Fee
Counter Staff - Viewer / Auditor

Roles and permissions must be configurable. Enforce permissions on the
backend for every protected API; hiding interface controls alone is
insufficient. Prevent self-approval and protect the last active Super
Admin from accidental removal.

### 3.2 Student master and debtor ledger

Maintain admission number, registration/enrollment number, student
details, course, batch, academic year, current year/semester, admission
status, fee category, approved concessions and document history.

The student ledger should show: - Charges and fee heads. - Opening
balances where applicable. - Concessions, scholarships and approved
adjustments. - Payments, allocations and refunds. - Due dates, overdue
amounts and outstanding balance.

Student receivables must reconcile to the general ledger. Retain
historical records for graduates, transfers and students who leave.

### 3.3 Reusable fee structures

Authorised staff can maintain versioned fee structures by course,
academic year, year/semester, fee head, category, installment and due
date. Applying a saved structure should populate student fee assessments
without repeated manual entry.

Keep historical versions, validate totals, prevent duplicate fee-head
entries and require approval for configured changes. Changes to a fee
structure must not silently alter already-issued dues.

### 3.4 Fee due notices and receipts

Generate a printable Fee Due Notice with student details, fee heads,
amounts charged, payments, balance and due date.

When a payment is received: 1. Select the student and applicable
outstanding fee items. 2. Validate amount and payment mode. 3. Apply the
configured review/approval process. 4. Post the payment and its
accounting entries atomically. 5. Update student dues and generate the
numbered Fee Receipt / Payment Acknowledgement.

Support relevant payment modes such as cash, cheque, demand draft,
NEFT/RTGS and online reference, subject to college practice. Only
completed, posted transactions should be represented as final accounting
receipts.

### 3.5 Student document generation

The system should generate and track: 1. Fee Receipt / Payment
Acknowledgement. 2. Admission / Seat Allotment Confirmation Letter. 3.
College Identity Card. 4. Enrollment / Registration Number Slip. 5. Fee
Concession / Scholarship Order, when approved. 6. Bonafide Certificate,
on request and after required verification.

Documents should use saved student data and configurable templates.
Record document number, issue date, academic year, template version,
creator, approver, status and reprint history. Configure approval rules
for admission letters, concessions and bonafide certificates.

### 3.6 Supplier and accounts payable

Maintain supplier details, applicable tax identifiers, payment terms and
restricted supplier bank details.

Workflow: supplier invoice draft → supporting documents → validation →
checker → approver → posted payable. Payments must be approved, posted
and allocated to invoices. Include duplicate invoice/payment controls,
over-allocation prevention, outstanding balances, ageing and
supplier-to-GL reconciliation.

### 3.7 Accounting and financial controls

Support chart of accounts, opening balances,
payment/receipt/journal/contra vouchers, fee-linked accounting, supplier
invoices and payments, fixed assets, depreciation, bank reconciliation
and applicable GST/TDS registers.

Every posted journal must balance. Use decimal monetary arithmetic,
database transactions, unique references, idempotency controls, period
locks, source links and reversals rather than deleting posted
transactions.

### 3.8 Reports

Provide authorised on-screen and PDF/Excel reports, including: - Trial
Balance. - Income and Expenditure Statement. - Balance Sheet. - General
Ledger. - Cash Book and Bank Book. - Voucher Register. - Student Ledger,
Fee Dues and Collection Summary. - Concession/Scholarship Register with
restricted access. - Supplier Ledger and Payables Ageing. - Fixed Asset
and Depreciation Schedule. - Bank Reconciliation Statement. - Applicable
GST/TDS registers. - Audit and user-activity reports.

Reports must support appropriate date, financial-year, academic-year and
permission-based filters.

## 4. Accounting and Period Rules

-   Financial year: April--March.
-   Academic year: configurable; confirm the college's official calendar
    before production.
-   Fee dues are associated with the relevant academic year.
-   Voucher and receipt numbering is configurable, with
    financial-year-based numbering where required.
-   Closed periods must reject ordinary postings and backdated changes.
-   Reopening a period must be restricted, justified and audited.
-   Posted vouchers are immutable; corrections use approved reversals or
    adjustments.
-   Student receivables and supplier payables must reconcile with their
    corresponding general-ledger control accounts.

## 5. Security and Operational Requirements

-   Secure initial Super Admin setup; no shared default production
    credentials.
-   Strong passwords; MFA recommended for privileged accounts.
-   Server-side permission checks and least-privilege database access.
-   Session expiry, revocation and failed-login protections.
-   Protected attachments with file type/size validation and audited
    downloads.
-   Append-only audit events and tamper-evident hash-chain verification.
-   Encrypted backups stored separately from the application server.
-   Periodic restore tests covering database and required files.
-   Firewall-restricted LAN access; PostgreSQL must not be directly
    exposed to public networks.
-   Secrets kept out of source control and logs.
-   Privacy controls for student and supplier personal/financial
    information.

A hash chain is tamper-evident, not an absolute guarantee against every
privileged attack.

## 6. Database Entities

Reconcile these proposed entities with existing models before adding
tables:

-   `users`, `roles`, `permissions`, `user_roles`, `role_permissions`
-   `audit_log`, `system_settings`, `backup_history`
-   `accounts`, `vouchers`, `voucher_lines`, `edit_requests`
-   `attachments`, `financial_periods`
-   `students`, `courses`, `academic_years`
-   `fee_structures`, `fee_structure_lines`, `student_fee_assessments`,
    `fee_dues`
-   `fee_receipts`, `fee_receipt_lines`
-   `document_templates`, `issued_documents`
-   `suppliers`, `supplier_invoices`, `supplier_invoice_lines`
-   `supplier_payments`, `payment_allocations`
-   `assets`, `asset_depreciations`, `bank_transactions`

Use foreign keys, indexes, database constraints, and Alembic migrations.
Do not duplicate an existing entity without reviewing the current
schema.

## 7. Proposed API Areas

Endpoint names are design proposals and must be reconciled with the
existing API.

-   **Administration:** `/admin/users`, `/admin/roles`,
    `/admin/permissions`, `/admin/audit-log`, `/admin/backup`
-   **Students:** `/students`, `/students/{id}`, `/students/{id}/dues`
-   **Fees:** `/fees/structures`, `/fees/dues`, `/fees/due-notices`,
    `/fees/receipts`
-   **Documents:** `/admin/document-templates`,
    `/students/{id}/documents`, `/documents/{id}/pdf`
-   **Suppliers:** `/suppliers`, `/supplier-invoices`,
    `/supplier-payments`
-   **Payables:** `/payables/open`, `/payables/ageing`,
    `/payables/reconciliation`
-   **Accounting and reports:** existing voucher, ledger, reconciliation
    and report endpoints, after code audit

Every endpoint must validate the user's permissions and the
transaction's state, and write required audit events.

## 8. Development and Release Sequence

1.  **Audit baseline:** Inspect actual repository and tests, rotate
    credentials, verify backups and perform a restore test.
2.  **Accounting foundation:** Review ledger integrity, use Alembic
    migrations, implement period controls and safe/idempotent posting.
3.  **Super Admin/RBAC:** Build user management, custom roles, granular
    permissions, session revocation and security audit events.
4.  **Browser UI:** Deliver secure login, navigation, forms, approval
    queues and role-filtered views.
5.  **Student and fee management:** Student master, reusable fee
    structures, dues, notices, receipts, concessions and reconciliation.
6.  **Document generation:** Templates and all six requested document
    types, with numbering and issuance history.
7.  **Supplier/payables:** Supplier master, invoice workflow, payments,
    allocations, ageing and reconciliation.
8.  **Reporting validation:** Validate financial statements, fixed
    assets, bank reconciliation and applicable tax registers.
9.  **Deployment/pilot:** Configure LAN server, backups, user training,
    opening data and parallel checks.
10. **Future modules:** Inventory, payroll and other integrations only
    after separate approval.

## 9. Acceptance Criteria

Do not release to production until: - Super Admin can manage users,
roles and permissions securely. - Restricted users cannot access
protected APIs directly. - The last active Super Admin cannot be
accidentally removed. - Posted vouchers balance and cannot be silently
edited/deleted. - Duplicate requests cannot post the same transaction
twice. - Fee structures generate correct dues and historical versions
remain intact. - Posted payments update student ledgers and GL
correctly. - All six document types can be generated with controlled
issuance and reprint history. - Supplier invoices and payments reconcile
to the GL. - Reports reconcile to ledger balances. - Backups restore
successfully, including required attachments. - College management and
the accountant approve accounting policies and opening balances.

## 10. Decisions Required Before Production

Confirm with college management and the accountant: 1. Legal entity
operating the college and approved accounting basis. 2. Official
academic calendar, fee heads, fee amounts and instalments. 3. Student
records, opening student dues, opening ledger balances and bank
balances. 4. Applicable GST/TDS registrations and tax treatment. 5.
Named Super Admins and staff role/approval assignments. 6. Whether
counter collections use a streamlined approved workflow or full Maker →
Checker → Approver. 7. Approval authorities for concessions, refunds and
student documents. 8. Official college document templates and
signatories. 9. Server, LAN access, backup destination and recovery
responsibilities.

## 11. Production Readiness Warning

Documentation or a passing test count alone does not prove that the
current application is production-ready. Inspect the actual source code,
verify tests against the current commit, rotate any exposed credentials,
review migration behaviour and demonstrate recovery from a clean backup
before go-live.
