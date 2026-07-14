"""AR/AP API router (US-8: customer invoicing)."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import Response

from accounting_shared.rbac import (
    P_ACCOUNTING_CREATE,
    P_ACCOUNTING_DELETE,
    P_ACCOUNTING_POST,
    P_ACCOUNTING_READ,
    P_ACCOUNTING_UPDATE,
)
from accounting_shared.types import TenantId, UserId
from ar_ap_service.deps import (
    RequireArApPermission,
    get_bank_account_repository,
    get_bank_statement_service,
    get_bill_service,
    get_credit_note_service,
    get_current_user_id,
    get_invoice_service,
    get_payment_service,
    get_reconciliation_service,
    require_tenant_id,
)
from ar_ap_service.modules.ar_ap.application.dto import (
    CreateInvoiceCommand,
    CreditNoteLineInput,
    InvoiceLineInput,
    IssueCreditNoteCommand,
    ReconcileTransactionCommand,
    RecordPaymentCommand,
    UpdateInvoiceCommand,
    UploadBankStatementCommand,
)
from ar_ap_service.modules.ar_ap.application.bank_statement import BankStatementService
from ar_ap_service.modules.ar_ap.application.bill_service import BillService
from ar_ap_service.modules.ar_ap.application.reconciliation import ReconciliationService
from ar_ap_service.modules.ar_ap.application.services import (
    CreditNoteService,
    InvoiceService,
    PaymentService,
)
from ar_ap_service.modules.ar_ap.domain.entities import (
    BankAccount,
    Bill,
    BillPayment,
    Customer,
    PaymentMethod,
    Vendor,
)
from ar_ap_service.modules.ar_ap.interfaces.api.schemas import (
    APAgingLineResponse,
    BankAccountResponse,
    BankTransactionResponse,
    BillLineResponse,
    BillPaymentResponse,
    BillResponse,
    BillSettlementResponse,
    CreateBankAccountRequest,
    CreateBillRequest,
    CreateCustomerRequest,
    CreateInvoiceRequest,
    CreateVendorRequest,
    CreditNoteResponse,
    CustomerResponse,
    InvoiceResponse,
    InvoiceSettlementResponse,
    IssueCreditNoteRequest,
    PayBillRequest,
    PaymentResponse,
    ReconciliationSuggestionResponse,
    ReconcileTransactionRequest,
    RecordPaymentRequest,
    UpdateBillRequest,
    UpdateInvoiceRequest,
    UploadBankStatementRequest,
    VendorResponse,
)

router = APIRouter(tags=["ar-ap"])


@router.get("/health-complete")
async def health_complete() -> dict[str, str]:
    """Combined health check for the AR/AP module."""
    return {"status": "ok"}


def _to_create_command(body: CreateInvoiceRequest) -> CreateInvoiceCommand:
    return CreateInvoiceCommand(
        customer_id=body.customer_id,
        issue_date=body.issue_date,
        due_date=body.due_date,
        lines=[
            InvoiceLineInput(
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_rate=line.gst_rate,
            )
            for line in body.lines
        ],
    )


def _to_update_command(body: UpdateInvoiceRequest) -> UpdateInvoiceCommand:
    lines = None
    if body.lines is not None:
        lines = [
            InvoiceLineInput(
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_rate=line.gst_rate,
            )
            for line in body.lines
        ]
    return UpdateInvoiceCommand(
        customer_id=body.customer_id,
        issue_date=body.issue_date,
        due_date=body.due_date,
        lines=lines,
    )


@router.post(
    "/invoices",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice(
    body: CreateInvoiceRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_CREATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceResponse:
    invoice = await service.create_draft(tenant_id, _to_create_command(body), user_id)
    return InvoiceResponse.from_entity(invoice)


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    invoice_status: Annotated[str | None, Query(alias="status")] = None,
    customer_id: UUID | None = None,
    issued_from: date | None = None,
    issued_to: date | None = None,
) -> list[InvoiceResponse]:
    invoices = await service.list_invoices(
        tenant_id,
        status=invoice_status,
        customer_id=customer_id,
        issued_from=issued_from,
        issued_to=issued_to,
    )
    return [InvoiceResponse.from_entity(inv) for inv in invoices]


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceResponse:
    invoice = await service.get_invoice(tenant_id, invoice_id)
    return InvoiceResponse.from_entity(invoice)


@router.get("/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> Response:
    pdf_bytes, filename = await service.build_invoice_pdf(tenant_id, invoice_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: UUID,
    body: UpdateInvoiceRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_UPDATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceResponse:
    invoice = await service.update_draft(tenant_id, invoice_id, _to_update_command(body))
    return InvoiceResponse.from_entity(invoice)


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceResponse)
async def issue_invoice(
    invoice_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_POST))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceResponse:
    invoice = await service.issue_invoice(tenant_id, invoice_id, user_id)
    return InvoiceResponse.from_entity(invoice)


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(
    invoice_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_DELETE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> None:
    await service.delete_draft(tenant_id, invoice_id)


@router.post(
    "/customers",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_customer(
    body: CreateCustomerRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_CREATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> CustomerResponse:
    customer = await service.create_customer(
        Customer(
            tenant_id=tenant_id,
            name=body.name,
            email=body.email,
            credit_terms_days=body.credit_terms_days,
        )
    )
    return CustomerResponse(
        id=customer.id,
        tenant_id=customer.tenant_id,
        name=customer.name,
        email=customer.email,
        credit_terms_days=customer.credit_terms_days,
    )


@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> list[CustomerResponse]:
    customers = await service.list_customers(tenant_id)
    return [
        CustomerResponse(
            id=c.id,
            tenant_id=c.tenant_id,
            name=c.name,
            email=c.email,
            credit_terms_days=c.credit_terms_days,
        )
        for c in customers
    ]


# ── payments (US-9) ──────────────────────────────────────────────────────────


@router.post(
    "/invoices/{invoice_id}/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_payment(
    invoice_id: UUID,
    body: RecordPaymentRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_POST))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PaymentResponse:
    command = RecordPaymentCommand(
        payment_date=body.payment_date,
        amount=body.amount,
        payment_method=body.payment_method,
        reference=body.reference,
        deposit_account_id=body.deposit_account_id,
        idempotency_key=body.idempotency_key or idempotency_key,
    )
    payment = await service.record_payment(tenant_id, invoice_id, command, user_id)
    return PaymentResponse.from_entity(payment)


@router.get("/invoices/{invoice_id}/payments", response_model=list[PaymentResponse])
async def list_invoice_payments(
    invoice_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> list[PaymentResponse]:
    payments = await service.list_invoice_payments(tenant_id, invoice_id)
    return [PaymentResponse.from_entity(p) for p in payments]


@router.get(
    "/invoices/{invoice_id}/settlement",
    response_model=InvoiceSettlementResponse,
)
async def get_invoice_settlement(
    invoice_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> InvoiceSettlementResponse:
    settlement = await service.get_invoice_settlement(tenant_id, invoice_id)
    return InvoiceSettlementResponse.from_entity(invoice_id, settlement)


@router.get("/payments", response_model=list[PaymentResponse])
async def list_payments(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
    invoice_id: UUID | None = None,
    customer_id: UUID | None = None,
    payment_method: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[PaymentResponse]:
    payments = await service.list_payments(
        tenant_id,
        invoice_id=invoice_id,
        customer_id=customer_id,
        payment_method=payment_method,
        date_from=date_from,
        date_to=date_to,
    )
    return [PaymentResponse.from_entity(p) for p in payments]


@router.get("/payments/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentResponse:
    payment = await service.get_payment(tenant_id, payment_id)
    return PaymentResponse.from_entity(payment)


# ── credit notes (US-10) ─────────────────────────────────────────────────────


def _to_issue_credit_note_command(
    body: IssueCreditNoteRequest,
    header_idempotency_key: str | None,
) -> IssueCreditNoteCommand:
    return IssueCreditNoteCommand(
        issue_date=body.issue_date,
        reason=body.reason,
        lines=[
            CreditNoteLineInput(
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_rate=line.gst_rate,
                invoice_line_id=line.invoice_line_id,
            )
            for line in body.lines
        ],
        idempotency_key=body.idempotency_key or header_idempotency_key,
    )


@router.post(
    "/invoices/{invoice_id}/credit-notes",
    response_model=CreditNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_credit_note(
    invoice_id: UUID,
    body: IssueCreditNoteRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_POST))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[CreditNoteService, Depends(get_credit_note_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreditNoteResponse:
    command = _to_issue_credit_note_command(body, idempotency_key)
    credit_note = await service.issue_credit_note(tenant_id, invoice_id, command, user_id)
    return CreditNoteResponse.from_entity(credit_note)


@router.get(
    "/invoices/{invoice_id}/credit-notes",
    response_model=list[CreditNoteResponse],
)
async def list_invoice_credit_notes(
    invoice_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[CreditNoteService, Depends(get_credit_note_service)],
) -> list[CreditNoteResponse]:
    credit_notes = await service.list_invoice_credit_notes(tenant_id, invoice_id)
    return [CreditNoteResponse.from_entity(cn) for cn in credit_notes]


@router.get("/credit-notes", response_model=list[CreditNoteResponse])
async def list_credit_notes(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[CreditNoteService, Depends(get_credit_note_service)],
    invoice_id: UUID | None = None,
    customer_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[CreditNoteResponse]:
    credit_notes = await service.list_credit_notes(
        tenant_id,
        invoice_id=invoice_id,
        customer_id=customer_id,
        date_from=date_from,
        date_to=date_to,
    )
    return [CreditNoteResponse.from_entity(cn) for cn in credit_notes]


@router.get("/credit-notes/{credit_note_id}", response_model=CreditNoteResponse)
async def get_credit_note(
    credit_note_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[CreditNoteService, Depends(get_credit_note_service)],
) -> CreditNoteResponse:
    credit_note = await service.get_credit_note(tenant_id, credit_note_id)
    return CreditNoteResponse.from_entity(credit_note)


# ── bank statement upload (US-13) ──────────────────────────────────────────────


@router.post(
    "/bank-statements/upload",
    response_model=list[BankTransactionResponse],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Invalid CSV format"},
    },
)
async def upload_bank_statement(
    body: UploadBankStatementRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_CREATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    bank_statement_service: Annotated[BankStatementService, Depends(get_bank_statement_service)],
) -> list[BankTransactionResponse]:
    command = UploadBankStatementCommand(
        bank_account_id=body.bank_account_id,
        csv_content=body.csv_content,
    )
    transactions = await bank_statement_service.upload_statement(tenant_id, command)
    return [BankTransactionResponse.from_entity(t) for t in transactions]


# ── reconciliation (US-14) ────────────────────────────────────────────────────


@router.get(
    "/bank-transactions/unmatched",
    response_model=list[BankTransactionResponse],
)
async def list_unmatched(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    reconciliation_service: Annotated[ReconciliationService, Depends(get_reconciliation_service)],
    bank_account_id: UUID | None = None,
) -> list[BankTransactionResponse]:
    transactions = await reconciliation_service.list_unmatched(
        tenant_id,
        bank_account_id=bank_account_id,
    )
    return [BankTransactionResponse.from_entity(t) for t in transactions]


@router.get(
    "/bank-transactions/matched",
    response_model=list[BankTransactionResponse],
)
async def list_matched(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    reconciliation_service: Annotated[ReconciliationService, Depends(get_reconciliation_service)],
    bank_account_id: UUID | None = None,
) -> list[BankTransactionResponse]:
    transactions = await reconciliation_service.list_matched(
        tenant_id,
        bank_account_id=bank_account_id,
    )
    return [BankTransactionResponse.from_entity(t) for t in transactions]


@router.get(
    "/bank-transactions/{transaction_id}/suggestions",
    response_model=list[ReconciliationSuggestionResponse],
)
async def get_reconciliation_suggestions(
    transaction_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    reconciliation_service: Annotated[ReconciliationService, Depends(get_reconciliation_service)],
) -> list[ReconciliationSuggestionResponse]:
    suggestions = await reconciliation_service.suggest_matches(tenant_id, transaction_id)
    return [ReconciliationSuggestionResponse.from_entity(s) for s in suggestions]


@router.post(
    "/bank-transactions/reconcile",
    response_model=BankTransactionResponse,
    responses={
        400: {"description": "Transaction already reconciled or invalid"},
        404: {"description": "Transaction not found"},
    },
)
async def reconcile_transaction(
    body: ReconcileTransactionRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_POST))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    reconciliation_service: Annotated[ReconciliationService, Depends(get_reconciliation_service)],
) -> BankTransactionResponse:
    command = ReconcileTransactionCommand(
        transaction_id=body.transaction_id,
        match_type=body.match_type,
        match_id=body.match_id,
        account_id=body.account_id,
    )
    transaction = await reconciliation_service.confirm_match(tenant_id, user_id, command)
    return BankTransactionResponse.from_entity(transaction)


# ── bank accounts ────────────────────────────────────────────────────────────


@router.post(
    "/bank-accounts",
    response_model=BankAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bank_account(
    body: CreateBankAccountRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_CREATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    bank_account_repo=Depends(get_bank_account_repository),
) -> BankAccountResponse:
    account = BankAccount(
        tenant_id=tenant_id,
        name=body.name,
        account_number=body.account_number,
        currency=body.currency,
        opening_balance=body.opening_balance,
    )
    created = await bank_account_repo.add(account)
    return BankAccountResponse.from_entity(created)


@router.get("/bank-accounts", response_model=list[BankAccountResponse])
async def list_bank_accounts(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    bank_account_repo=Depends(get_bank_account_repository),
) -> list[BankAccountResponse]:
    accounts = await bank_account_repo.list_by_tenant(tenant_id)
    return [BankAccountResponse.from_entity(a) for a in accounts]


# ── bills / AP (US-11 / US-12) ────────────────────────────────────────────────


def _bill_lines_to_input(lines: list) -> list[dict]:
    return [line.model_dump() for line in lines]


@router.post("/bills", response_model=BillResponse, status_code=status.HTTP_201_CREATED)
async def create_bill(
    body: CreateBillRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_CREATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> BillResponse:
    bill = await service.create_draft(
        tenant_id,
        body.vendor_id,
        issue_date=body.issue_date,
        due_date=body.due_date,
        lines_input=_bill_lines_to_input(body.lines),
        created_by=user_id,
    )
    return BillResponse.from_entity(bill)


@router.get("/bills", response_model=list[BillResponse])
async def list_bills(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
    status: Annotated[str | None, Query(alias="status")] = None,
    vendor_id: UUID | None = None,
    issued_from: date | None = None,
    issued_to: date | None = None,
) -> list[BillResponse]:
    bills = await service.list_bills(
        tenant_id, status=status, vendor_id=vendor_id, issued_from=issued_from, issued_to=issued_to
    )
    return [BillResponse.from_entity(b) for b in bills]


# Static paths MUST come before dynamic {bill_id} to avoid UUID parse errors.


@router.get("/bills/ap-aging", response_model=list[APAgingLineResponse])
async def get_ap_aging(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
    as_of: date | None = None,
) -> list[APAgingLineResponse]:
    rows = await service.get_ap_aging(tenant_id, as_of=as_of)
    return [APAgingLineResponse(**row) for row in rows]


@router.post("/vendors", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    body: CreateVendorRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_CREATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> VendorResponse:
    vendor = await service.create_vendor(tenant_id, name=body.name, email=body.email)
    return VendorResponse.from_entity(vendor)


@router.get("/vendors", response_model=list[VendorResponse])
async def list_vendors(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> list[VendorResponse]:
    vendors = await service.list_vendors(tenant_id)
    return [VendorResponse.from_entity(v) for v in vendors]


# ── dynamic bill routes (must come after static routes) ───────────────────────


@router.get("/bills/{bill_id}", response_model=BillResponse)
async def get_bill(
    bill_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> BillResponse:
    bill = await service.get_bill(tenant_id, bill_id)
    return BillResponse.from_entity(bill)


@router.put("/bills/{bill_id}", response_model=BillResponse)
async def update_bill(
    bill_id: UUID,
    body: UpdateBillRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_UPDATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> BillResponse:
    lines_input = _bill_lines_to_input(body.lines) if body.lines is not None else None
    bill = await service.update_draft(
        tenant_id,
        bill_id,
        vendor_id=body.vendor_id,
        issue_date=body.issue_date,
        due_date=body.due_date,
        lines_input=lines_input,
    )
    return BillResponse.from_entity(bill)


@router.post("/bills/{bill_id}/record", response_model=BillResponse)
async def record_bill(
    bill_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_POST))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> BillResponse:
    bill = await service.record_bill(tenant_id, bill_id, user_id)
    return BillResponse.from_entity(bill)


@router.delete("/bills/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bill(
    bill_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_DELETE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> None:
    await service.delete_draft(tenant_id, bill_id)


@router.post(
    "/bills/{bill_id}/payments", response_model=BillResponse, status_code=status.HTTP_201_CREATED
)
async def pay_bill(
    bill_id: UUID,
    body: PayBillRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_POST))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> BillResponse:
    bill = await service.pay_bill(
        tenant_id,
        bill_id,
        payment_date=body.payment_date,
        amount=body.amount,
        payment_method=PaymentMethod(body.payment_method),
        reference=body.reference,
        payment_account_id=body.payment_account_id,
        created_by=user_id,
    )
    return BillResponse.from_entity(bill)


@router.get("/bills/{bill_id}/payments", response_model=list[BillPaymentResponse])
async def list_bill_payments(
    bill_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> list[BillPaymentResponse]:
    payments = await service.list_bill_payments(tenant_id, bill_id)
    return [BillPaymentResponse.from_entity(p) for p in payments]


@router.get("/bills/{bill_id}/settlement", response_model=BillSettlementResponse)
async def get_bill_settlement(
    bill_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> BillSettlementResponse:
    total, paid = await service.get_bill_settlement(tenant_id, bill_id)
    return BillSettlementResponse.from_entity(bill_id, total, paid)
