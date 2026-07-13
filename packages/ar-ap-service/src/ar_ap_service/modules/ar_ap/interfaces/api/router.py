"""AR/AP API router (US-8: customer invoicing)."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status

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
    get_bill_payment_service,
    get_bill_service,
    get_credit_note_service,
    get_current_user_id,
    get_gst_service,
    get_invoice_service,
    get_payment_service,
    require_tenant_id,
)
from ar_ap_service.modules.ar_ap.application.dto import (
    BillLineInput,
    CreateBillCommand,
    CreateInvoiceCommand,
    CreditNoteLineInput,
    InvoiceLineInput,
    IssueCreditNoteCommand,
    PayBillCommand,
    RecordPaymentCommand,
    UpdateBillCommand,
    UpdateInvoiceCommand,
)
from ar_ap_service.modules.ar_ap.application.services import (
    BillPaymentService,
    BillService,
    CreditNoteService,
    GstService,
    InvoiceService,
    PaymentService,
)
from ar_ap_service.modules.ar_ap.domain.entities import Customer, Vendor
from ar_ap_service.modules.ar_ap.interfaces.api.schemas import (
    APAgingLineResponse,
    BillPaymentResponse,
    BillResponse,
    BillSettlementResponse,
    CreateBillRequest,
    CreateCustomerRequest,
    CreateInvoiceRequest,
    CreateVendorRequest,
    CreditNoteResponse,
    CustomerResponse,
    GstCodeResponse,
    GstSummaryResponse,
    InvoiceResponse,
    InvoiceSettlementResponse,
    IssueCreditNoteRequest,
    PayBillRequest,
    PaymentResponse,
    RecordPaymentRequest,
    UpdateBillRequest,
    UpdateInvoiceRequest,
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
                gst_code_id=line.gst_code_id,
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
                gst_code_id=line.gst_code_id,
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
                gst_code_id=line.gst_code_id,
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


# ── bills (US-11 / US-12) ────────────────────────────────────────────────────


def _to_create_bill_command(body: CreateBillRequest) -> CreateBillCommand:
    return CreateBillCommand(
        vendor_id=body.vendor_id,
        issue_date=body.issue_date,
        due_date=body.due_date,
        lines=[
            BillLineInput(
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_code_id=line.gst_code_id,
                gst_rate=line.gst_rate,
            )
            for line in body.lines
        ],
    )


def _to_update_bill_command(body: UpdateBillRequest) -> UpdateBillCommand:
    lines = None
    if body.lines is not None:
        lines = [
            BillLineInput(
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_code_id=line.gst_code_id,
                gst_rate=line.gst_rate,
            )
            for line in body.lines
        ]
    return UpdateBillCommand(
        vendor_id=body.vendor_id,
        issue_date=body.issue_date,
        due_date=body.due_date,
        lines=lines,
    )


@router.post(
    "/bills",
    response_model=BillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bill(
    body: CreateBillRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_CREATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> BillResponse:
    bill = await service.create_draft(tenant_id, _to_create_bill_command(body), user_id)
    return BillResponse.from_entity(bill)


@router.get("/bills", response_model=list[BillResponse])
async def list_bills(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
    bill_status: Annotated[str | None, Query(alias="status")] = None,
    vendor_id: UUID | None = None,
    issued_from: date | None = None,
    issued_to: date | None = None,
) -> list[BillResponse]:
    bills = await service.list_bills(
        tenant_id,
        status=bill_status,
        vendor_id=vendor_id,
        issued_from=issued_from,
        issued_to=issued_to,
    )
    return [BillResponse.from_entity(b) for b in bills]


@router.get("/bills/ap-aging", response_model=list[APAgingLineResponse])
async def get_ap_aging(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillPaymentService, Depends(get_bill_payment_service)],
    as_of: date | None = None,
) -> list[APAgingLineResponse]:
    lines = await service.get_ap_aging(tenant_id, as_of=as_of)
    return [APAgingLineResponse.from_entity(line) for line in lines]


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
    bill = await service.update_draft(tenant_id, bill_id, _to_update_bill_command(body))
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
    "/vendors",
    response_model=VendorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_vendor(
    body: CreateVendorRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_CREATE))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> VendorResponse:
    vendor = await service.create_vendor(
        Vendor(tenant_id=tenant_id, name=body.name, email=body.email)
    )
    return VendorResponse(
        id=vendor.id,
        tenant_id=vendor.tenant_id,
        name=vendor.name,
        email=vendor.email,
    )


@router.get("/vendors", response_model=list[VendorResponse])
async def list_vendors(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillService, Depends(get_bill_service)],
) -> list[VendorResponse]:
    vendors = await service.list_vendors(tenant_id)
    return [
        VendorResponse(id=v.id, tenant_id=v.tenant_id, name=v.name, email=v.email) for v in vendors
    ]


@router.post(
    "/bills/{bill_id}/payments",
    response_model=BillPaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def pay_bill(
    bill_id: UUID,
    body: PayBillRequest,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_POST))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    user_id: Annotated[UserId, Depends(get_current_user_id)],
    service: Annotated[BillPaymentService, Depends(get_bill_payment_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BillPaymentResponse:
    command = PayBillCommand(
        payment_date=body.payment_date,
        amount=body.amount,
        payment_method=body.payment_method,
        reference=body.reference,
        payment_account_id=body.payment_account_id,
        idempotency_key=body.idempotency_key or idempotency_key,
    )
    payment = await service.pay_bill(tenant_id, bill_id, command, user_id)
    return BillPaymentResponse.from_entity(payment)


@router.get("/bills/{bill_id}/payments", response_model=list[BillPaymentResponse])
async def list_bill_payments(
    bill_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillPaymentService, Depends(get_bill_payment_service)],
) -> list[BillPaymentResponse]:
    payments = await service.list_bill_payments(tenant_id, bill_id)
    return [BillPaymentResponse.from_entity(p) for p in payments]


@router.get("/bills/{bill_id}/settlement", response_model=BillSettlementResponse)
async def get_bill_settlement(
    bill_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillPaymentService, Depends(get_bill_payment_service)],
) -> BillSettlementResponse:
    settlement = await service.get_bill_settlement(tenant_id, bill_id)
    return BillSettlementResponse.from_entity(bill_id, settlement)


@router.get("/bill-payments", response_model=list[BillPaymentResponse])
async def list_bill_payments_all(
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillPaymentService, Depends(get_bill_payment_service)],
    bill_id: UUID | None = None,
    vendor_id: UUID | None = None,
    payment_method: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[BillPaymentResponse]:
    payments = await service.list_payments(
        tenant_id,
        bill_id=bill_id,
        vendor_id=vendor_id,
        payment_method=payment_method,
        date_from=date_from,
        date_to=date_to,
    )
    return [BillPaymentResponse.from_entity(p) for p in payments]


@router.get("/bill-payments/{payment_id}", response_model=BillPaymentResponse)
async def get_bill_payment(
    payment_id: UUID,
    _: Annotated[None, Depends(RequireArApPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[BillPaymentService, Depends(get_bill_payment_service)],
) -> BillPaymentResponse:
    payment = await service.get_payment(tenant_id, payment_id)
    return BillPaymentResponse.from_entity(payment)


@router.get(
    "/gst/codes",
    response_model=list[GstCodeResponse],
)
async def list_gst_codes(
    _: Annotated[
        None,
        Depends(RequireArApPermission(P_ACCOUNTING_READ)),
    ],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[GstService, Depends(get_gst_service)],
    active_only: bool = True,
) -> list[GstCodeResponse]:
    codes = await service.list_codes(
        tenant_id,
        active_only=active_only,
    )
    return [GstCodeResponse.from_entity(code) for code in codes]


@router.post(
    "/gst/codes/defaults",
    response_model=list[GstCodeResponse],
)
async def initialize_default_gst_codes(
    _: Annotated[
        None,
        Depends(RequireArApPermission(P_ACCOUNTING_CREATE)),
    ],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[GstService, Depends(get_gst_service)],
) -> list[GstCodeResponse]:
    codes = await service.ensure_default_codes(tenant_id)

    return [GstCodeResponse.from_entity(code) for code in codes]


@router.get(
    "/gst/summary",
    response_model=GstSummaryResponse,
)
async def get_gst_summary(
    _: Annotated[
        None,
        Depends(RequireArApPermission(P_ACCOUNTING_READ)),
    ],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[GstService, Depends(get_gst_service)],
    reporting_period: Annotated[
        str,
        Query(min_length=1, max_length=32),
    ],
) -> GstSummaryResponse:
    summary = await service.get_summary(
        tenant_id,
        reporting_period,
    )
    return GstSummaryResponse.from_entity(summary)


@router.get(
    "/gst/export",
    response_class=Response,
)
async def export_gst_summary(
    _: Annotated[
        None,
        Depends(RequireArApPermission(P_ACCOUNTING_READ)),
    ],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[GstService, Depends(get_gst_service)],
    reporting_period: Annotated[
        str,
        Query(min_length=1, max_length=32),
    ],
) -> Response:
    csv_bytes, filename = await service.build_summary_csv(
        tenant_id,
        reporting_period,
    )

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
