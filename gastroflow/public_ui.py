from __future__ import annotations

import reflex as rx
from gastroflow.components.delivery_input import delivery_date_input, delivery_time_input

from gastroflow.states.public_order_state import BrandState, PublicOrderState

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
        rx.image(src=BrandState.logo_url, width=size, height=size, border_radius="999px", object_fit="cover"),
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
        type=props.pop("type", "button"),
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


def input_style() -> dict[str, object]:
    return {
        "background": "#fffdf5",
        "border": "1px solid rgba(23, 46, 29, 0.18)",
        "border_radius": "12px",
        "box_shadow": "none",
        "color": GREEN,
        "font_weight": "700",
        "& input::placeholder": {"color": "#514332", "opacity": "1"},
        "& textarea::placeholder": {"color": "#514332", "opacity": "1"},
        "&::placeholder": {"color": "#514332", "opacity": "1"},
    }


def select_style() -> dict[str, str]:
    return {
        **input_style(),
        "background_color": "#fffdf5",
        "width": "100%",
        "height": "2.5rem",
    }


def placeholder_style() -> dict[str, str]:
    return {"color": "#514332", "opacity": "1"}


def delivery_input_style() -> dict[str, object]:
    return {
        **input_style(),
        "width": "100%",
        "height": "2.5rem",
        "padding": "0.5rem 0.75rem",
        "font_family": "inherit",
        "font_size": "var(--font-size-2, 14px)",
        "line_height": "var(--line-height-2, 20px)",
        "&::placeholder": {
            **placeholder_style(),
            "font_family": "inherit",
            "font_size": "inherit",
            "font_weight": "inherit",
        },
    }


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
                rx.image(src=category["foto"], width="100%", height="112px", object_fit="cover", border_radius="14px", loading="lazy", decoding="async"),
                food_visual(category["nombre"], "112px"),
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
            src=product["foto"],
            loading="lazy",
            decoding="async",
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
                rx.cond(product.get("es_especial", False), rx.text("Pedido especial · Sujeto a disponibilidad", color=RED, font_weight="900", font_size="0.8rem"), rx.fragment()),
                rx.text(product["nombre"], font_family=FONT_STACK, font_size="1.18rem", font_weight="900", color=GREEN),
                rx.hstack(
                    rx.text("$", product["precio"], font_weight="900", color=INK),
                    rx.spacer(),
                    outline_button("Ver", on_click=PublicOrderState.open_product(product["id"], product["categoria_id"])),
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
        rx.heading(rx.cond(PublicOrderState.special_catalog, "Pedido especial", "Productos disponibles"), size="7", font_family=FONT_STACK, color=GREEN),
        rx.cond(
            PublicOrderState.special_catalog,
            rx.vstack(
                rx.text("Se prepara únicamente por encargo y está sujeto a aceptación de disponibilidad del local.", color=RED, font_weight="700"),
                outline_button("Volver al catálogo habitual", on_click=PublicOrderState.show_category(PublicOrderState.selected_category_id)),
                align="stretch", width="100%",
            ),
            rx.cond(PublicOrderState.has_special_catalog,
                outline_button("Consultar pedido especial", on_click=PublicOrderState.show_special_category(PublicOrderState.selected_category_id)),
                rx.fragment()),
        ),
        rx.grid(
            rx.foreach(PublicOrderState.visible_products, product_card),
            columns="repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
            spacing="4",
            width="100%",
        ),
        spacing="4",
        align="stretch",
    )


def combo_option(option: rx.Var[dict]) -> rx.Component:
    return rx.select.item(option["nombre"], value=option["id_str"])


def addon_option(addon: rx.Var[dict]) -> rx.Component:
    return rx.hstack(
        rx.checkbox(
            checked=addon["cantidad"].to(int) > 0,
            on_change=PublicOrderState.set_selected_addon(addon["id"]),
            size="3",
            color_scheme="green",
        ),
        rx.vstack(
            rx.text(addon["nombre"], font_weight="900", color=GREEN),
            rx.text("$", addon["precio_display"], color="#725f45", font_size="0.88rem"),
            spacing="0",
            align="start",
        ),
        width="100%",
        align="center",
        padding="0.55rem",
        border="1px solid rgba(23, 46, 29, 0.12)",
        border_radius="12px",
    )


def detail_view() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.cond(PublicOrderState.special_catalog,
                outline_button("Volver", on_click=PublicOrderState.show_special_category(PublicOrderState.selected_category_id)),
                outline_button("Volver", on_click=PublicOrderState.show_category(PublicOrderState.selected_category_id))),
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
                rx.cond(PublicOrderState.detail_is_special,
                    rx.text("Pedido especial · Sujeto a aceptación de disponibilidad del local.", color=RED, font_weight="900", role="status"),
                    rx.fragment()),
                rx.cond(PublicOrderState.has_special_catalog & ~PublicOrderState.special_catalog,
                    outline_button("Consultar sabores para pedido especial", on_click=PublicOrderState.show_special_category(PublicOrderState.selected_category_id)), rx.fragment()),
                rx.cond(
                    PublicOrderState.combo_options.length() > 0,
                    rx.vstack(
                        field("¿Cómo la querés?", rx.radio(
                            ["Un solo sabor", "Mitad y mitad"],
                            value=PublicOrderState.pizza_mode, on_change=PublicOrderState.set_pizza_mode,
                        )),
                        rx.cond(
                            PublicOrderState.pizza_mode == "Mitad y mitad",
                            rx.vstack(
                                field("Elegí la otra mitad", rx.select.root(
                                    rx.select.trigger(placeholder="Seleccioná un sabor", width="100%"),
                                    rx.select.content(rx.foreach(PublicOrderState.combo_options, combo_option)),
                                    value=PublicOrderState.selected_combo_id, on_change=PublicOrderState.select_combo,
                                )),
                                rx.cond(
                                    PublicOrderState.selected_combo_id != "",
                                    rx.text("Mitad ", PublicOrderState.selected_product["nombre"], " / mitad ", PublicOrderState.selected_combo_name,
                                        color=GREEN, font_weight="900"),
                                    rx.fragment(),
                                ),
                                rx.text("El precio es el promedio de ambos sabores. Cada unidad es una pizza completa.", color="#5a4b38", font_size="0.9rem"),
                                align="stretch", spacing="2", width="100%",
                            ),
                            rx.fragment(),
                        ),
                        align="stretch", spacing="3", width="100%",
                    ),
                    rx.fragment(),
                ),
                rx.text("$", PublicOrderState.detail_price_display, font_size="1.8rem", font_weight="900"),
                field(
                    "Cantidad",
                    rx.hstack(
                        outline_button(
                            "−",
                            on_click=PublicOrderState.decrement_detail_quantity,
                            aria_label="Disminuir cantidad",
                        ),
                        rx.text(
                            PublicOrderState.detail_quantity,
                            min_width="3rem",
                            text_align="center",
                            font_size="1.15rem",
                            font_weight="900",
                            color=GREEN,
                        ),
                        outline_button(
                            "+",
                            on_click=PublicOrderState.increment_detail_quantity,
                            aria_label="Aumentar cantidad",
                        ),
                        align="center",
                        spacing="2",
                    ),
                ),
                rx.cond(
                    PublicOrderState.available_addons.length() > 0,
                    field(
                        "Agregados",
                        rx.vstack(
                            rx.foreach(PublicOrderState.available_addons, addon_option),
                            spacing="2",
                            align="stretch",
                            width="100%",
                        ),
                    ),
                    rx.fragment(),
                ),
                pill_button("Agregar al carrito", on_click=PublicOrderState.add_selected_to_cart, background=RED, loading=PublicOrderState.is_updating_cart,
                    disabled=PublicOrderState.is_submitting | (PublicOrderState.registered_order_code != "")
                    | ((PublicOrderState.pizza_mode == "Mitad y mitad") & (PublicOrderState.selected_combo_id == ""))),
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
            rx.text(item["categoria_display"], color=RED, font_size="0.88rem"),
            rx.cond(item.get("es_especial", False), rx.text("Pedido especial · Disponibilidad pendiente de aceptación", color=RED, font_weight="900", font_size="0.88rem"), rx.fragment()),
            rx.text("Cantidad: ", item["cantidad"], " | Subtotal: $", item["subtotal_display"], color="#725f45"),
            rx.cond(
                item.get("agregados_display", "") != "",
                rx.text("Agregados: ", item.get("agregados_display", ""), color=GREEN, font_size="0.88rem"),
                rx.fragment(),
            ),
            rx.cond(
                item["promo_label"] != "",
                rx.text(item["promo_label"], color=RED, font_weight="900", font_size="0.88rem"),
                rx.fragment(),
            ),
            spacing="1",
            align="start",
            flex="1",
        ),
        outline_button("Quitar", on_click=PublicOrderState.remove_cart_item(
            item["producto_id"], item["categoria_codigo"],
            item.get("producto_combo_id", 0), item.get("addon_key", ""),
        ), disabled=PublicOrderState.is_updating_cart | PublicOrderState.is_submitting | (PublicOrderState.registered_order_code != "")),
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
        type="button",
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
        type="button",
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
        type="button",
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
            rx.cond(
                PublicOrderState.registered_order_code != "",
                panel(
                    rx.heading(rx.cond(PublicOrderState.registered_order_is_special, "Solicitud especial registrada", "Pedido registrado"), size="6", color=GREEN),
                    rx.text(PublicOrderState.message, font_weight="900", role="status"),
                    rx.text("Pedido: ", PublicOrderState.registered_order_code),
                    rx.text("Si WhatsApp no se abrió, presioná Enviar por WhatsApp. Tu pedido ya está guardado; este botón no lo vuelve a registrar."),
                    rx.link(
                        "Enviar por WhatsApp", href=PublicOrderState.whatsapp_url,
                        color=GREEN, font_weight="900", padding="1rem",
                        border=f"2px solid {GREEN}", border_radius="12px",
                    ),
                    outline_button("Hacer otro pedido", on_click=PublicOrderState.start_new_order),
                    accent=True,
                ),
                rx.form(
                    panel(
                        rx.heading("Confirmar pedido", size="6", font_family=FONT_STACK, color=GREEN),
                        rx.cond(PublicOrderState.cart_has_special_orders,
                            rx.text("Tu pedido incluye productos por encargo. El pedido completo queda pendiente de aceptación de disponibilidad. Esperá la aceptación antes de pagar.", color=RED, font_weight="900", role="status"),
                            rx.fragment()),
                        field(
                            "Nombre y apellido",
                            rx.input(
                                value=PublicOrderState.nombre_apellido,
                                name="nombre_apellido",
                                on_change=PublicOrderState.set_nombre_apellido,
                                placeholder="Tu nombre",
                                style=input_style(),
                                _placeholder=placeholder_style(),
                            ),
                        ),
                        field(
                            "Celular",
                            rx.input(
                                value=PublicOrderState.telefono,
                                name="telefono",
                                on_change=PublicOrderState.set_telefono,
                                placeholder="3813543860",
                                input_mode="tel",
                                style=input_style(),
                                _placeholder=placeholder_style(),
                            ),
                        ),
                        rx.text(
                            "Ingresá 10 dígitos. También podés usar +54 9 o 0 delante del código de área.",
                            color="#514332", font_size="0.78rem",
                        ),
                        field(
                            "Fecha de entrega",
                            delivery_date_input(
                                default_value=PublicOrderState.fecha_entrega,
                                name="fecha_entrega",
                                on_blur=PublicOrderState.complete_delivery_date,
                                placeholder="DD-MM (año opcional)",
                                max_length=10,
                                input_mode="numeric",
                                style=delivery_input_style(),
                            ),
                        ),
                        field(
                            "Horario ideal de entrega",
                            delivery_time_input(
                                default_value=PublicOrderState.horario_entrega,
                                name="horario_entrega",
                                on_blur=PublicOrderState.complete_delivery_time,
                                placeholder="21 o 21:30",
                                max_length=5,
                                input_mode="numeric",
                                style=delivery_input_style(),
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
                                        name="direccion_delivery",
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
                                payment_button("Pago dividido", "mixto"),
                                columns="repeat(auto-fit, minmax(min(100%, 150px), 1fr))",
                                spacing="2",
                                width="100%",
                            ),
                        ),
                        rx.cond(
                            PublicOrderState.forma_pago == "mixto",
                            rx.grid(
                                field(
                                    "Monto en efectivo",
                                    rx.input(
                                        value=PublicOrderState.pago_efectivo,
                                        name="pago_efectivo",
                                        on_change=PublicOrderState.set_pago_efectivo,
                                        placeholder="0,00",
                                        input_mode="decimal",
                                        style=input_style(),
                                    ),
                                ),
                                field(
                                    "Monto por transferencia",
                                    rx.input(
                                        value=PublicOrderState.pago_transferencia,
                                        name="pago_transferencia",
                                        on_change=PublicOrderState.set_pago_transferencia,
                                        placeholder="0,00",
                                        input_mode="decimal",
                                        style=input_style(),
                                    ),
                                ),
                                columns="repeat(auto-fit, minmax(min(100%, 160px), 1fr))",
                                spacing="2",
                                width="100%",
                            ),
                            rx.fragment(),
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
                                name="observaciones",
                                on_change=PublicOrderState.set_observaciones,
                                placeholder="Referencias, cambio para efectivo, aclaraciones del pedido...",
                                style=input_style(),
                                _placeholder=placeholder_style(),
                            ),
                        ),
                        rx.cond(
                            PublicOrderState.events_minimum_message != "",
                            rx.text(PublicOrderState.events_minimum_message, color=RED, font_weight="900", role="alert"),
                            rx.fragment(),
                        ),
                        rx.cond(
                            PublicOrderState.is_submitting,
                            rx.hstack(rx.spinner(), rx.text("Registrando tu pedido..."), role="status", align="center"),
                            pill_button(rx.cond(PublicOrderState.cart_has_special_orders, "Enviar solicitud especial", "Confirmar pedido"), type="submit", background=RED, width="100%", disabled=PublicOrderState.is_updating_cart | (PublicOrderState.events_minimum_message != "")),
                        ),
                        rx.cond(
                            ~PublicOrderState.is_submitting,
                            rx.text(PublicOrderState.message, color=GREEN, font_weight="900", role="status"),
                            rx.fragment(),
                        ),
                        accent=True,
                    ),
                    on_submit=PublicOrderState.submit_order,
                    reset_on_submit=False,
                    width="100%",
                ),
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
            PublicOrderState.is_loading_catalog,
            rx.center(rx.hstack(rx.spinner(), rx.text("Cargando catálogo..."), align="center", role="status"), min_height="180px"),
            rx.cond(
                PublicOrderState.catalog_error != "",
                panel(
                    rx.text(PublicOrderState.catalog_error, role="alert"),
                    pill_button("Reintentar", on_click=PublicOrderState.load_catalog),
                ),
                rx.cond(
                    PublicOrderState.view == "products",
                    products_view(),
                    rx.cond(
                        PublicOrderState.view == "detail",
                        detail_view(),
                        rx.cond(PublicOrderState.view == "cart", cart_view(), categories_view()),
                    ),
                ),
            ),
        )
    )


def health_page() -> rx.Component:
    return rx.text("ok")
