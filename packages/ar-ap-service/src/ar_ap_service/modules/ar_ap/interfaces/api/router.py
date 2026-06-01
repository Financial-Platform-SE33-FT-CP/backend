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
    get_current_user_id,
    get_invoice_service,
    get_payment_service,
    require_tenant_id,
)
from ar_ap_service.modules.ar_ap.application.dto import (
    CreateInvoiceCommand,
    InvoiceLineInput,
    RecordPaymentCommand,
    UpdateInvoiceCommand,
)
from ar_ap_service.modules.ar_ap.application.services import InvoiceService, PaymentService
from ar_ap_service.modules.ar_ap.domain.entities import Customer
from ar_ap_service.modules.ar_ap.interfaces.api.schemas import (
    CreateCustomerRequest,
    CreateInvoiceRequest,
    CustomerResponse,
    InvoiceResponse,
    InvoiceSettlementResponse,
    PaymentResponse,
    RecordPaymentRequest,
    UpdateInvoiceRequest,
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
