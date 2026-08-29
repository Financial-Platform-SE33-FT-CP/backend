"""Subscription plan definitions shared across services."""

from enum import StrEnum
from typing import TypedDict


class PlanTier(StrEnum):
    STARTER = "starter"
    GROWTH = "growth"
    PRO = "pro"


class PlanLimits(TypedDict):
    max_users: int | None
    max_monthly_invoices: int | None
    features: list[str]


PLAN_LIMITS: dict[PlanTier, PlanLimits] = {
    PlanTier.STARTER: {
        "max_users": 3,
        "max_monthly_invoices": 100,
        "features": ["basic_reports"],
    },
    PlanTier.GROWTH: {
        "max_users": 10,
        "max_monthly_invoices": 500,
        "features": [
            "basic_reports",
            "approval_workflow",
            "cash_forecasting",
            "api_access",
        ],
    },
    PlanTier.PRO: {
        "max_users": None,
        "max_monthly_invoices": None,
        "features": [
            "basic_reports",
            "approval_workflow",
            "cash_forecasting",
            "api_access",
            "multi_entity",
            "advanced_analytics",
        ],
    },
}
