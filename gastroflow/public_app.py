from __future__ import annotations

import reflex as rx

from gastroflow.app import health_page, public_page
from gastroflow.states.app_state import BrandState, PublicOrderState


app = rx.App()
app.add_page(health_page, route="/ping")
app.add_page(public_page, route="/", on_load=[BrandState.load_brand, PublicOrderState.load_catalog])
