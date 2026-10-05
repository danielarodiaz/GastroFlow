from __future__ import annotations

import reflex as rx

from gastroflow.states.app_state import (
    AdminCrudState,
    AuthState,
    BrandState,
    CatalogAdminState,
    ExpenseState,
    OperationsState,
    PublicOrderState,
)

GOLD = "#D19C40"
CREAM = "#F0E9CF"
RED = "#A90F2B"
GREEN = "#172e1d"
INK = "#20180f"
LOGO_SRC = ""

FONT_STACK = '"Cooper Black", "Cooper BT", Georgia, serif'
SCRIPT_STACK = '"Playlist Script", "TAN St. Canard", "Cooper BT", Georgia, serif'


def page_bg(*children: rx.Component) -> rx.Component:
    return rx.box(
        *children,
        min_height="100vh",
        background=f"linear-gradient(135deg, {CREAM} 0%, #fffaf0 42%, #f8e0aa 100%)",
        color=INK,
        font_family='Inter, "Segoe UI", sans-serif',
    )


def logo_mark(size: str = "3rem") -> rx.Component:
    return rx.cond(
        BrandState.logo_url != "",
        rx.image(src=rx.get_upload_url(BrandState.logo_url), width=size, height=size, border_radius="999px", object_fit="cover"),
        rx.center(
            rx.text("GF", font_family=FONT_STACK, font_weight="900", color=CREAM),
            width=size,
            height=size,
            border_radius="999px",
            background=GREEN,
            border=f"2px solid {GOLD}",
            box_shadow="0 10px 30px rgba(23, 46, 29, 0.18)",
        ),
    )


def brand_block(compact: bool = False) -> rx.Component:
    return rx.hstack(
        logo_mark("2.6rem" if compact else "3.2rem"),
        rx.vstack(
            rx.text("Las Pizzas de Alejo", font_family=FONT_STACK, font_size="1.45rem", font_weight="900", line_height="1"),
            rx.text("Catalogo y pedidos", color=GREEN, font_size="0.78rem", font_weight="700"),
            spacing="0",
            align="start",
        ),
        spacing="3",
        align="center",
    )


def pill_button(label: str, **props: object) -> rx.Component:
    return rx.button(
        label,
        border_radius="999px",
        background=props.pop("background", GREEN),
        color=props.pop("color", CREAM),
        border=props.pop("border", "0"),
        box_shadow=props.pop("box_shadow", "0 10px 24px rgba(23, 46, 29, 0.14)"),
        font_weight="800",
        cursor="pointer",
        _hover={"transform": "translateY(-1px)", "filter": "brightness(1.05)"},
        transition="all 160ms ease",
        **props,
    )


def outline_button(label: str, **props: object) -> rx.Component:
    return pill_button(
        label,
        background="rgba(255,255,255,0.72)",
        color=GREEN,
        border=f"1px solid rgba(23, 46, 29, 0.18)",
        box_shadow="none",
        **props,
    )


def field(label: str, control: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.text(label, font_weight="800", font_size="0.86rem", color=GREEN),
        control,
        spacing="1",
        align="stretch",
        width="100%",
    )


def input_style() -> dict[str, str]:
    return {
        "background": "#fffdf5",
        "border": "1px solid rgba(23, 46, 29, 0.18)",
        "border_radius": "12px",
        "box_shadow": "none",
        "color": GREEN,
        "font_weight": "700",
    }


def select_style() -> dict[str, str]:
    return {
        **input_style(),
        "background_color": "#fffdf5",
        "width": "100%",
        "height": "2.5rem",
    }


def placeholder_style() -> dict[str, str]:
    return {"color": "#725f45", "opacity": "0.9"}


def panel(*children: rx.Component, accent: bool = False, **props: str) -> rx.Component:
    return rx.box(
        rx.vstack(*children, spacing="4", align="stretch"),
        width="100%",
        background="#fffdf5",
        border=f"1px solid {'rgba(169, 15, 43, 0.25)' if accent else 'rgba(23, 46, 29, 0.12)'}",
        border_radius="18px",
        padding="1rem",
        box_shadow="0 18px 48px rgba(23, 46, 29, 0.10)",
        **props,
    )


def public_nav() -> rx.Component:
    return rx.box(
        rx.hstack(
            brand_block(compact=True),
            rx.spacer(),
            pill_button(
                "Ver mi pedido",
                on_click=PublicOrderState.show_cart,
                background=RED,
                color="#fff8e5",
            ),
            width="100%",
            max_width="1180px",
            padding="1rem",
            align="center",
        ),
        width="100%",
        background="rgba(240, 233, 207, 0.82)",
        backdrop_filter="blur(18px)",
        border_bottom="1px solid rgba(23, 46, 29, 0.10)",
        position="sticky",
        top="0",
        z_index="10",
        display="flex",
        justify_content="center",
    )


def public_shell(*children: rx.Component) -> rx.Component:
    return page_bg(
        public_nav(),
        rx.box(
            rx.vstack(*children, spacing="5", align="stretch"),
            width="100%",
            max_width="1180px",
            margin="0 auto",
            padding="1rem",
        ),
    )


def hero() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text("Hacemos que compartir sea más rico", color=RED, font_weight="900"),
            rx.heading(
                "Elige por categoría",
                size="8",
                font_family=FONT_STACK,
                color=GREEN,
                letter_spacing="0",
            ),
            rx.text(
                "Explora el catalogo, suma productos al pedido y confirma todo desde el carrito.",
                max_width="680px",
                color="#5a4b38",
                font_size="1.05rem",
            ),
            spacing="2",
            align="start",
        ),
        padding="2rem 0 0.5rem",
    )


def category_card(category: rx.Var[dict]) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.cond(
                category["foto"] != "",
                rx.image(src=rx.get_upload_url(category["foto"]), width="100%", height="112px", object_fit="cover", border_radius="14px"),
                food_visual(category["nombre"], "112px"),
            ),
            rx.hstack(
                rx.box(width="0.75rem", height="2.4rem", border_radius="999px", background=RED),
                rx.spacer(),
                width="100%",
                align="center",
            ),
            rx.text(category["nombre"], font_family=FONT_STACK, font_size="1.4rem", color=GREEN, font_weight="900"),
            rx.cond(category["descripcion"] != "", rx.text(category["descripcion"], color="#725f45", font_size="0.92rem"), rx.fragment()),
            rx.text(category["total"], " productos", color="#725f45", font_weight="700"),
            pill_button("Ver catalogo", on_click=PublicOrderState.show_category(category["id"]), width="100%"),
            spacing="4",
            align="stretch",
        ),
        min_height="190px",
        padding="1rem",
        border_radius="18px",
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        box_shadow="0 20px 48px rgba(23, 46, 29, 0.10)",
    )


def food_visual(title: rx.Var[str] | str, height: str = "150px") -> rx.Component:
    return rx.center(
        rx.text(title, color="#fff8e5", font_family=SCRIPT_STACK, font_size="1.6rem", font_weight="900"),
        height=height,
        border_radius="14px",
        background=f"radial-gradient(circle at 30% 20%, {GOLD} 0 18%, transparent 19%), linear-gradient(135deg, {RED}, {GREEN})",
        overflow="hidden",
    )


def product_image(product: rx.Var[dict], height: str = "150px") -> rx.Component:
    return rx.cond(
        product["foto"] != "",
        rx.image(
            src=rx.get_upload_url(product["foto"]),
            width="100%",
            height=height,
            object_fit="cover",
            border_radius="14px",
        ),
        food_visual(product["nombre"], height),
    )


def product_card(product: rx.Var[dict]) -> rx.Component:
    return rx.box(
        rx.vstack(
            product_image(product),
            rx.vstack(
                rx.text(product["categoria"], color=RED, font_weight="900", font_size="0.76rem"),
                rx.text(product["nombre"], font_family=FONT_STACK, font_size="1.18rem", font_weight="900", color=GREEN),
                rx.hstack(
                    rx.text("$", product["precio"], font_weight="900", color=INK),
                    rx.spacer(),
                    outline_button("Ver", on_click=PublicOrderState.open_product(product["id"])),
                    width="100%",
                    align="center",
                ),
                spacing="2",
                align="stretch",
                width="100%",
            ),
            spacing="3",
            align="stretch",
        ),
        padding="0.7rem",
        border_radius="18px",
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        box_shadow="0 18px 42px rgba(23, 46, 29, 0.09)",
    )


def categories_view() -> rx.Component:
    return rx.vstack(
        hero(),
        rx.grid(
            rx.foreach(PublicOrderState.categories, category_card),
            columns="repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
            spacing="4",
            width="100%",
        ),
        spacing="4",
        align="stretch",
    )


def products_view() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            outline_button("Volver", on_click=PublicOrderState.show_categories),
            rx.spacer(),
            pill_button("Ver mi pedido", on_click=PublicOrderState.show_cart, background=RED),
            width="100%",
        ),
        rx.heading("Productos disponibles", size="7", font_family=FONT_STACK, color=GREEN),
        rx.grid(
            rx.foreach(PublicOrderState.visible_products, product_card),
            columns="repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
            spacing="4",
            width="100%",
        ),
        spacing="4",
        align="stretch",
    )


def detail_view() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            outline_button("Volver", on_click=PublicOrderState.show_category(PublicOrderState.selected_category_id)),
            rx.spacer(),
            pill_button("Ver mi pedido", on_click=PublicOrderState.show_cart, background=RED),
            width="100%",
        ),
        rx.grid(
            product_image(PublicOrderState.selected_product, "clamp(220px, 48vw, 360px)"),
            panel(
                rx.text(PublicOrderState.selected_product["categoria"], color=RED, font_weight="900"),
                rx.heading(
                    PublicOrderState.selected_product["nombre"],
                    size="8",
                    font_family=FONT_STACK,
                    color=GREEN,
                ),
                rx.text(PublicOrderState.selected_product["descripcion"], color="#5a4b38", font_size="1.02rem"),
                rx.text("$", PublicOrderState.selected_product["precio"], font_size="1.8rem", font_weight="900"),
                field(
                    "Cantidad",
                    rx.input(
                        value=PublicOrderState.detail_quantity,
                        on_change=PublicOrderState.set_detail_quantity,
                        type="number",
                        min="1",
                        size="3",
                        style=input_style(),
                    ),
                ),
                pill_button("Agregar al carrito", on_click=PublicOrderState.add_selected_to_cart, background=RED),
                accent=True,
            ),
            columns="repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
            spacing="5",
            width="100%",
        ),
        rx.text(PublicOrderState.message, color=GREEN, font_weight="900"),
        spacing="4",
        align="stretch",
    )


def cart_item(item: rx.Var[dict]) -> rx.Component:
    return rx.flex(
        rx.box(width="0.5rem", align_self="stretch", border_radius="999px", background=GOLD),
        rx.vstack(
            rx.text(item["nombre"], font_weight="900", color=GREEN),
            rx.text("Cantidad: ", item["cantidad"], " | Subtotal: $", item["subtotal_display"], color="#725f45"),
            rx.cond(
                item["promo_label"] != "",
                rx.text(item["promo_label"], color=RED, font_weight="900", font_size="0.88rem"),
                rx.fragment(),
            ),
            spacing="1",
            align="start",
            flex="1",
        ),
        outline_button("Quitar", on_click=PublicOrderState.remove_cart_item(item["producto_id"])),
        width="100%",
        padding="0.85rem",
        border_radius="14px",
        background="#fffaf0",
        border="1px solid rgba(23, 46, 29, 0.10)",
        align="center",
        gap="0.75rem",
        flex_wrap="wrap",
    )


def zone_option(zone: rx.Var[dict]) -> rx.Component:
    return rx.button(
        rx.hstack(
            rx.text(zone["nombre"], font_weight="900"),
            rx.spacer(),
            rx.text("$", zone["costo_display"], font_weight="900"),
            width="100%",
        ),
        on_click=PublicOrderState.select_zone(zone["id"]),
        width="100%",
        border_radius="14px",
        padding="0.85rem",
        background=rx.cond(
            PublicOrderState.zona_envio_id == zone["id_str"],
            GREEN,
            "#fffaf0",
        ),
        color=rx.cond(
            PublicOrderState.zona_envio_id == zone["id_str"],
            CREAM,
            GREEN,
        ),
        border="1px solid rgba(23, 46, 29, 0.16)",
        cursor="pointer",
    )


def delivery_button(label: str, value: str) -> rx.Component:
    return rx.button(
        label,
        on_click=PublicOrderState.set_delivery_mode(value),
        width="100%",
        border_radius="14px",
        padding="0.85rem",
        background=rx.cond(PublicOrderState.delivery_mode == value, GREEN, "#fffaf0"),
        color=rx.cond(PublicOrderState.delivery_mode == value, CREAM, GREEN),
        border="1px solid rgba(23, 46, 29, 0.16)",
        font_weight="900",
        cursor="pointer",
    )


def payment_button(label: str, value: str) -> rx.Component:
    return rx.button(
        label,
        on_click=PublicOrderState.set_forma_pago(value),
        width="100%",
        border_radius="14px",
        padding="0.85rem",
        background=rx.cond(PublicOrderState.forma_pago == value, RED, "#fffaf0"),
        color=rx.cond(PublicOrderState.forma_pago == value, "#fff8e5", GREEN),
        border="1px solid rgba(169, 15, 43, 0.18)",
        font_weight="900",
        cursor="pointer",
    )


def cart_view() -> rx.Component:
    return rx.vstack(
        rx.hstack(outline_button("Seguir comprando", on_click=PublicOrderState.show_categories), width="100%"),
        rx.grid(
            panel(
                rx.heading("Mi pedido", size="7", font_family=FONT_STACK, color=GREEN),
                rx.vstack(rx.foreach(PublicOrderState.cart, cart_item), spacing="2", align="stretch"),
                rx.hstack(
                    rx.text("Total productos", font_weight="900"),
                    rx.spacer(),
                    rx.text("$", PublicOrderState.cart_total_display, font_weight="900", font_size="1.3rem"),
                    width="100%",
                ),
                rx.hstack(
                    rx.text("Envio", font_weight="900"),
                    rx.spacer(),
                    rx.text("$", rx.cond(PublicOrderState.delivery_mode == "delivery", PublicOrderState.selected_zone_cost, "0,00"), font_weight="900"),
                    width="100%",
                ),
                rx.hstack(
                    rx.text("Total", font_weight="900", color=RED),
                    rx.spacer(),
                    rx.text("$", PublicOrderState.order_total_display, font_weight="900", font_size="1.45rem", color=RED),
                    width="100%",
                ),
            ),
            panel(
                rx.heading("Confirmar pedido", size="6", font_family=FONT_STACK, color=GREEN),
                field(
                    "Nombre y apellido",
                    rx.input(
                        value=PublicOrderState.nombre_apellido,
                        on_change=PublicOrderState.set_nombre_apellido,
                        placeholder="Tu nombre",
                        style=input_style(),
                        _placeholder=placeholder_style(),
                    ),
                ),
                field(
                    "Telefono",
                    rx.input(
                        value=PublicOrderState.telefono,
                        on_change=PublicOrderState.set_telefono,
                        placeholder="381...",
                        style=input_style(),
                        _placeholder=placeholder_style(),
                    ),
                ),
                field(
                    "Fecha de entrega",
                    rx.input(
                        value=PublicOrderState.fecha_entrega,
                        on_change=PublicOrderState.set_fecha_entrega,
                        placeholder="DD/MM/AAAA",
                        max_length=10,
                        input_mode="numeric",
                        style=input_style(),
                        _placeholder=placeholder_style(),
                    ),
                ),
                field(
                    "Horario ideal de entrega",
                    rx.input(
                        value=PublicOrderState.horario_entrega,
                        on_change=PublicOrderState.set_horario_entrega,
                        placeholder="HH:MM",
                        max_length=5,
                        input_mode="numeric",
                        style=input_style(),
                        _placeholder=placeholder_style(),
                    ),
                ),
                field(
                    "Entrega",
                    rx.grid(
                        delivery_button("Retiro del local", "retiro"),
                        delivery_button("Necesito que me lo envie", "delivery"),
                        columns="repeat(auto-fit, minmax(min(100%, 160px), 1fr))",
                        spacing="2",
                        width="100%",
                    ),
                ),
                rx.cond(
                    PublicOrderState.delivery_mode == "delivery",
                    rx.vstack(
                        field(
                            "Direccion",
                            rx.input(
                                value=PublicOrderState.direccion_delivery,
                                on_change=PublicOrderState.set_direccion_delivery,
                                placeholder="Calle, numero, localidad",
                                style=input_style(),
                                _placeholder=placeholder_style(),
                            ),
                        ),
                        field("Zona de envio", rx.vstack(rx.foreach(PublicOrderState.zones, zone_option), spacing="2", align="stretch")),
                        spacing="4",
                        align="stretch",
                    ),
                    rx.fragment(),
                ),
                field(
                    "Forma de pago",
                    rx.grid(
                        payment_button("Efectivo", "efectivo"),
                        payment_button("Transferencia", "transferencia"),
                        columns="repeat(auto-fit, minmax(min(100%, 150px), 1fr))",
                        spacing="2",
                        width="100%",
                    ),
                ),
                rx.cond(
                    PublicOrderState.forma_pago == "efectivo",
                    rx.text(
                        "En observaciones contanos con cuanto vas a pagar para que el delivery lleve cambio.",
                        color=RED,
                        font_weight="900",
                        font_size="0.9rem",
                    ),
                    rx.fragment(),
                ),
                field(
                    "Observaciones",
                    rx.text_area(
                        value=PublicOrderState.observaciones,
                        on_change=PublicOrderState.set_observaciones,
                        placeholder="Referencias, cambio para efectivo, aclaraciones del pedido...",
                        style=input_style(),
                        _placeholder=placeholder_style(),
                    ),
                ),
                pill_button("Confirmar pedido", on_click=PublicOrderState.submit_order, background=RED, width="100%"),
                rx.text(PublicOrderState.message, color=GREEN, font_weight="900"),
                accent=True,
            ),
            columns="repeat(auto-fit, minmax(min(100%, 360px), 1fr))",
            spacing="5",
            width="100%",
        ),
        spacing="4",
        align="stretch",
    )


def public_page() -> rx.Component:
    return public_shell(
        rx.cond(
            PublicOrderState.view == "products",
            products_view(),
            rx.cond(
                PublicOrderState.view == "detail",
                detail_view(),
                rx.cond(PublicOrderState.view == "cart", cart_view(), categories_view()),
            ),
        )
    )


def internal_nav() -> rx.Component:
    link_style = {
        "padding": "0.62rem 0.9rem",
        "border_radius": "999px",
        "background": "rgba(255,255,255,0.70)",
        "border": "1px solid rgba(23, 46, 29, 0.14)",
        "color": GREEN,
        "font_weight": "900",
    }
    return rx.box(
        rx.hstack(
            brand_block(compact=True),
            rx.spacer(),
            rx.link("Pedidos", href="/pedidos", style=link_style),
            rx.link("Gastos", href="/gastos", style=link_style),
            rx.link("Catalogo", href="/catalogo-admin", style=link_style),
            rx.link("Promos", href="/promociones", style=link_style),
            rx.link("Admin", href="/admin", style=link_style),
            rx.button(
                rx.hstack(rx.icon("log-out", size=16), rx.text("Salir"), spacing="2", align="center"),
                on_click=AuthState.logout,
                border_radius="999px",
                padding="0.65rem 0.95rem",
                background=RED,
                color="#fff8e5",
                border="1px solid rgba(169, 15, 43, 0.25)",
                font_weight="900",
                cursor="pointer",
            ),
            width="100%",
            max_width="1180px",
            padding="1rem",
            align="center",
            wrap="wrap",
        ),
        width="100%",
        background="rgba(240, 233, 207, 0.86)",
        backdrop_filter="blur(18px)",
        border_bottom="1px solid rgba(23, 46, 29, 0.10)",
        display="flex",
        justify_content="center",
    )


def internal_shell(*children: rx.Component) -> rx.Component:
    return page_bg(
        internal_nav(),
        rx.box(
            rx.vstack(*children, spacing="5", align="stretch"),
            width="100%",
            max_width="1180px",
            margin="0 auto",
            padding="1rem",
        ),
    )


def login_page() -> rx.Component:
    return page_bg(
        rx.center(
            rx.box(
                panel(
                    brand_block(),
                    rx.heading("Ingresar al panel", size="7", font_family=FONT_STACK, color=GREEN),
                    field("Usuario", rx.input(value=AuthState.username, on_change=AuthState.set_username, size="3", style=input_style())),
                    field(
                        "Password",
                        rx.input(
                            value=AuthState.password,
                            on_change=AuthState.set_password,
                            type="password",
                            size="3",
                            style=input_style(),
                        ),
                    ),
                    pill_button("Ingresar", on_click=AuthState.login, size="3", background=RED, width="100%"),
                    rx.text(AuthState.message, color=RED, font_weight="900"),
                ),
                width="100%",
                max_width="430px",
            ),
            min_height="100vh",
            padding="1rem",
        )
    )


def order_card(order: rx.Var[dict]) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(rx.text(order["codigo"], font_weight="900", color=GREEN), rx.spacer(), rx.text(order["estado"], color=RED, font_weight="900")),
            rx.text(order["cliente"], font_weight="800"),
            rx.text("Entrega: ", order["fecha"], color="#725f45"),
            rx.text("Total $", order["total"], font_weight="900"),
            rx.hstack(
                outline_button("En proceso", on_click=OperationsState.transition(order["id"], "en_proceso")),
                outline_button("Entregado", on_click=OperationsState.transition(order["id"], "entregado")),
                outline_button("Cancelar", on_click=OperationsState.transition(order["id"], "cancelado")),
                wrap="wrap",
            ),
            spacing="3",
            align="stretch",
        ),
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        border_radius="18px",
        padding="1rem",
        box_shadow="0 18px 42px rgba(23, 46, 29, 0.09)",
    )


def kpi_card(label: str, value: rx.Var[str] | str) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text(label, color="#725f45", font_weight="800", font_size="0.82rem"),
            rx.text(value, color=GREEN, font_weight="900", font_size="1.45rem"),
            spacing="1",
            align="start",
        ),
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        border_radius="14px",
        padding="0.9rem",
    )


def table_cell(content: rx.Component | str | rx.Var[str], weight: str = "700") -> rx.Component:
    return rx.box(
        rx.text(content, font_weight=weight, color=INK, font_size="0.86rem"),
        padding="0.65rem",
        min_width="130px",
    )


def order_table_row(order: rx.Var[dict]) -> rx.Component:
    return rx.grid(
        table_cell(order["codigo"], "900"),
        table_cell(order["fecha"]),
        table_cell(order["cliente"]),
        table_cell(order["estado"]),
        table_cell(order["forma_pago"]),
        table_cell(order["categorias"]),
        table_cell(order["items"]),
        table_cell(order["total_display"], "900"),
        columns="130px 130px 180px 150px 140px 220px 90px 120px",
        width="max-content",
        min_width="100%",
        border_bottom="1px solid rgba(23, 46, 29, 0.10)",
        align_items="center",
    )


def order_filters() -> rx.Component:
    return panel(
        rx.grid(
            field("Mes", rx.select(OperationsState.month_options, value=OperationsState.filter_month, on_change=OperationsState.set_filter_month, placeholder="Todos", style=select_style())),
            field("Desde", rx.input(value=OperationsState.filter_date_from, on_change=OperationsState.set_filter_date_from, placeholder="DD/MM/AAAA", max_length=10, style=input_style(), _placeholder=placeholder_style())),
            field("Hasta", rx.input(value=OperationsState.filter_date_to, on_change=OperationsState.set_filter_date_to, placeholder="DD/MM/AAAA", max_length=10, style=input_style(), _placeholder=placeholder_style())),
            field("Categoria", rx.select(OperationsState.category_options, value=OperationsState.filter_category, on_change=OperationsState.set_filter_category, placeholder="Todos", style=select_style())),
            field("Cliente", rx.input(value=OperationsState.filter_client, on_change=OperationsState.set_filter_client, placeholder="Cliente", style=input_style(), _placeholder=placeholder_style())),
            field("Pago", rx.select(OperationsState.payment_options, value=OperationsState.filter_payment, on_change=OperationsState.set_filter_payment, placeholder="Todos", style=select_style())),
            field("Estado", rx.select(OperationsState.state_options, value=OperationsState.filter_state, on_change=OperationsState.set_filter_state, placeholder="Todos", style=select_style())),
            columns="repeat(auto-fit, minmax(min(100%, 150px), 1fr))",
            spacing="3",
            width="100%",
        ),
        rx.hstack(
            pill_button("Aplicar filtros", on_click=OperationsState.load_orders),
            outline_button("Limpiar", on_click=OperationsState.clear_order_filters),
            pill_button("Descargar XLSX", on_click=OperationsState.export_orders_xlsx, background=GOLD, color=GREEN),
            wrap="wrap",
        ),
    )


def orders_page() -> rx.Component:
    return internal_shell(
        rx.hstack(
            rx.heading("Pedidos", size="7", font_family=FONT_STACK, color=GREEN),
            rx.spacer(),
            pill_button("Actualizar", on_click=OperationsState.load_orders),
            width="100%",
        ),
        rx.text(OperationsState.message, color=RED, font_weight="900"),
        rx.heading("Comanda activa", size="5", font_family=FONT_STACK, color=GREEN),
        rx.grid(
            rx.foreach(OperationsState.orders, order_card),
            columns="repeat(auto-fit, minmax(260px, 1fr))",
            spacing="4",
            width="100%",
        ),
        rx.cond(
            OperationsState.no_active_order_data,
            rx.text("No hay pedidos activos para mostrar.", color="#725f45", font_weight="900"),
            rx.fragment(),
        ),
        rx.heading("Todos los pedidos", size="5", font_family=FONT_STACK, color=GREEN),
        order_filters(),
        rx.grid(
            kpi_card("Pedidos", OperationsState.order_kpis["total_pedidos"]),
            kpi_card("Items", OperationsState.order_kpis["items"]),
            kpi_card("Ticket promedio", OperationsState.order_kpis["ticket_promedio"]),
            kpi_card("Facturacion", OperationsState.order_kpis["facturacion"]),
            columns="repeat(auto-fit, minmax(min(100%, 170px), 1fr))",
            spacing="3",
            width="100%",
        ),
        rx.cond(
            OperationsState.no_order_data,
            rx.text("No hay datos para el filtro elegido", color=RED, font_weight="900"),
            rx.fragment(),
        ),
        rx.box(
            rx.vstack(
                rx.grid(
                    table_cell("Codigo", "900"),
                    table_cell("Fecha", "900"),
                    table_cell("Cliente", "900"),
                    table_cell("Estado", "900"),
                    table_cell("Pago", "900"),
                    table_cell("Categorias", "900"),
                    table_cell("Items", "900"),
                    table_cell("Total", "900"),
                    columns="130px 130px 180px 150px 140px 220px 90px 120px",
                    width="max-content",
                    min_width="100%",
                    background="#fff4d9",
                    border_radius="12px 12px 0 0",
                ),
                rx.foreach(OperationsState.order_rows, order_table_row),
                spacing="0",
                align="stretch",
                width="100%",
            ),
            overflow_x="auto",
            background="#fffdf5",
            border="1px solid rgba(23, 46, 29, 0.12)",
            border_radius="14px",
        ),
    )


def expense_card(expense: rx.Var[dict]) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text(expense["codigo"], font_weight="900", color=GREEN),
            rx.text(expense["fecha"], color="#725f45"),
            rx.text(expense["motivo"], " · ", expense["marca"], color=RED, font_weight="900"),
            rx.text(expense["cantidad_display"], " ", expense["unidad"]),
            rx.text("$", expense["precio_display"], font_weight="900"),
            rx.text(expense["lugar"], color="#725f45"),
            spacing="2",
            align="stretch",
        ),
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        border_radius="18px",
        padding="1rem",
    )


def expense_table_row(expense: rx.Var[dict]) -> rx.Component:
    return rx.grid(
        table_cell(expense["codigo"], "900"),
        table_cell(expense["fecha"]),
        table_cell(expense["motivo"]),
        table_cell(expense["marca"]),
        table_cell(expense["cantidad_display"]),
        table_cell(expense["unidad"]),
        table_cell(expense["precio_display"], "900"),
        table_cell(expense["lugar"]),
        rx.hstack(
            outline_button("Editar", on_click=ExpenseState.open_edit_expense(expense["id"])),
            pill_button("Borrar", on_click=ExpenseState.request_delete_expense(expense["id"]), background=RED),
            spacing="2",
        ),
        columns="130px 130px 180px 180px 110px 100px 120px 220px 180px",
        width="max-content",
        min_width="100%",
        border_bottom="1px solid rgba(23, 46, 29, 0.10)",
        align_items="center",
    )


def expense_form_modal() -> rx.Component:
    return rx.cond(
        ExpenseState.show_form,
        rx.box(
            rx.center(
                rx.box(
                    panel(
                        rx.hstack(
                            rx.heading(
                                rx.cond(ExpenseState.editing_expense_id != "", "Modificar gasto", "Agregar gasto"),
                                size="5",
                                font_family=FONT_STACK,
                                color=GREEN,
                            ),
                            rx.spacer(),
                            outline_button("Cerrar", on_click=ExpenseState.close_form),
                            width="100%",
                        ),
                        field("Fecha", rx.input(value=ExpenseState.fecha, on_change=ExpenseState.set_fecha, placeholder="DD/MM/AAAA", max_length=10, style=input_style(), _placeholder=placeholder_style())),
                        field("Motivo", rx.input(value=ExpenseState.motivo_nombre, on_change=ExpenseState.set_motivo_nombre, placeholder="Ej: ACEITE GIRA-SOL", style=input_style(), _placeholder=placeholder_style())),
                        field("Marca", rx.input(value=ExpenseState.marca_nombre, on_change=ExpenseState.set_marca_nombre, placeholder="Ej: AVICOLA CRUZ PAPAL", style=input_style(), _placeholder=placeholder_style())),
                        rx.grid(
                            field("Cantidad", rx.input(value=ExpenseState.cantidad, on_change=ExpenseState.set_cantidad, placeholder="4,5 o 4.5", style=input_style(), _placeholder=placeholder_style())),
                            field("Unidad", rx.input(value=ExpenseState.unidad_medida, on_change=ExpenseState.set_unidad_medida, placeholder="LITROS", style=input_style(), _placeholder=placeholder_style())),
                            field("Precio", rx.input(value=ExpenseState.precio, on_change=ExpenseState.set_precio, placeholder="$8.500", style=input_style(), _placeholder=placeholder_style())),
                            columns="repeat(auto-fit, minmax(min(100%, 130px), 1fr))",
                            spacing="3",
                            width="100%",
                        ),
                        field("Lugar", rx.input(value=ExpenseState.lugar_texto, on_change=ExpenseState.set_lugar_texto, placeholder="Lugar de compra", style=input_style(), _placeholder=placeholder_style())),
                        rx.cond(
                            ExpenseState.pending_save,
                            rx.vstack(
                                rx.text("Estas seguro que quieres guardar este gasto?", color=RED, font_weight="900"),
                                rx.hstack(
                                    pill_button("Confirmar", on_click=ExpenseState.submit_expense, background=RED),
                                    outline_button("Cancelar", on_click=ExpenseState.cancel_save_expense),
                                ),
                                spacing="2",
                                align="stretch",
                            ),
                            pill_button("Guardar", on_click=ExpenseState.request_save_expense, background=RED, width="100%"),
                        ),
                    ),
                    width="min(94vw, 560px)",
                ),
                min_height="100vh",
                padding="1rem",
            ),
            position="fixed",
            inset="0",
            background="rgba(32, 24, 15, 0.42)",
            z_index="50",
        ),
        rx.fragment(),
    )


def expense_delete_confirm() -> rx.Component:
    return rx.cond(
        ExpenseState.pending_delete_id != "",
        rx.box(
            rx.center(
                rx.box(
                    panel(
                        rx.heading("Eliminar gasto", size="5", font_family=FONT_STACK, color=GREEN),
                        rx.text("Estas seguro que quieres eliminar este gasto?", color="#725f45", font_weight="800"),
                        rx.hstack(
                            pill_button("Eliminar", on_click=ExpenseState.delete_expense, background=RED),
                            outline_button("Cancelar", on_click=ExpenseState.cancel_delete_expense),
                        ),
                    ),
                    width="min(94vw, 420px)",
                ),
                min_height="100vh",
                padding="1rem",
            ),
            position="fixed",
            inset="0",
            background="rgba(32, 24, 15, 0.42)",
            z_index="60",
        ),
        rx.fragment(),
    )


def expense_filters() -> rx.Component:
    return panel(
        rx.grid(
            field("Mes", rx.select(ExpenseState.month_options, value=ExpenseState.filter_month, on_change=ExpenseState.set_filter_month, placeholder="Todos", style=select_style())),
            field("Desde", rx.input(value=ExpenseState.filter_date_from, on_change=ExpenseState.set_filter_date_from, placeholder="DD/MM/AAAA", max_length=10, style=input_style(), _placeholder=placeholder_style())),
            field("Hasta", rx.input(value=ExpenseState.filter_date_to, on_change=ExpenseState.set_filter_date_to, placeholder="DD/MM/AAAA", max_length=10, style=input_style(), _placeholder=placeholder_style())),
            field("Motivo", rx.input(value=ExpenseState.filter_motivo, on_change=ExpenseState.set_filter_motivo, placeholder="Motivo", style=input_style(), _placeholder=placeholder_style())),
            field("Marca", rx.input(value=ExpenseState.filter_marca, on_change=ExpenseState.set_filter_marca, placeholder="Marca", style=input_style(), _placeholder=placeholder_style())),
            field("Lugar", rx.input(value=ExpenseState.filter_lugar, on_change=ExpenseState.set_filter_lugar, placeholder="Lugar", style=input_style(), _placeholder=placeholder_style())),
            columns="repeat(auto-fit, minmax(min(100%, 150px), 1fr))",
            spacing="3",
            width="100%",
        ),
        rx.hstack(
            pill_button("Aplicar filtros", on_click=ExpenseState.load_expenses),
            outline_button("Limpiar", on_click=ExpenseState.clear_expense_filters),
            pill_button("Descargar XLSX", on_click=ExpenseState.export_expenses_xlsx, background=GOLD, color=GREEN),
            wrap="wrap",
        ),
    )


def expenses_page() -> rx.Component:
    return internal_shell(
        expense_form_modal(),
        expense_delete_confirm(),
        rx.hstack(
            rx.heading("Gastos", size="7", font_family=FONT_STACK, color=GREEN),
            rx.spacer(),
            pill_button("Agregar gasto", on_click=ExpenseState.open_new_expense, background=RED),
            outline_button("Actualizar", on_click=ExpenseState.load_expenses),
            width="100%",
        ),
        rx.text(ExpenseState.message, color=GREEN, font_weight="900"),
        rx.heading("Analisis de gastos", size="5", font_family=FONT_STACK, color=GREEN),
        expense_filters(),
        rx.grid(
            kpi_card("Gastos", ExpenseState.expense_kpis["total_gastos"]),
            kpi_card("Monto total", ExpenseState.expense_kpis["monto_total"]),
            kpi_card("Ticket promedio", ExpenseState.expense_kpis["ticket_promedio"]),
            columns="repeat(auto-fit, minmax(min(100%, 170px), 1fr))",
            spacing="3",
            width="100%",
        ),
        rx.cond(
            ExpenseState.no_expense_data,
            rx.text("No hay datos para el filtro elegido", color=RED, font_weight="900"),
            rx.fragment(),
        ),
        rx.box(
            rx.vstack(
                rx.grid(
                    table_cell("Codigo", "900"),
                    table_cell("Fecha", "900"),
                    table_cell("Motivo", "900"),
                    table_cell("Marca", "900"),
                    table_cell("Cantidad", "900"),
                    table_cell("Unidad", "900"),
                    table_cell("Precio", "900"),
                    table_cell("Lugar", "900"),
                    table_cell("Acciones", "900"),
                    columns="130px 130px 180px 180px 110px 100px 120px 220px 180px",
                    width="max-content",
                    min_width="100%",
                    background="#fff4d9",
                    border_radius="12px 12px 0 0",
                ),
                rx.foreach(ExpenseState.expense_rows, expense_table_row),
                spacing="0",
                align="stretch",
                width="100%",
            ),
            overflow_x="auto",
            background="#fffdf5",
            border="1px solid rgba(23, 46, 29, 0.12)",
            border_radius="14px",
        ),
    )


def table_button(table_name: rx.Var[str]) -> rx.Component:
    return outline_button(table_name, on_click=AdminCrudState.set_table(table_name))


def record_card(record: rx.Var[dict]) -> rx.Component:
    return rx.box(
        rx.text(record["display"]),
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        border_radius="14px",
        padding="0.85rem",
        overflow_x="auto",
        font_family="monospace",
        font_size="0.85rem",
    )


def admin_category_card(category: rx.Var[dict]) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.cond(
                category["foto"] != "",
                rx.image(src=rx.get_upload_url(category["foto"]), width="100%", height="110px", object_fit="cover", border_radius="12px"),
                food_visual(category["nombre"], "110px"),
            ),
            rx.hstack(
                rx.text(category["nombre"], font_weight="900", color=GREEN),
                rx.spacer(),
                rx.text(category["codigo"], color=RED, font_weight="900", font_size="0.75rem"),
                width="100%",
            ),
            rx.text(category["total"], " productos", color="#725f45", font_weight="700"),
            outline_button("Editar", on_click=CatalogAdminState.select_category(category["id"]), width="100%"),
            spacing="3",
            align="stretch",
        ),
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        border_radius="14px",
        padding="0.7rem",
    )


def admin_product_card(product: rx.Var[dict]) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.cond(
                product["foto"] != "",
                rx.image(src=rx.get_upload_url(product["foto"]), width="100%", height="120px", object_fit="cover", border_radius="12px"),
                food_visual(product["nombre"], "120px"),
            ),
            rx.hstack(
                rx.text(product["nombre"], font_weight="900", color=GREEN),
                rx.spacer(),
                rx.text("$", product["precio_display"], font_weight="900", color=RED),
                width="100%",
            ),
            rx.text(product["descripcion"], color="#725f45", font_size="0.88rem"),
            rx.hstack(
                rx.text(rx.cond(product["visible"], "Visible", "Oculto"), font_weight="900", color=rx.cond(product["visible"], GREEN, RED)),
                rx.spacer(),
                rx.text(rx.cond(product["destacado"], "Destacado", ""), color=GOLD, font_weight="900"),
                width="100%",
            ),
            rx.hstack(
                outline_button("Editar", on_click=CatalogAdminState.select_product_category(product["id"])),
                pill_button("Quitar", on_click=CatalogAdminState.request_delete_product_category(product["id"]), background=RED),
                width="100%",
            ),
            spacing="3",
            align="stretch",
        ),
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        border_radius="14px",
        padding="0.7rem",
    )


def upload_box(upload_id: str, label: str, on_click: rx.event.EventSpec) -> rx.Component:
    return rx.vstack(
        rx.upload(
            rx.vstack(
                rx.text(label, font_weight="900", color=GREEN),
                rx.text("Elegir archivo desde la compu", color="#725f45", font_size="0.85rem"),
                rx.foreach(rx.selected_files(upload_id), lambda file: rx.text(file, color=RED, font_weight="900", font_size="0.82rem")),
                spacing="1",
                align="center",
            ),
            id=upload_id,
            border="1px dashed rgba(23, 46, 29, 0.35)",
            border_radius="14px",
            padding="1rem",
            width="100%",
        ),
        pill_button("Subir imagen", on_click=on_click, background=GOLD, color=GREEN, width="100%"),
        spacing="2",
        align="stretch",
    )


def promo_card(promo: rx.Var[dict]) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text(promo["nombre"], font_weight="900", color=GREEN),
                rx.spacer(),
                rx.text(rx.cond(promo["activa"], "Activa", "Inactiva"), color=rx.cond(promo["activa"], GREEN, RED), font_weight="900"),
                width="100%",
            ),
            rx.text(promo["codigo"], color="#725f45", font_weight="800", font_size="0.82rem"),
            rx.text("Minimo: ", promo["cantidad_minima"], " | Precio: $", promo["precio_display"], color=INK, font_weight="800"),
            rx.text("Productos: ", promo["productos"], color="#725f45", font_size="0.86rem"),
            rx.hstack(
                outline_button("Editar", on_click=CatalogAdminState.select_promo(promo["id"])),
                pill_button("Borrar", on_click=CatalogAdminState.request_delete_promo(promo["id"]), background=RED),
            ),
            spacing="2",
            align="stretch",
        ),
        background="#fffdf5",
        border="1px solid rgba(23, 46, 29, 0.12)",
        border_radius="14px",
        padding="0.85rem",
    )


def catalog_confirmations() -> rx.Component:
    return rx.fragment(
        rx.cond(
            CatalogAdminState.pending_delete_product_category_id != "",
            rx.box(
                rx.center(
                    rx.box(
                        panel(
                            rx.heading("Eliminar producto de categoria", size="5", font_family=FONT_STACK, color=GREEN),
                            rx.text("Estas seguro que quieres eliminar esta relacion?", color="#725f45", font_weight="800"),
                            rx.hstack(
                                pill_button("Eliminar", on_click=CatalogAdminState.delete_product_category, background=RED),
                                outline_button("Cancelar", on_click=CatalogAdminState.cancel_delete_product_category),
                            ),
                        ),
                        width="min(94vw, 450px)",
                    ),
                    min_height="100vh",
                    padding="1rem",
                ),
                position="fixed",
                inset="0",
                background="rgba(32, 24, 15, 0.42)",
                z_index="70",
            ),
            rx.fragment(),
        ),
        rx.cond(
            CatalogAdminState.pending_delete_promo_id != "",
            rx.box(
                rx.center(
                    rx.box(
                        panel(
                            rx.heading("Eliminar promocion", size="5", font_family=FONT_STACK, color=GREEN),
                            rx.text("Estas seguro que quieres eliminar esta promocion?", color="#725f45", font_weight="800"),
                            rx.hstack(
                                pill_button("Eliminar", on_click=CatalogAdminState.delete_promo, background=RED),
                                outline_button("Cancelar", on_click=CatalogAdminState.cancel_delete_promo),
                            ),
                        ),
                        width="min(94vw, 450px)",
                    ),
                    min_height="100vh",
                    padding="1rem",
                ),
                position="fixed",
                inset="0",
                background="rgba(32, 24, 15, 0.42)",
                z_index="70",
            ),
            rx.fragment(),
        ),
    )


def catalog_admin_page() -> rx.Component:
    return internal_shell(
        catalog_confirmations(),
        rx.hstack(
            rx.heading("Catalogo visual", size="7", font_family=FONT_STACK, color=GREEN),
            rx.spacer(),
            pill_button("Actualizar", on_click=CatalogAdminState.load_catalog_admin),
            width="100%",
        ),
        rx.text(CatalogAdminState.message, color=RED, font_weight="900"),
        panel(
            rx.heading("Logo", size="5", font_family=FONT_STACK, color=GREEN),
            rx.hstack(
                rx.cond(
                    CatalogAdminState.logo_url != "",
                    rx.image(src=rx.get_upload_url(CatalogAdminState.logo_url), width="72px", height="72px", object_fit="cover", border_radius="999px"),
                    logo_mark("72px"),
                ),
                rx.vstack(
                    upload_box(
                        "logo_upload",
                        "Logo del negocio",
                        CatalogAdminState.upload_logo(rx.upload_files(upload_id="logo_upload")),
                    ),
                    outline_button("Eliminar logo", on_click=CatalogAdminState.delete_logo),
                    spacing="2",
                    align="stretch",
                    flex="1",
                ),
                width="100%",
                align="center",
            ),
        ),
        rx.grid(
            panel(
                rx.heading("Categorias", size="5", font_family=FONT_STACK, color=GREEN),
                rx.grid(
                    rx.foreach(CatalogAdminState.categories, admin_category_card),
                    columns="repeat(auto-fit, minmax(min(100%, 190px), 1fr))",
                    spacing="3",
                    width="100%",
                ),
            ),
            panel(
                rx.heading("Editar categoria", size="5", font_family=FONT_STACK, color=GREEN),
                field("Nombre", rx.input(value=CatalogAdminState.category_nombre, on_change=CatalogAdminState.set_category_nombre, style=input_style())),
                field("Descripcion publica", rx.text_area(value=CatalogAdminState.category_descripcion, on_change=CatalogAdminState.set_category_descripcion, style=input_style())),
                field("Orden", rx.input(value=CatalogAdminState.category_orden, on_change=CatalogAdminState.set_category_orden, type="number", style=input_style())),
                rx.text("Orden define en que posicion aparece la categoria. Menor numero aparece primero.", color="#725f45", font_size="0.85rem", font_weight="700"),
                rx.checkbox("Visible para cliente", checked=CatalogAdminState.category_visible, on_change=CatalogAdminState.set_category_visible),
                rx.cond(
                    CatalogAdminState.pending_save_category,
                    rx.vstack(
                        rx.text("Estas seguro que quieres modificar esta categoria?", color=RED, font_weight="900"),
                        rx.hstack(
                            pill_button("Confirmar", on_click=CatalogAdminState.save_category, background=RED),
                            outline_button("Cancelar", on_click=CatalogAdminState.cancel_save_category),
                        ),
                        spacing="2",
                        align="stretch",
                    ),
                    rx.hstack(
                        pill_button("Guardar categoria", on_click=CatalogAdminState.request_save_category, background=RED),
                        outline_button("Ver productos", on_click=rx.scroll_to("productos-categoria")),
                        wrap="wrap",
                    ),
                ),
                upload_box(
                    "category_upload",
                    "Foto de categoria",
                    CatalogAdminState.upload_category_photo(rx.upload_files(upload_id="category_upload")),
                ),
                outline_button("Eliminar foto de categoria", on_click=CatalogAdminState.delete_category_photo),
            ),
            columns="minmax(0, 1.3fr) minmax(280px, 0.7fr)",
            spacing="5",
            width="100%",
        ),
        rx.grid(
            panel(
                rx.heading("Productos de la categoria", size="5", font_family=FONT_STACK, color=GREEN),
                rx.text("Selecciona una categoria arriba para ver y agregar productos.", color="#725f45", font_weight="700"),
                rx.grid(
                    rx.foreach(CatalogAdminState.products, admin_product_card),
                    columns="repeat(auto-fit, minmax(min(100%, 210px), 1fr))",
                    spacing="3",
                    width="100%",
                ),
                id="productos-categoria",
            ),
            panel(
                rx.heading("Editar producto en categoria", size="5", font_family=FONT_STACK, color=GREEN),
                field("Producto disponible para agregar", rx.select(CatalogAdminState.available_products, value=CatalogAdminState.selected_available_product_id, on_change=CatalogAdminState.set_selected_available_product_id, placeholder="Elegir producto", style=select_style())),
                field("Precio", rx.input(value=CatalogAdminState.product_price, on_change=CatalogAdminState.set_product_price, style=input_style())),
                field("Descripcion contextual", rx.text_area(value=CatalogAdminState.product_description, on_change=CatalogAdminState.set_product_description, style=input_style())),
                field("Orden", rx.input(value=CatalogAdminState.product_order, on_change=CatalogAdminState.set_product_order, type="number", style=input_style())),
                rx.text("Orden define en que posicion aparece el producto dentro de esta categoria. Menor numero aparece primero.", color="#725f45", font_size="0.85rem", font_weight="700"),
                rx.checkbox("Visible", checked=CatalogAdminState.product_visible, on_change=CatalogAdminState.set_product_visible),
                rx.checkbox("Destacado", checked=CatalogAdminState.product_featured, on_change=CatalogAdminState.set_product_featured),
                rx.cond(
                    CatalogAdminState.pending_save_product,
                    rx.vstack(
                        rx.text("Estas seguro que quieres modificar este producto?", color=RED, font_weight="900"),
                        rx.hstack(
                            pill_button("Confirmar", on_click=CatalogAdminState.save_product_category, background=RED),
                            outline_button("Cancelar", on_click=CatalogAdminState.cancel_save_product_category),
                        ),
                        spacing="2",
                        align="stretch",
                    ),
                    rx.hstack(
                        pill_button("Agregar a categoria", on_click=CatalogAdminState.add_product_to_category, background=GOLD, color=GREEN),
                        pill_button("Guardar producto", on_click=CatalogAdminState.request_save_product_category, background=RED),
                        wrap="wrap",
                    ),
                ),
                upload_box(
                    "product_upload",
                    "Foto del producto en esta categoria",
                    CatalogAdminState.upload_product_photo(rx.upload_files(upload_id="product_upload")),
                ),
                outline_button("Eliminar foto del producto", on_click=CatalogAdminState.delete_product_photo),
            ),
            columns="minmax(0, 1.3fr) minmax(280px, 0.7fr)",
            spacing="5",
            width="100%",
        ),
    )


def promo_selected_product_row(product: rx.Var[dict]) -> rx.Component:
    return rx.hstack(
        rx.text(product["nombre"], font_weight="900", color=GREEN),
        rx.spacer(),
        outline_button("Quitar", on_click=CatalogAdminState.remove_promo_product(product["id"])),
        width="100%",
        padding="0.55rem 0.7rem",
        background="#fffaf0",
        border="1px solid rgba(23, 46, 29, 0.10)",
        border_radius="12px",
    )


def promotions_page() -> rx.Component:
    return internal_shell(
        catalog_confirmations(),
        rx.hstack(
            rx.heading("Promociones", size="7", font_family=FONT_STACK, color=GREEN),
            rx.spacer(),
            outline_button("Nueva promo", on_click=CatalogAdminState.new_promo),
            pill_button("Actualizar", on_click=CatalogAdminState.load_catalog_admin),
            width="100%",
            wrap="wrap",
        ),
        rx.text(CatalogAdminState.message, color=RED, font_weight="900"),
        rx.grid(
            panel(
                rx.heading("Promos cargadas", size="5", font_family=FONT_STACK, color=GREEN),
                rx.vstack(rx.foreach(CatalogAdminState.promotions, promo_card), spacing="2", align="stretch"),
            ),
            panel(
                rx.heading("Editar promo", size="5", font_family=FONT_STACK, color=GREEN),
                field("Codigo", rx.input(value=CatalogAdminState.promo_codigo, on_change=CatalogAdminState.set_promo_codigo, placeholder="PROMO-MUZZA", style=input_style(), _placeholder=placeholder_style())),
                field("Nombre", rx.input(value=CatalogAdminState.promo_nombre, on_change=CatalogAdminState.set_promo_nombre, placeholder="2 MUZZAS", style=input_style(), _placeholder=placeholder_style())),
                field("Cantidad minima", rx.input(value=CatalogAdminState.promo_cantidad_minima, on_change=CatalogAdminState.set_promo_cantidad_minima, type="number", style=input_style())),
                field("Precio unitario promocional", rx.input(value=CatalogAdminState.promo_precio, on_change=CatalogAdminState.set_promo_precio, placeholder="$8.500", style=input_style(), _placeholder=placeholder_style())),
                field(
                    "Producto elegible",
                    rx.hstack(
                        rx.select(CatalogAdminState.promo_product_options, value=CatalogAdminState.promo_selected_product, on_change=CatalogAdminState.set_promo_selected_product, placeholder="Elegir producto", style=select_style()),
                        pill_button("Agregar", on_click=CatalogAdminState.add_selected_promo_product, background=GOLD, color=GREEN),
                        width="100%",
                        align="end",
                    ),
                ),
                rx.vstack(rx.foreach(CatalogAdminState.promo_selected_products, promo_selected_product_row), spacing="2", align="stretch"),
                rx.checkbox("Activa", checked=CatalogAdminState.promo_activa, on_change=CatalogAdminState.set_promo_activa),
                pill_button("Guardar promo", on_click=CatalogAdminState.save_promo, background=RED),
            ),
            columns="minmax(0, 1.2fr) minmax(280px, 0.8fr)",
            spacing="5",
            width="100%",
        ),
    )


def admin_page() -> rx.Component:
    return internal_shell(
        rx.heading("Admin", size="7", font_family=FONT_STACK, color=GREEN),
        panel(
            rx.text("Tabla", font_weight="900", color=GREEN),
            rx.hstack(rx.foreach(AdminCrudState.tables, table_button), wrap="wrap"),
            field(
                "JSON de alta/edicion",
                rx.text_area(
                    value=AdminCrudState.payload_json,
                    on_change=AdminCrudState.set_payload_json,
                    min_height="160px",
                    style=input_style(),
                ),
            ),
            field("ID para editar/borrar", rx.input(value=AdminCrudState.selected_id, on_change=AdminCrudState.set_selected_id, style=input_style())),
            rx.hstack(
                pill_button("Listar", on_click=AdminCrudState.load_records),
                pill_button("Crear", on_click=AdminCrudState.create_record, background=GOLD, color=GREEN),
                outline_button("Actualizar", on_click=AdminCrudState.update_record),
                pill_button("Borrar", on_click=AdminCrudState.delete_record, background=RED),
                wrap="wrap",
            ),
            rx.text("Tabla actual: ", AdminCrudState.table_name, font_weight="900"),
            rx.text(AdminCrudState.message, color=RED, font_weight="900"),
        ),
        rx.vstack(rx.foreach(AdminCrudState.records, record_card), spacing="2", align="stretch", width="100%"),
    )


app = rx.App()
app.add_page(public_page, route="/", on_load=PublicOrderState.load_catalog)
app.add_page(login_page, route="/login")
app.add_page(orders_page, route="/pedidos", on_load=OperationsState.load_orders)
app.add_page(expenses_page, route="/gastos", on_load=ExpenseState.load_expenses)
app.add_page(catalog_admin_page, route="/catalogo-admin", on_load=CatalogAdminState.load_catalog_admin)
app.add_page(promotions_page, route="/promociones", on_load=CatalogAdminState.load_catalog_admin)
app.add_page(admin_page, route="/admin")
