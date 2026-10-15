from __future__ import annotations

import reflex as rx

from gastroflow.public_ui import health_page, public_page
from gastroflow.states.public_order_state import PublicOrderState


app = rx.App()
app.add_page(health_page, route="/ping")
app.add_page(public_page, route="/", on_load=PublicOrderState.load_catalog)
