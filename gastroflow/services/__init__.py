from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AuthService": ("gastroflow.services.auth", "AuthService"),
    "AdminCrudService": ("gastroflow.services.admin_crud", "AdminCrudService"),
    "CRUD_TABLES": ("gastroflow.services.admin_crud", "CRUD_TABLES"),
    "ExpenseDetailInput": ("gastroflow.services.expenses", "ExpenseDetailInput"),
    "ExpenseInput": ("gastroflow.services.expenses", "ExpenseInput"),
    "ExpenseService": ("gastroflow.services.expenses", "ExpenseService"),
    "ExpenseTicketInput": ("gastroflow.services.expenses", "ExpenseTicketInput"),
    "DEFAULT_CONTEXT_CODE": ("gastroflow.services.orders", "DEFAULT_CONTEXT_CODE"),
    "CreatedOrderResult": ("gastroflow.services.orders", "CreatedOrderResult"),
    "OrderAddonInput": ("gastroflow.services.orders", "OrderAddonInput"),
    "OrderItemInput": ("gastroflow.services.orders", "OrderItemInput"),
    "OrderPaymentInput": ("gastroflow.services.orders", "OrderPaymentInput"),
    "OrderService": ("gastroflow.services.orders", "OrderService"),
    "PublicOrderInput": ("gastroflow.services.orders", "PublicOrderInput"),
    "normalize_phone": ("gastroflow.services.orders", "normalize_phone"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
