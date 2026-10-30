from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import mimetypes
import re
import time as time_module
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import streamlit as st
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.config.settings import get_settings
from gastroflow.domain.enums import EstadoPedido, FormaPago, RolUsuario, TipoPromocion, UnidadVenta
from gastroflow.domain.errors import DomainError, ValidationError
from gastroflow.domain.order_state import valid_next_states
from gastroflow.models import (
    AgregadoCategoria,
    AppConfig,
    Categoria,
    Cliente,
    Gasto,
    GastoDetalle,
    GastoDocumento,
    Marca,
    MotivoGasto,
    Pedido,
    PedidoItem,
    PedidoItemAgregado,
    PedidoPago,
    PedidoRevision,
    Producto,
    ProductoCategoria,
    Promocion,
    PromocionCategoria,
    PromocionItem,
    PromocionProducto,
    Usuario,
    UsuarioRead,
    ZonaEnvio,
)
from gastroflow.services import (
    AdminCrudService,
    AuthService,
    CRUD_TABLES,
    ExpenseDetailInput,
    ExpenseService,
    ExpenseTicketInput,
    OrderService,
    normalize_phone,
)
from gastroflow.services.media_storage import save_media_bytes
from gastroflow.services.expense_documents import ExpenseDocumentDraft, HybridExpenseDocumentReader
from gastroflow.services.promotions import configure_promotion

BRAND_LOGO_CONFIG_KEY = "brand.logo_url"
ACTIVE_ORDER_STATES = {
    EstadoPedido.PEDIDO.value,
    EstadoPedido.PENDIENTE_CONFIRMACION.value,
    EstadoPedido.EN_PROCESO.value,
}
AUTH_QUERY_PARAM = "session"
AUTH_SESSION_SECONDS = 60 * 60 * 12
ORDER_REFRESH_INTERVAL = "5s"


def main() -> None:
    st.set_page_config(
        page_title="GastroFlow Gestion",
        page_icon="GF",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_session_state()
    _restore_authentication()
    _render_sidebar()
    if not _is_authenticated():
        _render_login()
        return

    page = st.session_state.get("internal_page", "Pedidos")
    if page == "Pedidos":
        _render_orders()
    elif page == "Gastos":
        _render_expenses()
    elif page == "Catalogo":
        _render_catalog()
    elif page == "Promos":
        _render_promotions()
    elif page == "Admin":
        _render_admin()


def _init_session_state() -> None:
    defaults = {
        "user_id": 0,
        "username": "",
        "role": "",
        "internal_page": "Pedidos",
        "auth_message": "",
        "selected_order_id": None,
        "order_success_message": "",
        "last_modified_order": None,
        "show_delivered_orders": False,
        "selected_expense_id": None,
        "expense_ticket_items": [],
        "expense_capture_draft": None,
        "expense_capture_file": None,
        "expense_capture_items": [],
        "expense_edit_id": None,
        "expense_delete_id": None,
        "expense_action_message": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _render_sidebar() -> None:
    with st.sidebar:
        st.title("GastroFlow")
        if _is_authenticated():
            st.caption(f"{st.session_state.username} | {st.session_state.role}")
            pages = ["Pedidos", "Gastos", "Catalogo", "Promos", "Admin"]
            st.radio(
                "Seccion",
                pages,
                key="internal_page",
                label_visibility="collapsed",
            )
            if st.button("Cerrar sesion", use_container_width=True):
                _logout()
                st.rerun()
        else:
            st.caption("Gestion interna")


def _render_login() -> None:
    st.title("Ingreso interno")
    st.caption("Acceso para gestion de pedidos, gastos, catalogo y administracion.")
    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Ingresar", use_container_width=True)
    if submitted:
        try:
            with Session(engine) as session:
                user = AuthService(session).authenticate(username, password)
            st.session_state.user_id = user.id
            st.session_state.username = user.username
            st.session_state.role = user.rol.value
            st.session_state.auth_message = ""
            _persist_authentication(user.id)
            st.rerun()
        except DomainError as exc:
            st.session_state.auth_message = str(exc)
    if st.session_state.auth_message:
        st.error(st.session_state.auth_message)


def _render_orders() -> None:
    st.title("Pedidos")
    if success_message := st.session_state.pop("order_success_message", ""):
        st.toast(success_message, icon="✅")
    _render_modified_order_notice()
    if st.session_state.show_delivered_orders:
        if st.button("← Volver a pedidos activos"):
            st.session_state.show_delivered_orders = False
            st.rerun()
        _render_delivered_orders()
        return

    action_cols = st.columns([1, 3])
    if action_cols[0].button("Ver mis pedidos", use_container_width=True):
        st.session_state.show_delivered_orders = True
        st.rerun()
    action_cols[1].caption("La pantalla se actualiza automáticamente cada 5 segundos.")
    _render_live_orders()


@st.fragment(run_every=ORDER_REFRESH_INTERVAL)
def _render_live_orders() -> None:
    orders = [row for row in _load_order_rows() if row["estado"] in ACTIVE_ORDER_STATES]
    orders = _prioritize_pending_special_orders(orders)
    metric_cols = st.columns(4)
    total_amount = sum((row["monto_total"] for row in orders), Decimal("0.00"))
    metric_cols[0].metric("Pedidos", len(orders))
    metric_cols[1].metric("Total", _money_text(total_amount))
    metric_cols[2].metric("Pendientes", sum(1 for row in orders if row["estado"] in {EstadoPedido.PEDIDO.value, EstadoPedido.PENDIENTE_CONFIRMACION.value}))
    metric_cols[3].metric(
        "En proceso",
        sum(1 for row in orders if row["estado"] == EstadoPedido.EN_PROCESO.value),
    )

    _render_production_summary(orders)

    if not orders:
        st.info("No hay pedidos activos en este momento.")
        return

    for row in orders:
        with st.container(border=True):
            cols = st.columns([1.1, 1.4, 1.2, 1.2, 1.1, 1])
            cols[0].markdown(f"**{row['codigo']}**")
            cols[1].write(row["cliente"])
            cols[2].write(f"{row['fecha_entrega']} · {row['horario_entrega']}")
            cols[3].markdown(_state_badge(row["estado"]), unsafe_allow_html=True)
            cols[4].write(_money_text(row["monto_total"]))
            special_pending = row["estado"] == EstadoPedido.PENDIENTE_CONFIRMACION.value
            if special_pending:
                st.info("Pedido modificado o especial — Pendiente de confirmación")
            elif row.get("es_especial", False):
                st.info("Pedido especial")
            if cols[5].button("Ver detalles", key=f"order_detail_{row['id']}", use_container_width=True):
                st.session_state.selected_order_id = row["id"]
                _show_order_detail(row)

            if _is_admin() and st.button(
                "Modificar pedido",
                key=f"edit_active_order_{row['id']}",
                use_container_width=True,
            ):
                _show_order_edit_dialog(row["id"])

            next_states = valid_next_states(EstadoPedido(row["estado"]))
            if special_pending:
                next_states = {EstadoPedido.PEDIDO, EstadoPedido.CANCELADO}
            if next_states:
                action_cols = st.columns(len(next_states))
                for index, next_state in enumerate(sorted(next_states, key=lambda item: item.value)):
                    if action_cols[index].button(
                        ("Aceptar disponibilidad" if next_state == EstadoPedido.PEDIDO else "Rechazar solicitud") if special_pending else _transition_label(next_state),
                        key=f"order_{row['id']}_{next_state.value}",
                        type="primary" if next_state != EstadoPedido.CANCELADO else "secondary",
                        use_container_width=True,
                    ):
                        _transition_order(row["id"], next_state)
                        _load_order_rows.clear()
                        st.rerun(scope="fragment")


def _prioritize_pending_special_orders(
    orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Promote orders awaiting confirmation while preserving the existing order."""
    return sorted(
        orders,
        key=lambda row: row["estado"] != EstadoPedido.PENDIENTE_CONFIRMACION.value,
    )


def _render_modified_order_notice() -> None:
    notice = st.session_state.get("last_modified_order")
    if not notice:
        return
    with st.container(border=True):
        st.success(f"Pedido {notice['codigo']} modificado")
        columns = st.columns([2, 1])
        if notice.get("whatsapp_url"):
            columns[0].link_button(
                "Enviar pedido actualizado por WhatsApp",
                notice["whatsapp_url"],
                use_container_width=True,
            )
        else:
            columns[0].caption("El cliente no tiene un teléfono cargado para enviar el resumen.")
        if columns[1].button(
            "Cerrar aviso",
            key=f"dismiss_modified_order_{notice['codigo']}",
            use_container_width=True,
        ):
            st.session_state.last_modified_order = None
            st.rerun()


def _render_delivered_orders() -> None:
    st.subheader("Mis pedidos entregados")
    _render_order_admin_editor()
    delivered = [
        row for row in _load_order_rows()
        if row["estado"] == EstadoPedido.ENTREGADO.value
    ]
    delivered.sort(
        key=lambda row: (
            row["fecha_entrega_raw"],
            row["horario_entrega_raw"] or time.min,
            row["id"],
        ),
        reverse=True,
    )
    if not delivered:
        st.info("Todavía no hay pedidos entregados.")
        return

    month_options = _month_filter_options(delivered)
    filter_cols = st.columns(3)
    selected_months = filter_cols[0].multiselect(
        "Mes",
        [value for value in month_options if value != "Todos"],
        format_func=lambda value: month_options[value],
        placeholder="Todos los meses",
    )
    selected_dates = filter_cols[1].date_input(
        "Rango de fecha (desde / hasta)",
        value=(),
        format="DD/MM/YYYY",
    )
    categories = sorted({item["categoria"] for row in delivered for item in row["items"]})
    products = sorted({
        product
        for row in delivered
        for item in row["items"]
        for product in (item["producto"], item["combo"])
        if product
    })
    clients = sorted({row["cliente"] for row in delivered})
    zones = sorted({row["zona"] for row in delivered})
    selected_categories = filter_cols[2].multiselect(
        "Categoría", categories, placeholder="Todas las categorías"
    )
    filter_cols_2 = st.columns(3)
    selected_products = filter_cols_2[0].multiselect(
        "Producto", products, placeholder="Todos los productos"
    )
    selected_clients = filter_cols_2[1].multiselect(
        "Cliente", clients, placeholder="Todos los clientes"
    )
    selected_zones = filter_cols_2[2].multiselect(
        "Zona", zones, placeholder="Todas las zonas"
    )

    date_from, date_to = _normalize_date_range(selected_dates)
    filtered = _filter_delivered_orders(
        delivered,
        month=selected_months,
        date_from=date_from,
        date_to=date_to,
        category=selected_categories,
        product=selected_products,
        client=selected_clients,
        zone=selected_zones,
    )
    visible_item_count = sum(len(order["items"]) for order in filtered)
    st.caption(f"{len(filtered)} pedidos · {visible_item_count} ítems encontrados")
    if not filtered:
        st.warning("No hay pedidos que coincidan con los filtros seleccionados.")
        return
    metric_cols = st.columns(3)
    metric_cols[0].metric(
        "Total",
        _money_text(sum((order["monto_total"] for order in filtered), Decimal("0.00"))),
    )
    metric_cols[1].metric(
        "Cantidad de pizzas",
        sum(
            int(item.get("cantidad", 0))
            for order in filtered
            for item in order["items"]
            if _is_pizza_item(item)
        ),
    )
    metric_cols[2].metric("Cantidad de pedidos", len(filtered))
    st.dataframe(
        _delivered_order_table_rows(filtered),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Total": st.column_config.NumberColumn(format="$ %.2f"),
            "Envío": st.column_config.NumberColumn(format="$ %.2f"),
            "Precio unitario": st.column_config.NumberColumn(format="$ %.2f"),
            "Subtotal": st.column_config.NumberColumn(format="$ %.2f"),
        },
    )


def _month_filter_options(orders: list[dict[str, Any]]) -> dict[str, str]:
    month_names = (
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    )
    months = sorted(
        {row["fecha_entrega_raw"].strftime("%Y-%m") for row in orders},
        reverse=True,
    )
    options = {"Todos": "Todos"}
    for value in months:
        year, month = (int(part) for part in value.split("-"))
        options[value] = f"{month_names[month - 1]} {year}"
    return options


def _normalize_date_range(value: Any) -> tuple[date | None, date | None]:
    if isinstance(value, date):
        return value, value
    if isinstance(value, (tuple, list)):
        if len(value) == 1:
            return value[0], value[0]
        if len(value) >= 2:
            return value[0], value[1]
    return None, None


def _filter_delivered_orders(
    orders: list[dict[str, Any]],
    *,
    month: str | list[str] = "Todos",
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | list[str] = "Todos",
    product: str | list[str] = "Todos",
    client: str | list[str] = "Todos",
    zone: str | list[str] = "Todos",
) -> list[dict[str, Any]]:
    selected_months = _filter_values(month)
    selected_categories = _filter_values(category)
    selected_products = _filter_values(product)
    selected_clients = _filter_values(client)
    selected_zones = _filter_values(zone)
    filtered: list[dict[str, Any]] = []
    for order in orders:
        delivery_date = order["fecha_entrega_raw"]
        if order["estado"] != EstadoPedido.ENTREGADO.value:
            continue
        if selected_months and delivery_date.strftime("%Y-%m") not in selected_months:
            continue
        if date_from is not None and delivery_date < date_from:
            continue
        if date_to is not None and delivery_date > date_to:
            continue
        if selected_clients and order["cliente"] not in selected_clients:
            continue
        if selected_zones and order["zona"] not in selected_zones:
            continue
        matching_items = [
            item
            for item in order["items"]
            if (not selected_categories or item["categoria"] in selected_categories)
            and (
                not selected_products
                or item["producto"] in selected_products
                or item["combo"] in selected_products
            )
        ]
        if not matching_items:
            continue
        filtered.append({**order, "items": matching_items})
    return filtered


def _filter_values(value: str | list[str]) -> set[str]:
    if isinstance(value, str):
        return set() if value == "Todos" else {value}
    return {item for item in value if item and item != "Todos"}


def _is_pizza_item(item: dict[str, Any]) -> bool:
    return str(item.get("categoria", "")).casefold() not in {"pre pizzas", "pan árabe"}


def _delivered_order_table_rows(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order in orders:
        items = order["items"] or [{}]
        for item in items:
            rows.append({
                "Código": order["codigo"],
                "Fecha": order["fecha_entrega"],
                "Hora": order["horario_entrega"],
                "Cliente": order["cliente"],
                "Teléfono": order["telefono"],
                "Categoría": item.get("categoria", ""),
                "Producto": item.get("producto", ""),
                "Combinación": item.get("combo", ""),
                "Cantidad": item.get("cantidad", ""),
                "Precio unitario": item.get("precio_unitario_raw"),
                "Subtotal": item.get("subtotal_raw"),
                "Agregados": item.get("agregados_texto", ""),
                "Dirección": order["direccion"],
                "Zona": order["zona"],
                "Envío": order["costo_envio"],
                "Forma de pago": order["pagos_texto"],
                "Total": order["monto_total"],
                "Observaciones": order["observaciones"],
                "Pedido especial": "Sí" if item.get("pedido_especial") else "No",
                "Estado": "Entregado",
                "Creado": _format_display_value(order["creado"]),
            })
    return rows


def _render_production_summary(orders: list[dict[str, Any]]) -> None:
    summary = _build_production_summary(orders)
    st.subheader("Produccion pendiente por fecha de entrega")
    st.caption("Incluye pedidos aceptados y en proceso. No cuenta solicitudes pendientes de aceptación, pedidos entregados ni cancelados.")
    if not summary:
        st.info("No hay productos pendientes de preparacion.")
        return
    for delivery_date, data in summary.items():
        with st.container(border=True):
            st.markdown(f"### {delivery_date} · {data['order_count']} pedidos")
            if not data["categories"]:
                st.caption("El pedido no tiene items cargados.")
                continue
            category_columns = st.columns(min(len(data["categories"]), 3))
            for index, (category, products) in enumerate(data["categories"].items()):
                with category_columns[index % len(category_columns)]:
                    st.markdown(f"**{category}**")
                    for product, quantity in products.items():
                        st.write(f"{quantity} × {product}")


def _render_expenses() -> None:
    st.title("Gastos")
    action_message = st.session_state.pop("expense_action_message", "")
    if action_message:
        st.success(action_message)
    expenses = _load_expense_rows()
    items = _load_expense_item_rows()
    total_amount = sum((row["subtotal"] for row in items), Decimal("0.00"))
    metric_cols = st.columns(3)
    metric_cols[0].metric("Ítems", len(items))
    metric_cols[1].metric("Monto total", _money_text(total_amount))
    metric_cols[2].metric(
        "Comprobantes", len(expenses),
    )
    item_tab, ticket_tab, capture_tab = st.tabs(["Ítems", "Comprobantes", "Capturar documento"])
    with item_tab:
        _render_expense_item_browser(items)
    with ticket_tab:
        with st.expander("Carga manual", expanded=False):
            _render_expense_form()
        _render_expense_ticket_browser(expenses)
    with capture_tab:
        _render_expense_capture()


def _filter_expense_items(
    rows: list[dict[str, Any]],
    *,
    query: str = "",
    places: list[str] | None = None,
    motives: list[str] | None = None,
    brands: list[str] | None = None,
) -> list[dict[str, Any]]:
    search = " ".join(query.casefold().split())
    return [
        row for row in rows
        if (not search or search in " ".join(str(row.get(key, "")) for key in (
            "codigo", "fecha", "motivo", "marca", "descripcion", "lugar",
            "destinatario_pago", "identificador_pago",
        )).casefold())
        and (not places or row["lugar"] in places)
        and (not motives or row["motivo"] in motives)
        and (not brands or row["marca"] in brands)
    ]


def _render_expense_item_browser(items: list[dict[str, Any]]) -> None:
    query = st.text_input(
        "Buscar",
        placeholder="Producto, marca, comercio, destinatario, código u operación",
        key="expense_item_search",
    )
    filter_cols = st.columns(3)
    places = filter_cols[0].multiselect(
        "Lugar", sorted({row["lugar"] for row in items if row["lugar"]})
    )
    motives = filter_cols[1].multiselect(
        "Motivo", sorted({row["motivo"] for row in items if row["motivo"]})
    )
    brands = filter_cols[2].multiselect(
        "Marca", sorted({row["marca"] for row in items if row["marca"]})
    )
    filtered = _filter_expense_items(
        items, query=query, places=places, motives=motives, brands=brands
    )
    st.caption(
        f"{len(filtered)} ítems · Total filtrado: "
        f"{_money_text(sum((row['subtotal'] for row in filtered), Decimal('0.00')))}"
    )
    st.dataframe(
        [{
            "Fecha": row["fecha"],
            "Motivo": row["motivo"],
            "Marca": row["marca"] or "-",
            "Cantidad": f"{row['cantidad']} {row['unidad']}",
            "Lugar": row["lugar"],
            "Importe": _money_text(row["subtotal"]),
            "Comprobante": row["codigo"],
        } for row in filtered],
        hide_index=True,
        use_container_width=True,
    )
    ticket_options = {f"{row['codigo']} · {row['fecha']} · {row['lugar']}": row["gasto_id"] for row in filtered}
    selected = st.selectbox("Abrir comprobante", [""] + list(ticket_options), key="expense_item_ticket")
    if selected and st.button("Ver detalle", key="expense_item_open"):
        _show_expense_detail(ticket_options[selected])


def _render_expense_ticket_browser(expenses: list[dict[str, Any]]) -> None:
    search = st.text_input("Buscar comprobante", key="expense_ticket_search").casefold().strip()
    visible = [row for row in expenses if not search or search in " ".join(str(value) for value in row.values()).casefold()]
    st.dataframe(
        [{
            "Código": row["codigo"], "Fecha": row["fecha"], "Lugar": row["lugar"],
            "Medio de pago": row["medio_pago"] or "-",
            "Destinatario": row["destinatario_pago"] or "-",
            "Total": _money_text(row["monto_total"]),
        } for row in visible],
        hide_index=True,
        use_container_width=True,
    )
    options = {f"{row['codigo']} · {row['fecha']} · {row['lugar']}": row["id"] for row in visible}
    selected = st.selectbox("Seleccionar comprobante", [""] + list(options), key="expense_ticket_open")
    selected_id = options.get(selected) if selected else None
    action_cols = st.columns([1, 1, 1, 3])
    if action_cols[0].button("Ver", disabled=selected_id is None, key="expense_ticket_open_button"):
        _show_expense_detail(int(selected_id))
    if action_cols[1].button("Modificar", disabled=selected_id is None, key="expense_ticket_edit_button"):
        st.session_state.expense_edit_id = int(selected_id)
        st.session_state.expense_delete_id = None
        st.rerun()
    if action_cols[2].button("Eliminar", disabled=selected_id is None, key="expense_ticket_delete_button"):
        st.session_state.expense_delete_id = int(selected_id)
        st.session_state.expense_edit_id = None
        st.rerun()

    if st.session_state.expense_edit_id:
        _render_expense_editor(int(st.session_state.expense_edit_id))
    if st.session_state.expense_delete_id:
        _render_expense_delete_confirmation(int(st.session_state.expense_delete_id))


def _load_expense_for_edit(expense_id: int) -> tuple[Gasto, list[dict[str, Any]]] | None:
    with Session(engine) as session:
        gasto = session.get(Gasto, expense_id)
        if gasto is None:
            return None
        details = session.exec(
            select(GastoDetalle).where(GastoDetalle.gasto_id == expense_id).order_by(GastoDetalle.id)
        ).all()
        motives = {item.id: item.nombre for item in session.exec(select(MotivoGasto)).all()}
        brands = {item.id: item.nombre for item in session.exec(select(Marca)).all()}
        session.expunge(gasto)
    return gasto, [
        {
            "Motivo": motives.get(detail.motivo_gasto_id, ""),
            "Marca": brands.get(detail.marca_id, "") if detail.marca_id else "",
            "Descripción": detail.descripcion or "",
            "Cantidad": float(detail.cantidad),
            "Unidad": detail.unidad_medida,
            "Subtotal": float(detail.subtotal),
        }
        for detail in details
    ]


def _render_expense_editor(expense_id: int) -> None:
    loaded = _load_expense_for_edit(expense_id)
    if loaded is None:
        st.error("El gasto seleccionado ya no existe.")
        st.session_state.expense_edit_id = None
        return
    gasto, item_rows = loaded
    with st.expander(f"Modificar {gasto.codigo}", expanded=True):
        with st.form(f"expense_edit_form_{expense_id}"):
            header_cols = st.columns([1, 2])
            expense_date = header_cols[0].date_input("Fecha", value=gasto.fecha, format="DD-MM-YYYY")
            place = header_cols[1].text_input("Lugar", value=gasto.lugar_texto)
            payment_options = ["", "EFECTIVO", "TRANSFERENCIA", "TARJETA", "OTRO"]
            current_payment = gasto.medio_pago or ""
            if current_payment and current_payment not in payment_options:
                payment_options.append(current_payment)
            payment_cols = st.columns(3)
            payment_method = payment_cols[0].selectbox(
                "Medio de pago",
                payment_options,
                index=payment_options.index(current_payment) if current_payment in payment_options else 0,
            )
            payment_recipient = payment_cols[1].text_input(
                "Destinatario", value=gasto.destinatario_pago or ""
            )
            payment_id = payment_cols[2].text_input(
                "ID de operación", value=gasto.identificador_pago or ""
            )
            observations = st.text_input("Observaciones", value=gasto.observaciones or "")
            edited_items = st.data_editor(
                item_rows,
                num_rows="dynamic",
                hide_index=True,
                use_container_width=True,
                key=f"expense_edit_items_{expense_id}",
                column_config={
                    "Cantidad": st.column_config.NumberColumn(min_value=0.001, step=0.001),
                    "Subtotal": st.column_config.NumberColumn(min_value=0.0, step=100.0, format="$ %.2f"),
                },
            )
            save = st.form_submit_button("Guardar cambios", type="primary")
            cancel = st.form_submit_button("Cancelar")
        if cancel:
            st.session_state.expense_edit_id = None
            st.rerun()
        if save:
            try:
                details = _expense_details_from_editor(edited_items)
                with Session(engine) as session:
                    updated = ExpenseService(session).update_expense_ticket(
                        expense_id,
                        ExpenseTicketInput(
                            fecha=expense_date,
                            lugar_texto=place,
                            items=details,
                            observaciones=observations or None,
                            medio_pago=payment_method or None,
                            destinatario_pago=payment_recipient or None,
                            identificador_pago=payment_id or None,
                        ),
                        _current_user(),
                    )
                st.session_state.expense_edit_id = None
                _load_expense_rows.clear()
                _load_expense_item_rows.clear()
                st.session_state.expense_action_message = f"Gasto {updated.codigo} modificado."
                st.rerun()
            except Exception as exc:
                _render_action_error("No se pudo modificar el gasto.", exc)


def _render_expense_delete_confirmation(expense_id: int) -> None:
    expense = next((row for row in _load_expense_rows() if row["id"] == expense_id), None)
    if expense is None:
        st.session_state.expense_delete_id = None
        return
    with st.container(border=True):
        st.warning(
            f"Vas a eliminar {expense['codigo']} de {expense['lugar']} por "
            f"{_money_text(expense['monto_total'])}. Esta acción no se puede deshacer."
        )
        cols = st.columns([1, 1, 3])
        if cols[0].button("Confirmar eliminación", type="primary", key=f"confirm_delete_{expense_id}"):
            try:
                with Session(engine) as session:
                    code = ExpenseService(session).delete_expense_ticket(expense_id, _current_user())
                st.session_state.expense_delete_id = None
                _load_expense_rows.clear()
                _load_expense_item_rows.clear()
                st.session_state.expense_action_message = f"Gasto {code} eliminado."
                st.rerun()
            except Exception as exc:
                _render_action_error("No se pudo eliminar el gasto.", exc)
        if cols[1].button("Cancelar", key=f"cancel_delete_{expense_id}"):
            st.session_state.expense_delete_id = None
            st.rerun()


def _render_catalog() -> None:
    st.title("Catalogo")
    categories, product_rows, products = _load_catalog_rows()
    if _is_admin():
        _render_brand_media_editor()
    category_tab, product_tab = st.tabs(["Categorias", "Productos por categoria"])

    with category_tab:
        st.dataframe(
            [
                {
                    "id": category.id,
                    "codigo": category.codigo,
                    "nombre": category.nombre,
                    "visible": category.visible_cliente,
                    "activa": category.activa,
                    "orden": category.orden,
                }
                for category in categories
            ],
            hide_index=True,
            use_container_width=True,
        )
        if not _is_admin():
            st.info("Solo Admin puede modificar el catalogo.")
        else:
            _render_category_editor(categories)

    with product_tab:
        st.dataframe(product_rows, hide_index=True, use_container_width=True)
        if not _is_admin():
            st.info("Solo Admin puede modificar productos.")
        else:
            _render_add_product_to_category(categories, products)
            _render_product_category_editor(product_rows)


def _render_promotions() -> None:
    st.title("Promos")
    if st.session_state.pop("promotion_saved", False):
        st.success("Promo guardada.")
    promos, promo_rows, products = _load_promotion_rows()
    st.dataframe(promo_rows, hide_index=True, use_container_width=True)
    if not _is_admin():
        st.info("Solo Admin puede modificar promociones.")
        return
    _render_promotion_editor(promos, products)


def _render_admin() -> None:
    st.title("Admin")
    if not _is_admin():
        st.info("Solo Admin puede acceder a esta seccion.")
        return

    table_name = st.selectbox("Tabla", list(CRUD_TABLES.keys()), key="admin_table_name")
    records = _load_admin_records(table_name)
    st.caption(f"{len(records)} registros")
    st.dataframe(records, hide_index=True, use_container_width=True)

    action = st.radio("Accion", ["Crear", "Actualizar", "Borrar"], horizontal=True)
    if action in {"Actualizar", "Borrar"}:
        record_id = st.number_input("ID", min_value=1, step=1, key="admin_record_id")
    else:
        record_id = None

    if action in {"Crear", "Actualizar"}:
        st.caption("Usa JSON con nombres de campos del modelo. Para `usuario`, usa `password` al crear o cambiar clave.")
        payload_json = st.text_area("Payload JSON", value="{}", height=180, key="admin_payload_json")
        if st.button(f"{action} registro", use_container_width=True):
            try:
                payload = json.loads(payload_json)
                if not isinstance(payload, dict):
                    raise ValueError("El payload debe ser un objeto JSON.")
                with Session(engine) as session:
                    service = AdminCrudService(session)
                    if action == "Crear":
                        result = service.create_record(table_name, payload, _current_user())
                    else:
                        result = service.update_record(table_name, int(record_id or 0), payload, _current_user())
                st.success(f"Guardado: {result}")
            except Exception as exc:
                _render_action_error("No se pudo guardar el registro.", exc)
    else:
        st.warning("Borrar registros puede afectar relaciones. Usar solo para correcciones controladas.")
        if st.button("Borrar registro", use_container_width=True):
            try:
                with Session(engine) as session:
                    AdminCrudService(session).delete_record(table_name, int(record_id or 0), _current_user())
                st.success("Registro borrado.")
            except Exception as exc:
                _render_action_error("No se pudo borrar el registro.", exc)


@st.fragment
def _render_brand_media_editor() -> None:
    with st.expander("Marca e imagenes", expanded=False):
        logo_url = _read_app_config(BRAND_LOGO_CONFIG_KEY)
        if logo_url:
            st.image(logo_url, caption="Logo actual", width=120)
        uploaded = st.file_uploader("Logo del negocio", type=["png", "jpg", "jpeg", "webp"], key="brand_logo_upload")
        cols = st.columns([1, 1, 2])
        if cols[0].button("Subir logo", disabled=uploaded is None):
            try:
                url = _save_uploaded_file(uploaded, "brand")
                _write_app_config(BRAND_LOGO_CONFIG_KEY, url)
                st.success("Logo actualizado.")
            except Exception as exc:
                _render_action_error("No se pudo subir el logo.", exc)
        if cols[1].button("Quitar logo", disabled=not logo_url):
            try:
                _write_app_config(BRAND_LOGO_CONFIG_KEY, "")
                st.success("Logo eliminado.")
            except Exception as exc:
                _render_action_error("No se pudo quitar el logo.", exc)


@st.fragment
def _render_category_editor(categories: list[Categoria]) -> None:
    if not categories:
        st.info("No hay categorias cargadas.")
        return
    options = {f"{category.id} | {category.nombre}": category for category in categories}
    selected_label = st.selectbox("Categoria a editar", list(options))
    selected = options[selected_label]
    if selected.foto_url:
        st.image(selected.foto_url, caption="Foto actual", width=180)
    with st.form("category_editor"):
        nombre = st.text_input("Nombre", value=selected.nombre)
        descripcion = st.text_area("Descripcion publica", value=selected.descripcion_publica or "")
        orden = st.number_input("Orden", value=int(selected.orden), step=1)
        visible = st.checkbox("Visible para cliente", value=bool(selected.visible_cliente))
        activa = st.checkbox("Activa", value=bool(selected.activa))
        submitted = st.form_submit_button("Guardar categoria", use_container_width=True)
    if submitted:
        try:
            with Session(engine) as session:
                category = session.get(Categoria, selected.id)
                if category is None:
                    raise ValueError("La categoria seleccionada ya no existe.")
                category.nombre = " ".join(nombre.strip().split())
                category.descripcion_publica = " ".join(descripcion.strip().split()) or None
                category.orden = int(orden)
                category.visible_cliente = visible
                category.activa = activa
                session.add(category)
                session.commit()
            st.success("Categoria guardada.")
        except Exception as exc:
            _render_action_error("No se pudo guardar la categoria.", exc)
    uploaded = st.file_uploader("Foto de categoria", type=["png", "jpg", "jpeg", "webp"], key=f"category_image_{selected.id}")
    upload_cols = st.columns([1, 1, 2])
    if upload_cols[0].button("Subir foto", disabled=uploaded is None, key=f"upload_category_{selected.id}"):
        try:
            url = _save_uploaded_file(uploaded, "categories")
            with Session(engine) as session:
                category = session.get(Categoria, selected.id)
                if category is None:
                    st.error("Categoria inexistente.")
                    return
                category.foto_url = url
                session.add(category)
                session.commit()
            st.success("Foto de categoria actualizada.")
        except Exception as exc:
            _render_action_error("No se pudo subir la foto de la categoria.", exc)
    if upload_cols[1].button("Quitar foto", key=f"delete_category_image_{selected.id}"):
        try:
            with Session(engine) as session:
                category = session.get(Categoria, selected.id)
                if category is not None:
                    category.foto_url = None
                    session.add(category)
                    session.commit()
            st.success("Foto de categoria eliminada.")
        except Exception as exc:
            _render_action_error("No se pudo quitar la foto de la categoria.", exc)


@st.fragment
def _render_add_product_to_category(categories: list[Categoria], products: list[Producto]) -> None:
    if not categories:
        st.info("Primero debes crear una categoria.")
        return
    with st.expander("Agregar producto a una categoria", expanded=False):
        mode = st.radio(
            "Producto",
            ["Elegir producto existente", "Crear producto nuevo"],
            horizontal=True,
            key="add_product_mode",
        )
        category_options = {f"{category.id} | {category.nombre}": category.id for category in categories}
        category_label = st.selectbox("Categoria", list(category_options), key="add_product_category")
        product_options = {f"{product.id} | {product.nombre}": product.id for product in products}

        with st.form("add_product_to_category_form"):
            if mode == "Elegir producto existente":
                if not product_options:
                    st.info("No hay productos existentes. Elige Crear producto nuevo.")
                    product_label = None
                else:
                    product_label = st.selectbox("Producto existente", list(product_options))
                code = name = base_description = ""
                unit = UnidadVenta.UNIDAD.value
            else:
                product_label = None
                identity_cols = st.columns(2)
                code = identity_cols[0].text_input("Codigo del producto")
                name = identity_cols[1].text_input("Nombre del producto")
                base_description = st.text_area("Descripcion general")
                unit = st.selectbox("Unidad de venta", [item.value for item in UnidadVenta])

            price_cols = st.columns([1, 1])
            price = price_cols[0].number_input("Precio en esta categoria", min_value=0.0, value=0.0, step=100.0)
            order = price_cols[1].number_input("Orden", min_value=0, value=0, step=1)
            public_description = st.text_area("Descripcion publica en esta categoria")
            flag_cols = st.columns(3)
            visible = flag_cols[0].checkbox("Visible", value=True)
            featured = flag_cols[1].checkbox("Destacado", value=False)
            active = flag_cols[2].checkbox("Activo", value=True)
            submitted = st.form_submit_button("Agregar a la categoria", use_container_width=True)

        if submitted:
            try:
                if mode == "Elegir producto existente" and product_label is None:
                    raise ValueError("Selecciona un producto o crea uno nuevo.")
                with Session(engine) as session:
                    if mode == "Crear producto nuevo":
                        clean_code = " ".join(code.strip().split()).upper()
                        clean_name = " ".join(name.strip().split())
                        if not clean_code or not clean_name:
                            raise ValueError("El codigo y el nombre del producto son obligatorios.")
                        existing_product = session.exec(
                            select(Producto).where(func.upper(Producto.codigo) == clean_code)
                        ).first()
                        if existing_product is not None:
                            raise ValueError("Ya existe un producto con ese codigo. Elige el producto existente.")
                        product = Producto(
                            codigo=clean_code,
                            nombre=clean_name,
                            descripcion=" ".join(base_description.strip().split()) or None,
                            unidad_venta=UnidadVenta(unit),
                            activo=True,
                        )
                        session.add(product)
                        session.flush()
                        product_id = product.id or 0
                    else:
                        product_id = int(product_options[str(product_label)])

                    category_id = int(category_options[category_label])
                    existing_relation = session.exec(
                        select(ProductoCategoria).where(
                            ProductoCategoria.producto_id == product_id,
                            ProductoCategoria.categoria_id == category_id,
                        )
                    ).first()
                    if existing_relation is not None:
                        raise ValueError("Ese producto ya pertenece a la categoria seleccionada.")
                    session.add(
                        ProductoCategoria(
                            producto_id=product_id,
                            categoria_id=category_id,
                            precio=Decimal(str(price)).quantize(Decimal("0.01")),
                            descripcion_publica=" ".join(public_description.strip().split()) or None,
                            visible=visible,
                            orden=int(order),
                            destacado=featured,
                            activo=active,
                        )
                    )
                    session.commit()
                st.success("Producto agregado a la categoria.")
            except Exception as exc:
                _render_action_error("No se pudo agregar el producto a la categoria.", exc)


@st.fragment
def _render_product_category_editor(product_rows: list[dict[str, Any]]) -> None:
    if not product_rows:
        st.info("No hay productos asociados a categorias.")
        return
    options = {f"{row['relation_id']} | {row['categoria']} | {row['producto']}": row for row in product_rows}
    selected_label = st.selectbox("Producto en categoria", list(options))
    selected = options[selected_label]
    if selected["foto_url"]:
        st.image(selected["foto_url"], caption="Foto actual", width=180)
    with st.form("product_category_editor"):
        precio = st.number_input("Precio", min_value=0.0, value=float(selected["precio_raw"]), step=100.0)
        descripcion = st.text_area("Descripcion publica", value=selected["descripcion"] or "")
        orden = st.number_input("Orden", value=int(selected["orden"]), step=1)
        visible = st.checkbox("Visible", value=bool(selected["visible"]))
        destacado = st.checkbox("Destacado", value=bool(selected["destacado"]))
        activo = st.checkbox("Activo", value=bool(selected["activo"]))
        special = st.checkbox("Permitir pedido especial (por encargo)", value=bool(selected["permite_pedido_especial"]))
        st.caption("Por encargo se muestra únicamente en Consultar pedido especial. Requiere aceptar disponibilidad y conserva el precio de esta categoría.")
        submitted = st.form_submit_button("Guardar producto", use_container_width=True)
    if submitted:
        try:
            with Session(engine) as session:
                relation = session.get(ProductoCategoria, int(selected["relation_id"]))
                if relation is None:
                    raise ValueError("La asociacion seleccionada ya no existe.")
                relation.precio = Decimal(str(precio)).quantize(Decimal("0.01"))
                relation.descripcion_publica = " ".join(descripcion.strip().split()) or None
                relation.orden = int(orden)
                relation.visible = visible and not special
                relation.permite_pedido_especial = special
                relation.destacado = destacado
                relation.activo = activo
                session.add(relation)
                session.commit()
            st.success("Producto actualizado.")
        except Exception as exc:
            _render_action_error("No se pudo actualizar el producto.", exc)
    uploaded = st.file_uploader("Foto del producto en esta categoria", type=["png", "jpg", "jpeg", "webp"], key=f"product_image_{selected['relation_id']}")
    upload_cols = st.columns([1, 1, 2])
    if upload_cols[0].button("Subir foto", disabled=uploaded is None, key=f"upload_product_{selected['relation_id']}"):
        try:
            url = _save_uploaded_file(uploaded, "product-categories")
            with Session(engine) as session:
                relation = session.get(ProductoCategoria, int(selected["relation_id"]))
                if relation is None:
                    st.error("Relacion inexistente.")
                    return
                relation.foto_url = url
                session.add(relation)
                session.commit()
            st.success("Foto de producto actualizada.")
        except Exception as exc:
            _render_action_error("No se pudo subir la foto del producto.", exc)
    if upload_cols[1].button("Quitar foto", key=f"delete_product_image_{selected['relation_id']}"):
        try:
            with Session(engine) as session:
                relation = session.get(ProductoCategoria, int(selected["relation_id"]))
                if relation is not None:
                    relation.foto_url = None
                    session.add(relation)
                    session.commit()
            st.success("Foto de producto eliminada.")
        except Exception as exc:
            _render_action_error("No se pudo quitar la foto del producto.", exc)


@st.fragment
def _render_promotion_editor(promos: list[Promocion], products: list[Producto]) -> None:
    promo_options = {"Nueva promo": None}
    promo_options.update({f"{promo.id} | {promo.nombre}": promo for promo in promos})
    selected_label = st.selectbox("Promo", list(promo_options))
    selected = promo_options[selected_label]
    editor_key = str(selected.id) if selected else "new"
    with Session(engine) as session:
        categories = session.exec(select(Categoria).where(
            Categoria.activa == True, Categoria.es_automatica == False, Categoria.codigo != "EVENTOS",
        ).order_by(Categoria.orden, Categoria.nombre)).all()
        relations = session.exec(select(ProductoCategoria).where(
            ProductoCategoria.activo == True, ProductoCategoria.permite_pedido_especial == False,
        )).all()
        links = session.exec(select(PromocionProducto).where(PromocionProducto.promocion_id == selected.id)).all() if selected else []
        scopes = session.exec(select(PromocionCategoria).where(PromocionCategoria.promocion_id == selected.id)).all() if selected else []
        components = session.exec(select(PromocionItem).where(PromocionItem.promocion_id == selected.id)).all() if selected else []
    if selected and not scopes:
        st.warning("Esta promo no tiene categorías asignadas y no se aplica. Elegí sus categorías y guardala.")
    # These controls must rerun immediately so products follow the category selection.
    category_options = {category.id: category.nombre for category in categories}
    chosen_categories = st.multiselect(
        "Categorías de la promo", list(category_options),
        default=[link.categoria_id for link in scopes if link.categoria_id in category_options],
        format_func=category_options.get, key=f"promo_categories_{editor_key}",
    )
    eligible_ids = {relation.producto_id for relation in relations if relation.categoria_id in chosen_categories}
    product_options = {product.id: product.nombre for product in products if product.id in eligible_ids and product.activo}
    chosen_products = st.multiselect(
        "Productos elegibles", list(product_options),
        default=[link.producto_id for link in links if link.producto_id in product_options],
        format_func=product_options.get, key=f"promo_products_{editor_key}_{','.join(map(str, sorted(chosen_categories)))}",
    )
    package_mode = st.checkbox("Paquete combinado con cantidades por producto y categoría",
        value=bool(components), key=f"promo_package_{editor_key}")
    package_items = []
    if package_mode:
        st.caption("Indicá las unidades de cada producto por paquete completo. Usá 0 para excluir una presentación.")
        previous = {(item.producto_id, item.categoria_id): item.cantidad for item in components}
        for relation in sorted(relations, key=lambda item: (item.categoria_id, item.producto_id)):
            if relation.categoria_id not in chosen_categories or relation.producto_id not in chosen_products:
                continue
            quantity = st.number_input(
                f"{product_options[relation.producto_id]} · {category_options[relation.categoria_id]} — unidades por paquete",
                min_value=0, value=previous.get((relation.producto_id, relation.categoria_id), 0), step=1,
                key=f"promo_units_{editor_key}_{relation.producto_id}_{relation.categoria_id}",
            )
            if quantity:
                package_items.append((relation.producto_id, relation.categoria_id, int(quantity)))
        st.caption(f"Unidades por paquete: {sum(quantity for _, _, quantity in package_items)}")
    else:
        st.caption("La promo se evalúa por separado en cada categoría seleccionada. Las unidades sobrantes mantienen el precio base.")
    with st.form(f"promotion_editor_{editor_key}"):
        codigo = st.text_input("Codigo", value=selected.codigo if selected else "")
        nombre = st.text_input("Nombre", value=selected.nombre if selected else "")
        cantidad_minima = sum(quantity for _, _, quantity in package_items) if package_mode else st.number_input(
            "Cantidad minima", min_value=1, value=int(selected.cantidad_minima) if selected else 2, step=1,
        )
        precio_unitario = 0 if package_mode else st.number_input(
            "Precio unitario promocional", min_value=0.0,
            value=float(selected.precio_unitario_promocional) if selected else 0.0, step=100.0,
        )
        precio_total_default = float(selected.precio_total_promocional) if selected and selected.precio_total_promocional else 0.0
        precio_total = st.number_input("Precio total del paquete", min_value=0.0, value=precio_total_default, step=100.0)
        activa = st.checkbox("Activa", value=bool(selected.activa) if selected else True)
        submitted = st.form_submit_button("Guardar promo", use_container_width=True)
    if submitted:
        try:
            saved = _save_promotion(
                promo_id=selected.id if selected else None,
                codigo=codigo,
                nombre=nombre,
                cantidad_minima=sum(quantity for _, _, quantity in package_items) if package_mode else int(cantidad_minima),
                precio_unitario=Decimal(str(precio_unitario)).quantize(Decimal("0.01")),
                precio_total=Decimal(str(precio_total)).quantize(Decimal("0.01")) if precio_total else None,
                activa=activa,
                product_ids=chosen_products,
                category_ids=chosen_categories,
                package_items=package_items,
                package_mode=package_mode,
            )
            if saved:
                st.session_state.promotion_saved = True
                st.rerun()
        except Exception as exc:
            _render_action_error("No se pudo guardar la promocion.", exc)


@st.fragment
def _render_expense_form() -> None:
    expense_success_message = st.session_state.pop("expense_success_message", "")
    if expense_success_message:
        st.success(expense_success_message)
    st.caption("Carga un ticket completo: fecha y lugar una sola vez, luego agrega todos los items comprados.")
    header_cols = st.columns([1, 2])
    fecha = header_cols[0].date_input("Fecha", key="expense_ticket_date", format="DD-MM-YYYY")
    lugar = header_cols[1].text_input("Lugar", key="expense_ticket_place")
    payment_cols = st.columns(3)
    medio_pago = payment_cols[0].selectbox(
        "Medio de pago", ["", "EFECTIVO", "TRANSFERENCIA", "TARJETA", "OTRO"],
        key="expense_ticket_payment_method",
    )
    destinatario_pago = payment_cols[1].text_input(
        "Destinatario del pago (opcional)", key="expense_ticket_payment_recipient"
    )
    identificador_pago = payment_cols[2].text_input(
        "ID de operación (opcional)", key="expense_ticket_payment_id"
    )

    with st.form("expense_ticket_item_form", clear_on_submit=True):
        motivo = st.text_input("Motivo")
        marca = st.text_input("Marca (opcional)")
        descripcion = st.text_input("Descripcion")
        form_cols = st.columns(3)
        cantidad = form_cols[0].number_input("Cantidad", min_value=0.001, value=1.0, step=1.0)
        unidad = form_cols[1].text_input("Unidad", value="KG")
        total_item = form_cols[2].number_input("Total del item", min_value=0.0, value=0.0, step=100.0)
        add_item = st.form_submit_button("Agregar item", use_container_width=True)
    if add_item:
        added = _add_expense_ticket_item(
            motivo=motivo,
            marca=marca,
            descripcion=descripcion,
            cantidad=Decimal(str(cantidad)),
            unidad=unidad,
            total_item=Decimal(str(total_item)),
        )
        if added:
            st.success("Item agregado al ticket.")

    _render_expense_ticket_items()
    action_cols = st.columns([1, 1, 2])
    if action_cols[0].button("Guardar ticket", use_container_width=True, disabled=not st.session_state.expense_ticket_items):
        try:
            with Session(engine) as session:
                expense = ExpenseService(session).create_expense_ticket(
                    ExpenseTicketInput(
                        fecha=fecha,
                        lugar_texto=lugar,
                        items=[
                            ExpenseDetailInput(
                                motivo_nombre=item["motivo"],
                                marca_nombre=item["marca"],
                                descripcion=item["descripcion"] or None,
                                cantidad=Decimal(str(item["cantidad"])),
                                unidad_medida=item["unidad"],
                                precio_unitario=Decimal(str(item["precio_unitario"])),
                                subtotal=Decimal(str(item["subtotal"])),
                            )
                            for item in st.session_state.expense_ticket_items
                        ],
                        medio_pago=medio_pago or None,
                        destinatario_pago=destinatario_pago or None,
                        identificador_pago=identificador_pago or None,
                    ),
                    _current_user(),
                )
            st.session_state.expense_ticket_items = []
            _load_expense_rows.clear()
            st.session_state.expense_success_message = f"Gasto {expense.codigo} guardado."
            st.rerun(scope="fragment")
        except Exception as exc:
            _render_action_error("No se pudo guardar el gasto.", exc)
    if action_cols[1].button("Limpiar ticket", use_container_width=True, disabled=not st.session_state.expense_ticket_items):
        st.session_state.expense_ticket_items = []
        st.rerun(scope="fragment")


def _render_expense_capture() -> None:
    st.caption(
        "Subí una foto o PDF. El QR y el texto se leen localmente con Tesseract; "
        "nada se guarda hasta que confirmes."
    )
    uploaded = st.file_uploader(
        "Comprobante",
        type=["pdf", "png", "jpg", "jpeg"],
        key="expense_document_upload",
    )
    if uploaded is not None:
        content = uploaded.getvalue()
        content_type = uploaded.type or mimetypes.guess_type(uploaded.name)[0] or "application/octet-stream"
        if content_type.startswith("image/"):
            st.image(content, caption=uploaded.name, width=520)
        else:
            st.caption(f"PDF seleccionado: {uploaded.name}")
        if st.button("Analizar documento", type="primary", key="expense_analyze_document"):
            digest = hashlib.sha256(content).hexdigest()
            try:
                with Session(engine) as session:
                    duplicate = session.exec(
                        select(GastoDocumento).where(GastoDocumento.contenido_sha256 == digest)
                    ).first()
                if duplicate is not None:
                    st.error("Este documento ya está asociado a un gasto.")
                else:
                    try:
                        with st.spinner("Leyendo QR y texto localmente con Tesseract..."):
                            draft = HybridExpenseDocumentReader().analyze(content, content_type)
                    except Exception as exc:
                        draft = ExpenseDocumentDraft(
                            motor_lectura="manual-fallback",
                            advertencias=[
                                "Tesseract no pudo completar la lectura. Cargá o corregí los datos "
                                f"en el formulario: {exc}"
                            ],
                        )
                    if draft.fecha is None:
                        draft.fecha = _expense_date_from_filename(uploaded.name)
                    st.session_state.expense_capture_draft = draft
                    st.session_state.expense_capture_file = {
                        "name": uploaded.name,
                        "content": content,
                        "content_type": content_type,
                        "sha256": digest,
                    }
                    st.session_state.expense_capture_items = [
                        {
                            "Motivo": item.motivo,
                            "Marca": item.marca or "",
                            "Descripción": item.descripcion or "",
                            "Cantidad": float(item.cantidad),
                            "Unidad": item.unidad,
                            "Subtotal": float(item.subtotal),
                        }
                        for item in draft.items
                    ] or [{
                        "Motivo": "", "Marca": "", "Descripción": "",
                        "Cantidad": 1.0, "Unidad": "UNIDAD", "Subtotal": 0.0,
                    }]
                    st.rerun()
            except Exception as exc:
                _render_action_error("No se pudo preparar el documento.", exc)

    draft = st.session_state.get("expense_capture_draft")
    file_data = st.session_state.get("expense_capture_file")
    if not isinstance(draft, ExpenseDocumentDraft) or not file_data:
        st.info("El análisis aparecerá aquí para que puedas corregirlo antes de guardar.")
        return

    st.subheader("Revisar propuesta")
    if draft.qr_contenido:
        st.success("QR detectado localmente.")
    for warning in draft.advertencias:
        st.warning(warning)
    if draft.texto_extraido:
        with st.expander("Texto detectado por Tesseract", expanded=False):
            st.text(draft.texto_extraido)
    header_cols = st.columns([1, 2, 1])
    expense_date = header_cols[0].date_input(
        "Fecha", value=draft.fecha or date.today(), key="expense_capture_date", format="DD-MM-YYYY"
    )
    place = header_cols[1].text_input(
        "Lugar de compra", value=draft.lugar, key="expense_capture_place",
        help="Es el comercio o lugar donde compraste, no necesariamente el titular de la cuenta.",
    )
    expected_total = header_cols[2].number_input(
        "Total del documento", min_value=0.0, value=float(draft.monto_total or 0), step=100.0,
        key="expense_capture_total",
    )
    payment_cols = st.columns(3)
    payment_options = ["", "TRANSFERENCIA", "EFECTIVO", "TARJETA", "OTRO"]
    current_payment = draft.medio_pago or ""
    payment_method = payment_cols[0].selectbox(
        "Medio de pago", payment_options,
        index=payment_options.index(current_payment) if current_payment in payment_options else 0,
        key="expense_capture_payment_method",
    )
    payment_recipient = payment_cols[1].text_input(
        "Destinatario del pago", value=draft.destinatario_pago or "", key="expense_capture_recipient"
    )
    payment_id = payment_cols[2].text_input(
        "ID de operación", value=draft.identificador_pago or "", key="expense_capture_operation"
    )
    st.caption("La descripción del motivo se separa en ítems editables. Corregí cualquier dato dudoso.")
    edited_items = st.data_editor(
        st.session_state.expense_capture_items,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="expense_capture_item_editor",
        column_config={
            "Motivo": st.column_config.TextColumn(required=True),
            "Descripción": st.column_config.TextColumn(),
            "Cantidad": st.column_config.NumberColumn(min_value=0.001, step=0.001),
            "Unidad": st.column_config.TextColumn(required=True),
            "Subtotal": st.column_config.NumberColumn(min_value=0.0, step=100.0, format="$ %.2f"),
        },
    )
    calculated_total = sum(
        (Decimal(str(row.get("Subtotal") or 0)) for row in _editor_rows(edited_items)),
        Decimal("0"),
    )
    st.write(f"Total de ítems: {_money_text(calculated_total)}")
    action_cols = st.columns([1, 1, 3])
    if action_cols[0].button("Confirmar gasto", type="primary", key="expense_capture_confirm"):
        if not place.strip():
            st.error("Indicá el lugar de compra.")
            return
        if not edited_items:
            st.error("Agregá al menos un ítem.")
            return
        if calculated_total.quantize(Decimal("0.01")) != Decimal(str(expected_total)).quantize(Decimal("0.01")):
            st.error("El total de los ítems debe coincidir con el total del documento.")
            return
        try:
            details = _expense_details_from_editor(edited_items)
            with Session(engine) as session:
                expense = ExpenseService(session).create_expense_ticket(
                    ExpenseTicketInput(
                        fecha=expense_date,
                        lugar_texto=place,
                        items=details,
                        medio_pago=payment_method or None,
                        destinatario_pago=payment_recipient or None,
                        identificador_pago=payment_id or None,
                        observaciones="Carga asistida desde documento; datos confirmados por el usuario.",
                    ),
                    _current_user(),
                    commit=False,
                )
                safe_name = "".join(
                    char for char in file_data["name"] if char.isalnum() or char in {".", "-", "_"}
                )
                stored_url = save_media_bytes(
                    content=file_data["content"], folder="gastos",
                    filename=f"{file_data['sha256'][:12]}_{safe_name}",
                    content_type=file_data["content_type"],
                )
                session.add(GastoDocumento(
                    gasto_id=expense.id,
                    nombre_archivo=file_data["name"],
                    archivo_url=stored_url,
                    contenido_sha256=file_data["sha256"],
                    tipo_contenido=file_data["content_type"],
                    estado="confirmado",
                    motor_lectura=draft.motor_lectura,
                    qr_contenido=None,
                    texto_extraido=None,
                    datos_extraidos=draft.to_json(),
                    confianza=draft.confianza,
                ))
                session.commit()
            st.session_state.expense_capture_draft = None
            st.session_state.expense_capture_file = None
            st.session_state.expense_capture_items = []
            _load_expense_rows.clear()
            _load_expense_item_rows.clear()
            st.success(f"Gasto {expense.codigo} confirmado.")
            st.rerun()
        except Exception as exc:
            _render_action_error("No se pudo guardar el gasto leído.", exc)
    if action_cols[1].button("Descartar", key="expense_capture_discard"):
        st.session_state.expense_capture_draft = None
        st.session_state.expense_capture_file = None
        st.session_state.expense_capture_items = []
        st.rerun()


def _expense_details_from_editor(edited_items: Any) -> list[ExpenseDetailInput]:
    rows = _editor_rows(edited_items)
    if not rows:
        raise ValidationError("Agregá al menos un ítem.")
    details: list[ExpenseDetailInput] = []
    for row in rows:
        motive = " ".join(str(row.get("Motivo") or "").split())
        unit = " ".join(str(row.get("Unidad") or "").split())
        quantity = Decimal(str(row.get("Cantidad") or 0))
        subtotal = Decimal(str(row.get("Subtotal") or 0)).quantize(Decimal("0.01"))
        if not motive:
            raise ValidationError("Todos los ítems deben tener motivo.")
        if not unit:
            raise ValidationError("Todos los ítems deben tener unidad.")
        if quantity <= 0:
            raise ValidationError("Todas las cantidades deben ser mayores a cero.")
        if subtotal < 0:
            raise ValidationError("Los subtotales no pueden ser negativos.")
        details.append(ExpenseDetailInput(
            motivo_nombre=motive,
            marca_nombre=" ".join(str(row.get("Marca") or "").split()) or None,
            descripcion=" ".join(str(row.get("Descripción") or "").split()) or None,
            cantidad=quantity,
            unidad_medida=unit,
            precio_unitario=(subtotal / quantity).quantize(Decimal("0.01")),
            subtotal=subtotal,
        ))
    return details


def _editor_rows(edited_items: Any) -> list[dict[str, Any]]:
    if hasattr(edited_items, "to_dict"):
        return list(edited_items.to_dict("records"))
    return list(edited_items)


def _expense_date_from_filename(filename: str) -> date | None:
    match = re.search(r"(?:^|\D)(\d{1,2})[-_](\d{1,2})[-_](\d{2,4})(?:\D|$)", filename)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _add_expense_ticket_item(
    *,
    motivo: str,
    marca: str,
    descripcion: str,
    cantidad: Decimal,
    unidad: str,
    total_item: Decimal,
) -> bool:
    if not motivo.strip() or not unidad.strip():
        st.warning("Motivo y unidad son obligatorios para agregar un item.")
        return False
    if cantidad <= 0:
        st.warning("La cantidad debe ser mayor a cero.")
        return False
    if total_item < 0:
        st.warning("El total no puede ser negativo.")
        return False
    subtotal = total_item.quantize(Decimal("0.01"))
    precio_unitario = (subtotal / cantidad).quantize(Decimal("0.01"))
    st.session_state.expense_ticket_items = [
        *st.session_state.expense_ticket_items,
        {
            "motivo": " ".join(motivo.strip().split()),
            "marca": " ".join(marca.strip().split()),
            "descripcion": " ".join(descripcion.strip().split()),
            "cantidad": str(cantidad),
            "unidad": " ".join(unidad.strip().split()),
            "precio_unitario": str(precio_unitario),
            "subtotal": str(subtotal),
        },
    ]
    return True


def _render_expense_ticket_items() -> None:
    items = st.session_state.expense_ticket_items
    if not items:
        st.info("Agrega al menos un item para guardar el ticket.")
        return
    rows = [
        {
            "motivo": item["motivo"],
            "marca": item["marca"],
            "descripcion": item["descripcion"],
            "cantidad": item["cantidad"],
            "unidad": item["unidad"],
            "precio_unitario": _money_text(item["precio_unitario"]),
            "subtotal": _money_text(item["subtotal"]),
        }
        for item in items
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    total = sum((Decimal(str(item["subtotal"])) for item in items), Decimal("0.00"))
    st.write(f"Total temporal: {_money_text(total)}")
    remove_options = [f"{index + 1}. {item['motivo']} | {item['marca']} | {_money_text(item['subtotal'])}" for index, item in enumerate(items)]
    remove_choice = st.selectbox("Item a quitar", [""] + remove_options)
    if st.button("Quitar item", disabled=not remove_choice):
        index = remove_options.index(remove_choice)
        st.session_state.expense_ticket_items = [item for item_index, item in enumerate(items) if item_index != index]
        st.rerun(scope="fragment")


def _render_placeholder(title: str) -> None:
    st.title(title)
    st.info("Seccion preparada. Se conectara a los servicios compartidos en la siguiente fase.")


@st.cache_data(ttl=4, show_spinner=False)
def _load_order_rows() -> list[dict[str, Any]]:
    combo_product = aliased(Producto)
    with Session(engine) as session:
        order_rows = session.exec(
            select(Pedido, Cliente, ZonaEnvio)
            .select_from(Pedido)
            .join(Cliente, Cliente.id == Pedido.cliente_id)
            .outerjoin(ZonaEnvio, ZonaEnvio.id == Pedido.zona_envio_id)
        ).all()
        detail_rows = session.exec(
            select(PedidoItem, Producto, combo_product, Categoria)
            .select_from(PedidoItem)
            .join(Producto, Producto.id == PedidoItem.producto_id)
            .outerjoin(combo_product, combo_product.id == PedidoItem.producto_combo_id)
            .join(Categoria, Categoria.id == PedidoItem.categoria_venta_id)
        ).all()
        payment_rows = session.exec(select(PedidoPago).order_by(PedidoPago.id)).all()
        addon_rows = session.exec(select(PedidoItemAgregado).order_by(PedidoItemAgregado.id)).all()
        revision_rows = session.exec(
            select(PedidoRevision).order_by(PedidoRevision.created_at.desc(), PedidoRevision.id.desc())
        ).all()

    payments_by_order: dict[int, list[PedidoPago]] = {}
    for payment in payment_rows:
        payments_by_order.setdefault(payment.pedido_id, []).append(payment)
    addons_by_item: dict[int, list[PedidoItemAgregado]] = {}
    for addon in addon_rows:
        addons_by_item.setdefault(addon.pedido_item_id, []).append(addon)
    revisions_by_order: dict[int, list[PedidoRevision]] = {}
    for revision in revision_rows:
        revisions_by_order.setdefault(revision.pedido_id, []).append(revision)

    rows_by_id: dict[int, dict[str, Any]] = {}
    for pedido, cliente, zona in order_rows:
        order_id = pedido.id or 0
        payments = payments_by_order.get(order_id, [])
        if payments:
            payment_details = [
                {
                    "forma_pago": payment.forma_pago.value,
                    "monto": payment.monto,
                }
                for payment in payments
            ]
        else:
            payment_details = [{"forma_pago": pedido.forma_pago.value, "monto": pedido.monto_total}]
        rows_by_id[order_id] = {
            "id": pedido.id or 0,
            "codigo": pedido.codigo,
            "fecha_entrega": _date_text(pedido.fecha_entrega),
            "fecha_entrega_raw": pedido.fecha_entrega,
            "horario_entrega": pedido.horario_entrega.strftime("%H:%M") if pedido.horario_entrega else "Sin horario",
            "horario_entrega_raw": pedido.horario_entrega,
            "cliente": cliente.nombre_apellido,
            "telefono": cliente.telefono,
            "estado": pedido.estado.value,
            "forma_pago": pedido.forma_pago.value,
            "pagos": payment_details,
            "pagos_texto": " + ".join(
                f"{payment['forma_pago'].replace('_', ' ').title()} {_money_text(payment['monto'])}"
                for payment in payment_details
            ),
            "direccion": pedido.direccion_delivery,
            "zona": zona.nombre if zona else "Sin envio",
            "costo_envio": pedido.costo_envio,
            "monto_total": pedido.monto_total,
            "observaciones": pedido.observaciones or "",
            "creado": pedido.created_at,
            "items": [],
            "es_especial": False,
            "revisiones": [
                {
                    "fecha": revision.created_at,
                    "usuario": revision.usuario_nombre,
                    "accion": revision.accion,
                    "motivo": revision.motivo,
                }
                for revision in revisions_by_order.get(order_id, [])
            ],
        }
    for item, product, combo, category in detail_rows:
        order = rows_by_id.get(item.pedido_id)
        if order is None:
            continue
        order["es_especial"] = order["es_especial"] or item.es_especial
        item_addons = addons_by_item.get(item.id or 0, [])
        addon_details = [
            {
                "nombre": addon.agregado_nombre,
                "cantidad": addon.cantidad,
                "precio_unitario": addon.precio_unitario,
                "subtotal": addon.subtotal,
            }
            for addon in item_addons
        ]
        order["items"].append(
            {
                "producto": product.nombre,
                "id": item.id or 0,
                "producto_id": product.id or 0,
                "combo_id": combo.id if combo else None,
                "categoria_id": category.id or 0,
                "combo": combo.nombre if combo else "",
                "categoria": category.nombre,
                "cantidad": item.cantidad,
                "precio_unitario_raw": item.precio_unitario,
                "subtotal_raw": item.subtotal,
                "precio_unitario": _money_text(item.precio_unitario),
                "subtotal": _money_text(item.subtotal),
                "pedido_especial": item.es_especial,
                "agregados": addon_details,
                "agregados_texto": ", ".join(
                    f"{addon['cantidad']} × {addon['nombre']} ({_money_text(addon['subtotal'])})"
                    for addon in addon_details
                ),
            }
        )

    status_order = {
        EstadoPedido.PEDIDO.value: 0,
        EstadoPedido.PENDIENTE_CONFIRMACION.value: 0,
        EstadoPedido.EN_PROCESO.value: 1,
        EstadoPedido.ENTREGADO.value: 2,
        EstadoPedido.CANCELADO.value: 3,
    }
    return sorted(
        rows_by_id.values(),
        key=lambda row: (
            row["estado"] == EstadoPedido.CANCELADO.value,
            row["fecha_entrega_raw"],
            row["horario_entrega_raw"] or time.max,
            status_order.get(row["estado"], 9),
            row["id"],
        ),
    )


@st.cache_data(ttl=15, show_spinner=False)
def _load_expense_rows() -> list[dict[str, Any]]:
    with Session(engine) as session:
        gastos = session.exec(select(Gasto).order_by(Gasto.fecha.desc(), Gasto.id.desc())).all()
    return [
        {
            "id": gasto.id or 0,
            "codigo": gasto.codigo,
            "fecha": _date_text(gasto.fecha),
            "lugar": gasto.lugar_texto,
            "medio_pago": gasto.medio_pago or "",
            "destinatario_pago": gasto.destinatario_pago or "",
            "identificador_pago": gasto.identificador_pago or "",
            "monto_total": gasto.monto_total,
        }
        for gasto in gastos
    ]


@st.cache_data(ttl=15, show_spinner=False)
def _load_expense_item_rows() -> list[dict[str, Any]]:
    with Session(engine) as session:
        result = session.exec(
            select(GastoDetalle, Gasto, MotivoGasto, Marca)
            .join(Gasto, Gasto.id == GastoDetalle.gasto_id)
            .join(MotivoGasto, MotivoGasto.id == GastoDetalle.motivo_gasto_id)
            .outerjoin(Marca, Marca.id == GastoDetalle.marca_id)
            .order_by(Gasto.fecha.desc(), Gasto.id.desc(), GastoDetalle.id)
        ).all()
    return [
        {
            "detalle_id": detail.id or 0,
            "gasto_id": gasto.id or 0,
            "codigo": gasto.codigo,
            "fecha": _date_text(gasto.fecha),
            "fecha_raw": gasto.fecha,
            "motivo": motivo.nombre,
            "marca": marca.nombre if marca else "",
            "descripcion": detail.descripcion or "",
            "cantidad": detail.cantidad,
            "unidad": detail.unidad_medida,
            "subtotal": detail.subtotal,
            "lugar": gasto.lugar_texto,
            "medio_pago": gasto.medio_pago or "",
            "destinatario_pago": gasto.destinatario_pago or "",
            "identificador_pago": gasto.identificador_pago or "",
        }
        for detail, gasto, motivo, marca in result
    ]


def _load_catalog_rows() -> tuple[list[Categoria], list[dict[str, Any]], list[Producto]]:
    with Session(engine) as session:
        categories = session.exec(select(Categoria).order_by(Categoria.orden, Categoria.nombre)).all()
        product_list = session.exec(select(Producto).order_by(Producto.nombre)).all()
        products = {product.id: product for product in product_list}
        category_by_id = {category.id: category for category in categories}
        relations = session.exec(
            select(ProductoCategoria).order_by(ProductoCategoria.categoria_id, ProductoCategoria.orden)
        ).all()
    rows = []
    for relation in relations:
        product = products.get(relation.producto_id)
        category = category_by_id.get(relation.categoria_id)
        rows.append(
            {
                "relation_id": relation.id or 0,
                "categoria": category.nombre if category else "",
                "producto": product.nombre if product else "",
                "precio": _money_text(relation.precio),
                "precio_raw": str(relation.precio),
                "descripcion": relation.descripcion_publica or "",
                "foto_url": relation.foto_url or "",
                "orden": relation.orden,
                "visible": relation.visible,
                "permite_pedido_especial": relation.permite_pedido_especial,
                "destacado": relation.destacado,
                "activo": relation.activo,
            }
        )
    return categories, rows, product_list


def _load_promotion_rows() -> tuple[list[Promocion], list[dict[str, Any]], list[Producto]]:
    with Session(engine) as session:
        promos = session.exec(select(Promocion).order_by(Promocion.nombre)).all()
        products = session.exec(select(Producto).order_by(Producto.nombre)).all()
        product_by_id = {product.id: product for product in products}
        links = session.exec(select(PromocionProducto)).all()
        category_by_id = {category.id: category.nombre for category in session.exec(select(Categoria)).all()}
        scopes = session.exec(select(PromocionCategoria)).all()
        components = session.exec(select(PromocionItem)).all()
    product_names_by_promo: dict[int, list[str]] = {}
    for link in links:
        product = product_by_id.get(link.producto_id)
        if product:
            product_names_by_promo.setdefault(link.promocion_id, []).append(product.nombre)
    category_names_by_promo = {}
    for scope in scopes:
        category_names_by_promo.setdefault(scope.promocion_id, []).append(category_by_id.get(scope.categoria_id, ""))
    composition_by_promo = {}
    for item in components:
        product = product_by_id.get(item.producto_id)
        if product:
            composition_by_promo.setdefault(item.promocion_id, []).append(
                f"{item.cantidad} × {product.nombre} ({category_by_id.get(item.categoria_id, '')})"
            )
    rows = [
        {
            "id": promo.id,
            "codigo": promo.codigo,
            "nombre": promo.nombre,
            "cantidad_minima": promo.cantidad_minima,
            "precio_unitario": _money_text(promo.precio_unitario_promocional),
            "precio_total": _money_text(promo.precio_total_promocional) if promo.precio_total_promocional else "",
            "activa": promo.activa,
            "categorias": ", ".join(category_names_by_promo.get(promo.id, [])) or "Sin asignar: no se aplica",
            "paquete": " + ".join(composition_by_promo.get(promo.id, [])),
            "productos": ", ".join(product_names_by_promo.get(promo.id or 0, [])),
        }
        for promo in promos
    ]
    return promos, rows, products


def _load_admin_records(table_name: str) -> list[dict[str, Any]]:
    try:
        with Session(engine) as session:
            records = AdminCrudService(session).list_records(table_name, _current_user())
        return [
            {key: _format_display_value(value) for key, value in record.items()}
            for record in records
        ]
    except Exception as exc:
        _render_action_error("No se pudieron cargar los registros.", exc)
        return []


def _save_promotion(
    *,
    promo_id: int | None,
    codigo: str,
    nombre: str,
    cantidad_minima: int,
    precio_unitario: Decimal,
    precio_total: Decimal | None,
    activa: bool,
    product_ids: list[int],
    category_ids: list[int],
    package_items: list[tuple[int, int, int]],
    package_mode: bool,
) -> bool:
    if not codigo.strip() or not nombre.strip():
        st.error("Codigo y nombre son obligatorios.")
        return False
    if not product_ids:
        st.error("Selecciona al menos un producto elegible.")
        return False
    if package_mode and not package_items:
        st.error("Define las cantidades por producto del paquete combinado.")
        return False
    with Session(engine) as session:
        existing_links: list[PromocionProducto] = []
        if promo_id is None:
            promo = Promocion(
                codigo=codigo.strip().upper(),
                nombre=" ".join(nombre.strip().split()),
                tipo=TipoPromocion.PRECIO_UNITARIO_POR_CANTIDAD,
                cantidad_minima=cantidad_minima,
                precio_unitario_promocional=precio_unitario,
                precio_total_promocional=precio_total,
                activa=activa,
            )
            session.add(promo)
            session.flush()
        else:
            promo = session.get(Promocion, promo_id)
            if promo is None:
                st.error("Promocion inexistente.")
                return False
            promo.codigo = codigo.strip().upper()
            promo.nombre = " ".join(nombre.strip().split())
            promo.cantidad_minima = cantidad_minima
            promo.precio_unitario_promocional = precio_unitario
            promo.precio_total_promocional = precio_total
            promo.activa = activa
            session.add(promo)
            session.flush()
            existing_links = session.exec(select(PromocionProducto).where(PromocionProducto.promocion_id == promo.id)).all()
        configure_promotion(session, promo, category_ids, product_ids, package_items if package_mode else [])
        _sync_promotion_products(session, promo.id or 0, product_ids, existing_links=existing_links)
        session.commit()
    return True


def _sync_promotion_products(
    session: Session,
    promotion_id: int,
    product_ids: list[int],
    *,
    existing_links: list[PromocionProducto] | None = None,
) -> None:
    links = existing_links
    if links is None:
        links = session.exec(
            select(PromocionProducto).where(PromocionProducto.promocion_id == promotion_id)
        ).all()
    selected_product_ids = set(product_ids)
    existing_by_product = {link.producto_id: link for link in links}
    for product_id, link in existing_by_product.items():
        if product_id not in selected_product_ids:
            session.delete(link)
    for product_id in selected_product_ids - set(existing_by_product):
        session.add(PromocionProducto(promocion_id=promotion_id, producto_id=product_id))


def _read_app_config(key: str) -> str:
    with Session(engine) as session:
        setting = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
        return setting.value if setting and setting.value else ""


def _write_app_config(key: str, value: str) -> None:
    with Session(engine) as session:
        setting = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
        if setting is None:
            setting = AppConfig(key=key, value=value)
        else:
            setting.value = value
        session.add(setting)
        session.commit()


def _save_uploaded_file(uploaded_file: Any, folder: str) -> str:
    safe_name = "".join(char for char in uploaded_file.name if char.isalnum() or char in {".", "-", "_"})
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    content_type = uploaded_file.type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return save_media_bytes(
        content=uploaded_file.getvalue(),
        folder=folder,
        filename=filename,
        content_type=content_type,
    )


def _show_order_detail(order: dict[str, Any]) -> None:
    if hasattr(st, "dialog"):
        @st.dialog("Detalle del pedido")
        def dialog() -> None:
            _render_order_detail(order)

        dialog()
    else:
        with st.expander("Detalle del pedido", expanded=True):
            _render_order_detail(order)


def _render_order_admin_editor() -> None:
    if st.session_state.role != RolUsuario.ADMIN.value:
        return
    with st.expander("Modificar un pedido", expanded=False):
        st.caption("Buscá el código exacto. Los cambios quedan aplicados al pedido y sus totales.")
        cols = st.columns([3, 1])
        code = cols[0].text_input(
            "Código del pedido",
            placeholder="PED-0104",
            key="order_edit_search_code",
        ).strip().upper()
        if cols[1].button("Buscar y modificar", use_container_width=True, disabled=not code):
            order = next((row for row in _load_order_rows() if row["codigo"].upper() == code), None)
            if order is None:
                st.error("No existe un pedido con ese código.")
            else:
                _show_order_edit_dialog(order["id"])


def _show_order_edit_dialog(order_id: int) -> None:
    if hasattr(st, "dialog"):
        @st.dialog("Modificar pedido")
        def dialog() -> None:
            _render_order_edit_form(order_id)

        dialog()
    else:
        with st.expander("Modificar pedido", expanded=True):
            _render_order_edit_form(order_id)


def _render_order_edit_form(order_id: int) -> None:
    with Session(engine) as session:
        pedido = session.get(Pedido, order_id)
        if pedido is None:
            st.error("Pedido inexistente.")
            return
        cliente = session.get(Cliente, pedido.cliente_id)
        items = session.exec(
            select(PedidoItem).where(PedidoItem.pedido_id == order_id).order_by(PedidoItem.id)
        ).all()
        payments = session.exec(
            select(PedidoPago).where(PedidoPago.pedido_id == order_id).order_by(PedidoPago.id)
        ).all()
        products = session.exec(select(Producto).order_by(Producto.nombre)).all()
        categories = session.exec(select(Categoria).order_by(Categoria.nombre)).all()
        zones = session.exec(select(ZonaEnvio).order_by(ZonaEnvio.nombre)).all()
        product_by_id = {product.id: product for product in products}
        category_by_id = {category.id: category for category in categories}

    if cliente is None:
        st.error("El pedido no tiene un cliente válido.")
        return
    payment_amounts = {payment.forma_pago: payment.monto for payment in payments}
    product_names = [product.nombre for product in products]
    category_names = [category.nombre for category in categories]
    zone_labels = {"Sin zona": None, **{zone.nombre: zone.id for zone in zones}}
    selected_zone = next(
        (label for label, zone_id in zone_labels.items() if zone_id == pedido.zona_envio_id),
        "Sin zona",
    )
    item_rows = [
        {
            "ID": item.id,
            "Producto": product_by_id[item.producto_id].nombre,
            "Combinación": product_by_id[item.producto_combo_id].nombre if item.producto_combo_id else "",
            "Categoría": category_by_id[item.categoria_venta_id].nombre,
            "Cantidad": item.cantidad,
            "Subtotal": float(item.subtotal),
            "Especial": item.es_especial,
        }
        for item in items
    ]
    is_pending_confirmation = pedido.estado == EstadoPedido.PENDIENTE_CONFIRMACION
    is_in_preparation = pedido.estado == EstadoPedido.EN_PROCESO

    st.caption(f"{pedido.codigo} · El código no se modifica.")
    if is_pending_confirmation:
        st.info(
            "Podés guardar el acuerdo sin confirmarlo todavía o guardar y confirmar para que el pedido pase al orden normal."
        )
    if is_in_preparation:
        st.warning(
            "Este pedido ya está en preparación. Verificá el cambio con cocina antes de guardarlo."
        )
    with st.form(f"order_edit_form_{order_id}"):
        customer_cols = st.columns(2)
        customer_name = customer_cols[0].text_input("Cliente", value=cliente.nombre_apellido)
        customer_phone = customer_cols[1].text_input("Teléfono", value=cliente.telefono or "")
        st.caption("Actualizar estos datos modifica el cliente vinculado y, por lo tanto, todos sus pedidos históricos.")

        delivery_cols = st.columns(3)
        delivery_date = delivery_cols[0].date_input(
            "Fecha de entrega", value=pedido.fecha_entrega, format="DD/MM/YYYY"
        )
        has_delivery_time = delivery_cols[1].checkbox(
            "Tiene horario", value=pedido.horario_entrega is not None
        )
        delivery_time = delivery_cols[2].time_input(
            "Horario",
            value=pedido.horario_entrega or time(12, 0),
            disabled=not has_delivery_time,
        )
        address = st.text_input("Dirección", value=pedido.direccion_delivery)
        shipping_cols = st.columns(2)
        zone_label = shipping_cols[0].selectbox(
            "Zona", list(zone_labels), index=list(zone_labels).index(selected_zone)
        )
        shipping_cost = shipping_cols[1].number_input(
            "Costo de envío", min_value=0.0, value=float(pedido.costo_envio), step=100.0
        )

        state_cols = st.columns(2)
        payment_method = state_cols[0].selectbox(
            "Forma de pago",
            [payment.value for payment in FormaPago],
            index=[payment.value for payment in FormaPago].index(pedido.forma_pago.value),
            format_func=lambda value: value.replace("_", " ").title(),
        )
        state = state_cols[1].selectbox(
            "Estado",
            [status.value for status in EstadoPedido],
            index=[status.value for status in EstadoPedido].index(pedido.estado.value),
            format_func=lambda value: value.replace("_", " ").title(),
            disabled=is_pending_confirmation,
        )
        payment_cols = st.columns(2)
        cash_amount = payment_cols[0].number_input(
            "Monto en efectivo",
            min_value=0.0,
            value=float(payment_amounts.get(FormaPago.EFECTIVO, Decimal("0.00"))),
            step=100.0,
            help="Solo se usa manualmente cuando la forma de pago es Mixto.",
        )
        transfer_amount = payment_cols[1].number_input(
            "Monto por transferencia",
            min_value=0.0,
            value=float(payment_amounts.get(FormaPago.TRANSFERENCIA, Decimal("0.00"))),
            step=100.0,
            help="Solo se usa manualmente cuando la forma de pago es Mixto.",
        )
        observations = st.text_area("Observaciones", value=pedido.observaciones or "")
        change_reason = st.text_input(
            "Motivo del cambio",
            placeholder="Ej.: El cliente cambió la mitad de Fugazzetta por Muzzarella completa",
            help="Quedará registrado en el historial interno del pedido.",
        )
        preparation_acknowledged = False
        if is_in_preparation:
            preparation_acknowledged = st.checkbox(
                "Confirmo que avisé a cocina sobre esta modificación"
            )
        st.markdown("**Ítems del pedido**")
        edited_items = st.data_editor(
            item_rows,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "ID": st.column_config.NumberColumn("ID", disabled=True),
                "Producto": st.column_config.SelectboxColumn("Producto", options=product_names, required=True),
                "Combinación": st.column_config.SelectboxColumn("Combinación", options=["", *product_names]),
                "Categoría": st.column_config.SelectboxColumn("Categoría", options=category_names, required=True),
                "Cantidad": st.column_config.NumberColumn("Cantidad", min_value=1, step=1, required=True),
                "Subtotal": st.column_config.NumberColumn("Subtotal", min_value=0.01, format="$ %.2f", required=True),
                "Especial": st.column_config.CheckboxColumn("Pedido especial"),
            },
            key=f"order_items_editor_{order_id}",
        )
        if is_pending_confirmation:
            submit_columns = st.columns(2)
            keep_pending = submit_columns[0].form_submit_button(
                "Guardar y mantener pendiente",
                use_container_width=True,
            )
            save_and_confirm = submit_columns[1].form_submit_button(
                "Guardar y confirmar",
                type="primary",
                use_container_width=True,
            )
            submitted_action = (
                "confirmar_cambio" if save_and_confirm
                else "mantener_pendiente" if keep_pending
                else ""
            )
        else:
            submitted = st.form_submit_button(
                "Guardar cambios", type="primary", use_container_width=True
            )
            submitted_action = "modificar" if submitted else ""

    if not submitted_action:
        return
    rows = edited_items.to_dict("records") if hasattr(edited_items, "to_dict") else list(edited_items)
    try:
        _update_order(
            order_id=order_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_date=delivery_date,
            delivery_time=delivery_time if has_delivery_time else None,
            address=address,
            zone_id=zone_labels[zone_label],
            shipping_cost=Decimal(str(shipping_cost)),
            payment_method=FormaPago(payment_method),
            cash_amount=Decimal(str(cash_amount)),
            transfer_amount=Decimal(str(transfer_amount)),
            state=(
                EstadoPedido.PEDIDO if submitted_action == "confirmar_cambio"
                else EstadoPedido.PENDIENTE_CONFIRMACION if submitted_action == "mantener_pendiente"
                else EstadoPedido(state)
            ),
            observations=observations,
            item_rows=rows,
            change_reason=change_reason,
            action=submitted_action,
            preparation_acknowledged=preparation_acknowledged,
        )
        _load_order_rows.clear()
        updated_order = next(
            (row for row in _load_order_rows() if row["id"] == order_id),
            None,
        )
        st.session_state.order_success_message = f"Pedido {pedido.codigo} modificado"
        st.session_state.last_modified_order = {
            "codigo": pedido.codigo,
            "whatsapp_url": _updated_order_whatsapp_url(updated_order) if updated_order else "",
        }
        st.rerun()
    except (DomainError, ValueError, IntegrityError) as exc:
        _render_action_error("No se pudo modificar el pedido.", exc)


def _update_order(
    *,
    order_id: int,
    customer_name: str,
    customer_phone: str,
    delivery_date: date,
    delivery_time: time | None,
    address: str,
    zone_id: int | None,
    shipping_cost: Decimal,
    payment_method: FormaPago,
    cash_amount: Decimal,
    transfer_amount: Decimal,
    state: EstadoPedido,
    observations: str,
    item_rows: list[dict[str, Any]],
    change_reason: str = "Modificación administrativa",
    action: str = "modificar",
    preparation_acknowledged: bool = False,
) -> None:
    if not customer_name.strip():
        raise ValidationError("El nombre del cliente es obligatorio.")
    if not address.strip():
        raise ValidationError("La dirección es obligatoria.")
    if shipping_cost < 0:
        raise ValidationError("El costo de envío no puede ser negativo.")
    if not item_rows:
        raise ValidationError("El pedido debe tener al menos un ítem.")
    if not change_reason.strip():
        raise ValidationError("Indicá el motivo del cambio para guardarlo en el historial.")
    if action not in {"modificar", "mantener_pendiente", "confirmar_cambio"}:
        raise ValidationError("La acción de modificación no es válida.")

    with Session(engine) as session:
        current_user = _current_user()
        AuthService(session).require_admin(current_user)
        pedido = session.get(Pedido, order_id)
        if pedido is None:
            raise ValidationError("Pedido inexistente.")
        cliente = session.get(Cliente, pedido.cliente_id)
        if cliente is None:
            raise ValidationError("Cliente inexistente.")
        if pedido.estado == EstadoPedido.EN_PROCESO and not preparation_acknowledged:
            raise ValidationError("Confirmá que avisaste a cocina antes de modificar el pedido.")
        if action in {"mantener_pendiente", "confirmar_cambio"}:
            if pedido.estado != EstadoPedido.PENDIENTE_CONFIRMACION:
                raise ValidationError("El pedido ya no está pendiente de confirmación.")
            state = (
                EstadoPedido.PEDIDO
                if action == "confirmar_cambio"
                else EstadoPedido.PENDIENTE_CONFIRMACION
            )
        previous_snapshot = _order_revision_snapshot(session, pedido, cliente)
        products = session.exec(select(Producto)).all()
        categories = session.exec(select(Categoria)).all()
        product_categories = session.exec(select(ProductoCategoria)).all()
        product_by_name = {product.nombre: product for product in products}
        category_by_name = {category.nombre: category for category in categories}
        allowed_product_categories = {
            (relation.producto_id, relation.categoria_id)
            for relation in product_categories
        }
        existing_items = {
            item.id: item
            for item in session.exec(select(PedidoItem).where(PedidoItem.pedido_id == order_id)).all()
        }
        submitted_ids: set[int] = set()
        prepared_rows: list[tuple[PedidoItem, Decimal]] = []
        addon_total = Decimal("0.00")

        for row in item_rows:
            raw_id = row.get("ID")
            item_id = None if _is_blank_cell(raw_id) else int(raw_id)
            if item_id is not None:
                item = existing_items.get(item_id)
                if item is None:
                    raise ValidationError("Uno de los ítems no pertenece al pedido.")
                if item_id in submitted_ids:
                    raise ValidationError("Hay un ítem duplicado en la edición.")
                submitted_ids.add(item_id)
            else:
                item = PedidoItem(
                    pedido_id=order_id,
                    producto_id=0,
                    categoria_venta_id=0,
                    cantidad=1,
                    precio_unitario=Decimal("0.00"),
                    subtotal=Decimal("0.00"),
                )

            product = product_by_name.get(str(row.get("Producto") or ""))
            category = category_by_name.get(str(row.get("Categoría") or ""))
            combo_name = "" if _is_blank_cell(row.get("Combinación")) else str(row["Combinación"])
            combo = product_by_name.get(combo_name) if combo_name else None
            if product is None or category is None or (combo_name and combo is None):
                raise ValidationError("Revisá producto, combinación y categoría de todos los ítems.")
            if combo is not None and combo.id == product.id:
                raise ValidationError("Una pizza mitad y mitad debe tener dos sabores diferentes.")
            if (product.id, category.id) not in allowed_product_categories or (
                combo is not None and (combo.id, category.id) not in allowed_product_categories
            ):
                raise ValidationError("El producto elegido no está disponible en esa categoría.")
            raw_quantity = row.get("Cantidad")
            raw_subtotal = row.get("Subtotal")
            if _is_blank_cell(raw_quantity) or _is_blank_cell(raw_subtotal):
                raise ValidationError("Cantidad y subtotal son obligatorios en todos los ítems.")
            try:
                quantity_value = Decimal(str(raw_quantity))
                if not quantity_value.is_finite() or quantity_value != quantity_value.to_integral_value():
                    raise ValueError
                quantity = int(quantity_value)
                subtotal = Decimal(str(raw_subtotal)).quantize(Decimal("0.01"))
            except (TypeError, ValueError, ArithmeticError):
                raise ValidationError("Cantidad y subtotal deben ser números válidos.") from None
            if quantity <= 0 or not subtotal.is_finite() or subtotal <= 0:
                raise ValidationError("Cantidad y subtotal deben ser mayores a cero.")
            item.producto_id = product.id or 0
            item.producto_combo_id = combo.id if combo else None
            item.categoria_venta_id = category.id or 0
            item.cantidad = quantity
            item.subtotal = subtotal
            item.precio_unitario = (subtotal / Decimal(quantity)).quantize(Decimal("0.01"))
            item.es_especial = bool(row.get("Especial", False))
            session.add(item)
            session.flush()

            item_addons = session.exec(
                select(PedidoItemAgregado).where(PedidoItemAgregado.pedido_item_id == item.id)
            ).all()
            for addon in item_addons:
                enabled = session.exec(select(AgregadoCategoria).where(
                    AgregadoCategoria.agregado_id == addon.agregado_id,
                    AgregadoCategoria.categoria_id == item.categoria_venta_id,
                )).first()
                if enabled is None:
                    raise ValidationError(
                        f"El agregado {addon.agregado_nombre} no está habilitado para la categoría elegida."
                    )
                addon_total += addon.subtotal
            prepared_rows.append((item, subtotal))

        for item_id, item in existing_items.items():
            if item_id in submitted_ids:
                continue
            for addon in session.exec(select(PedidoItemAgregado).where(
                PedidoItemAgregado.pedido_item_id == item_id
            )).all():
                session.delete(addon)
            session.delete(item)

        total = (
            sum((subtotal for _, subtotal in prepared_rows), Decimal("0.00"))
            + addon_total
            + shipping_cost
        ).quantize(Decimal("0.01"))
        if payment_method == FormaPago.MIXTO:
            cash = cash_amount.quantize(Decimal("0.01"))
            transfer = transfer_amount.quantize(Decimal("0.01"))
            if cash <= 0 or transfer <= 0 or cash + transfer != total:
                raise ValidationError("Los pagos divididos deben ser mayores a cero y sumar el total del pedido.")
            new_payments = ((FormaPago.EFECTIVO, cash), (FormaPago.TRANSFERENCIA, transfer))
        else:
            new_payments = ((payment_method, total),)
        for payment in session.exec(select(PedidoPago).where(PedidoPago.pedido_id == order_id)).all():
            session.delete(payment)
        for form, amount in new_payments:
            session.add(PedidoPago(pedido_id=order_id, forma_pago=form, monto=amount))

        cliente.nombre_apellido = " ".join(customer_name.strip().split())
        cliente.telefono = normalize_phone(customer_phone) if customer_phone.strip() else None
        cliente.updated_at = datetime.now(timezone.utc)
        pedido.fecha_entrega = delivery_date
        pedido.horario_entrega = delivery_time
        pedido.direccion_delivery = address.strip()
        pedido.zona_envio_id = zone_id
        pedido.costo_envio = shipping_cost.quantize(Decimal("0.01"))
        pedido.forma_pago = payment_method
        pedido.estado = state
        pedido.observaciones = observations.strip() or None
        pedido.monto_total = total
        pedido.updated_at = datetime.now(timezone.utc)
        session.add(cliente)
        session.add(pedido)
        session.flush()
        new_snapshot = _order_revision_snapshot(session, pedido, cliente)
        session.add(PedidoRevision(
            pedido_id=order_id,
            usuario_id=current_user.id,
            usuario_nombre=current_user.username,
            accion=action,
            motivo=" ".join(change_reason.strip().split()),
            resumen_anterior=json.dumps(previous_snapshot, ensure_ascii=False, sort_keys=True),
            resumen_nuevo=json.dumps(new_snapshot, ensure_ascii=False, sort_keys=True),
        ))
        session.commit()


def _order_revision_snapshot(
    session: Session,
    pedido: Pedido,
    cliente: Cliente,
) -> dict[str, Any]:
    items = session.exec(
        select(PedidoItem).where(PedidoItem.pedido_id == pedido.id).order_by(PedidoItem.id)
    ).all()
    product_ids = {
        product_id
        for item in items
        for product_id in (item.producto_id, item.producto_combo_id)
        if product_id is not None
    }
    category_ids = {item.categoria_venta_id for item in items}
    products = {
        product.id: product.nombre
        for product in session.exec(select(Producto).where(Producto.id.in_(product_ids))).all()
    } if product_ids else {}
    categories = {
        category.id: category.nombre
        for category in session.exec(select(Categoria).where(Categoria.id.in_(category_ids))).all()
    } if category_ids else {}
    item_ids = [item.id for item in items if item.id is not None]
    addons_by_item: dict[int, list[dict[str, Any]]] = {}
    if item_ids:
        for addon in session.exec(
            select(PedidoItemAgregado).where(PedidoItemAgregado.pedido_item_id.in_(item_ids))
        ).all():
            addons_by_item.setdefault(addon.pedido_item_id, []).append({
                "nombre": addon.agregado_nombre,
                "cantidad": addon.cantidad,
                "subtotal": str(addon.subtotal),
            })
    payments = session.exec(
        select(PedidoPago).where(PedidoPago.pedido_id == pedido.id).order_by(PedidoPago.id)
    ).all()
    return {
        "codigo": pedido.codigo,
        "cliente": cliente.nombre_apellido,
        "telefono": cliente.telefono,
        "fecha_entrega": pedido.fecha_entrega.isoformat(),
        "horario_entrega": pedido.horario_entrega.isoformat() if pedido.horario_entrega else None,
        "direccion": pedido.direccion_delivery,
        "zona_envio_id": pedido.zona_envio_id,
        "costo_envio": str(pedido.costo_envio),
        "estado": pedido.estado.value,
        "forma_pago": pedido.forma_pago.value,
        "monto_total": str(pedido.monto_total),
        "observaciones": pedido.observaciones,
        "pagos": [
            {"forma_pago": payment.forma_pago.value, "monto": str(payment.monto)}
            for payment in payments
        ],
        "items": [
            {
                "id": item.id,
                "producto": products.get(item.producto_id, ""),
                "combinacion": products.get(item.producto_combo_id, "") if item.producto_combo_id else "",
                "categoria": categories.get(item.categoria_venta_id, ""),
                "cantidad": item.cantidad,
                "precio_unitario": str(item.precio_unitario),
                "subtotal": str(item.subtotal),
                "es_especial": item.es_especial,
                "agregados": addons_by_item.get(item.id or 0, []),
            }
            for item in items
        ],
    }


def _updated_order_whatsapp_url(order: dict[str, Any] | None) -> str:
    if not order or not order.get("telefono"):
        return ""
    item_lines: list[str] = []
    for item in order["items"]:
        product = item["producto"]
        if item.get("combo"):
            product = f"Mitad {product} / mitad {item['combo']}"
        line = f"- {item['cantidad']} x {product} ({item['subtotal']})"
        if item.get("agregados_texto"):
            line += f" + {item['agregados_texto']}"
        item_lines.append(line)
    message = "\n".join([
        f"Hola {order['cliente']}, te envío la actualización de tu pedido {order['codigo']}:",
        *item_lines,
        f"Envío: {_money_text(order['costo_envio'])}",
        f"Total: {_money_text(order['monto_total'])}",
        f"Entrega: {order['fecha_entrega']} · {order['horario_entrega']}",
    ])
    return f"https://wa.me/549{order['telefono']}?text={quote(message)}"


def _is_blank_cell(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, float) and math.isnan(value))


def _show_expense_detail(expense_id: int) -> None:
    if hasattr(st, "dialog"):
        @st.dialog("Detalle del gasto")
        def dialog() -> None:
            _render_expense_detail(expense_id)

        dialog()
    else:
        with st.expander("Detalle del gasto", expanded=True):
            _render_expense_detail(expense_id)


def _render_order_detail(order: dict[str, Any]) -> None:
    st.subheader(order["codigo"])
    st.write(f"Cliente: {order['cliente']}")
    st.write(f"Telefono: {order['telefono'] or 'Sin teléfono'}")
    st.write(f"Entrega: {order['fecha_entrega']} a las {order['horario_entrega']}")
    st.write(f"Direccion: {order['direccion']}")
    st.write(f"Zona: {order['zona']}")
    st.markdown(f"Estado: {_state_badge(order['estado'])}", unsafe_allow_html=True)
    if order.get("es_especial", False):
        st.info("Pedido especial. El precio registrado es definitivo; solo se debe aceptar la disponibilidad.")
        st.caption("Si hace falta proponer un cambio, acordalo con el cliente antes de confirmar. No se cambian productos ni precios automáticamente.")
        if order["telefono"]:
            message = quote(f"Hola {order['cliente']}, te contactamos por la disponibilidad de tu pedido especial {order['codigo']}.")
            st.link_button("Coordinar con el cliente por WhatsApp", f"https://wa.me/549{order['telefono']}?text={message}")
        else:
            st.caption("Este cliente histórico no tiene teléfono cargado.")
    item_rows = [
        {
            "Producto": item["producto"],
            "Combinación": item["combo"],
            "Categoría": item["categoria"],
            "Cantidad": item["cantidad"],
            "Precio unitario": item["precio_unitario"],
            "Subtotal": item["subtotal"],
            "Agregados": item["agregados_texto"],
            "Pedido especial": "Sí" if item["pedido_especial"] else "No",
        }
        for item in order["items"]
    ]
    st.dataframe(item_rows, hide_index=True, use_container_width=True)
    if order["observaciones"]:
        st.write(f"Observaciones: {order['observaciones']}")
    st.write(f"Envio: {_money_text(order['costo_envio'])}")
    st.write(f"Pago: {order['pagos_texto']}")
    st.write(f"Total: {_money_text(order['monto_total'])}")
    if order.get("revisiones"):
        action_labels = {
            "modificar": "Modificado",
            "mantener_pendiente": "Modificado · continúa pendiente",
            "confirmar_cambio": "Modificado y confirmado",
        }
        with st.expander(f"Historial de cambios ({len(order['revisiones'])})"):
            st.dataframe(
                [
                    {
                        "Fecha": _format_display_value(revision["fecha"]),
                        "Usuario": revision["usuario"],
                        "Acción": action_labels.get(revision["accion"], revision["accion"]),
                        "Motivo": revision["motivo"],
                    }
                    for revision in order["revisiones"]
                ],
                hide_index=True,
                use_container_width=True,
            )


def _render_expense_detail(expense_id: int) -> None:
    with Session(engine) as session:
        gasto = session.get(Gasto, expense_id)
        if gasto is None:
            st.error("Gasto inexistente.")
            return
        details = session.exec(select(GastoDetalle).where(GastoDetalle.gasto_id == expense_id)).all()
        documents = session.exec(
            select(GastoDocumento).where(GastoDocumento.gasto_id == expense_id)
        ).all()
        motivos = {motivo.id: motivo for motivo in session.exec(select(MotivoGasto)).all()}
        marcas = {marca.id: marca for marca in session.exec(select(Marca)).all()}

    st.subheader(gasto.codigo)
    st.write(f"Fecha: {_date_text(gasto.fecha)}")
    st.write(f"Lugar: {gasto.lugar_texto}")
    if gasto.medio_pago:
        st.write(f"Medio de pago: {gasto.medio_pago}")
    if gasto.destinatario_pago:
        st.write(f"Destinatario del pago: {gasto.destinatario_pago}")
    if gasto.identificador_pago:
        st.write(f"ID de operación: {gasto.identificador_pago}")
    rows = [
        {
            "motivo": motivos[detail.motivo_gasto_id].nombre if detail.motivo_gasto_id in motivos else "",
            "marca": marcas[detail.marca_id].nombre if detail.marca_id in marcas else "",
            "descripcion": detail.descripcion or "",
            "cantidad": str(detail.cantidad),
            "unidad": detail.unidad_medida,
            "precio_unitario": _money_text(detail.precio_unitario),
            "subtotal": _money_text(detail.subtotal),
        }
        for detail in details
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.write(f"Total: {_money_text(gasto.monto_total)}")
    if documents:
        st.markdown("**Documentos asociados**")
        for document in documents:
            st.caption(
                f"{document.nombre_archivo} · {document.motor_lectura or 'carga manual'} · "
                f"estado {document.estado}"
            )


def _transition_order(order_id: int, next_state: EstadoPedido) -> None:
    try:
        with Session(engine) as session:
            OrderService(session).transition_order(order_id, next_state, _current_user())
        _load_order_rows.clear()
        st.success("Estado actualizado.")
    except DomainError as exc:
        _render_action_error("No se pudo actualizar el estado del pedido.", exc)


def _current_user() -> UsuarioRead:
    role = RolUsuario(st.session_state.role or RolUsuario.DUENO.value)
    return UsuarioRead(
        id=int(st.session_state.user_id),
        username=str(st.session_state.username),
        rol=role,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _create_auth_token(
    user_id: int,
    *,
    now: int | None = None,
    secret: str | None = None,
) -> str:
    expires_at = (now if now is not None else int(time_module.time())) + AUTH_SESSION_SECONDS
    payload = f"{user_id}:{expires_at}".encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signing_secret = (secret or get_settings().app_secret_key).encode("utf-8")
    signature = hmac.new(signing_secret, encoded_payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded_payload}.{signature}"


def _decode_auth_token(
    token: str,
    *,
    now: int | None = None,
    secret: str | None = None,
) -> int | None:
    try:
        encoded_payload, signature = token.split(".", 1)
        signing_secret = (secret or get_settings().app_secret_key).encode("utf-8")
        expected_signature = hmac.new(
            signing_secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return None
        padding = "=" * (-len(encoded_payload) % 4)
        user_id_text, expires_at_text = base64.urlsafe_b64decode(
            encoded_payload + padding
        ).decode("utf-8").split(":", 1)
        user_id = int(user_id_text)
        expires_at = int(expires_at_text)
        current_time = now if now is not None else int(time_module.time())
        if user_id <= 0 or expires_at <= current_time:
            return None
        return user_id
    except (binascii.Error, TypeError, ValueError, UnicodeDecodeError):
        return None


def _persist_authentication(user_id: int) -> None:
    st.query_params[AUTH_QUERY_PARAM] = _create_auth_token(user_id)


def _restore_authentication() -> None:
    if _is_authenticated():
        return
    token = st.query_params.get(AUTH_QUERY_PARAM, "")
    user_id = _decode_auth_token(token) if token else None
    if user_id is None:
        if token:
            st.query_params.pop(AUTH_QUERY_PARAM, None)
        return
    with Session(engine) as session:
        user = session.get(Usuario, user_id)
    if user is None:
        st.query_params.pop(AUTH_QUERY_PARAM, None)
        return
    st.session_state.user_id = user.id or 0
    st.session_state.username = user.username
    st.session_state.role = user.rol.value


def _is_authenticated() -> bool:
    return int(st.session_state.get("user_id") or 0) > 0


def _is_admin() -> bool:
    return _is_authenticated() and st.session_state.get("role") == RolUsuario.ADMIN.value


def _logout() -> None:
    st.session_state.user_id = 0
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.auth_message = ""
    st.session_state.show_delivered_orders = False
    st.query_params.pop(AUTH_QUERY_PARAM, None)


def _money_text(value: Decimal | str | int | float) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return f"$ {amount:.2f}".replace(".", ",")


def _date_text(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _format_display_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y %H:%M")
    if isinstance(value, date):
        return _date_text(value)
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return value


def _render_action_error(message: str, exc: Exception) -> None:
    st.error(_friendly_internal_error(message, exc))
    with st.expander("Ver detalles tecnicos", expanded=False):
        st.code(f"{type(exc).__name__}: {exc}", language="text")


def _friendly_internal_error(message: str, exc: Exception) -> str:
    if isinstance(exc, DomainError):
        return str(exc)
    if isinstance(exc, ValueError):
        return str(exc) or message
    if isinstance(exc, IntegrityError):
        detail = str(exc).lower()
        if "promocion_producto" in detail:
            return "Uno de los productos ya esta asociado a esta promocion. Actualiza la pagina e intenta nuevamente."
        if "producto_categoria" in detail:
            return "Ese producto ya pertenece a la categoria seleccionada."
        if "duplicate key" in detail or "unique" in detail:
            return "Ya existe un registro con esos datos. Revisa el codigo o la seleccion realizada."
    lowered = str(exc).lower()
    if "could not connect" in lowered or "connection" in lowered or "timeout" in lowered:
        return "No se pudo conectar con la base de datos. Espera unos segundos e intenta nuevamente."
    return message


def _build_production_summary(orders: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    excluded_states = {EstadoPedido.ENTREGADO.value, EstadoPedido.CANCELADO.value, EstadoPedido.PENDIENTE_CONFIRMACION.value}
    summary: dict[str, dict[str, Any]] = {}
    for order in orders:
        if order["estado"] in excluded_states:
            continue
        delivery_date = order["fecha_entrega"]
        date_summary = summary.setdefault(delivery_date, {"order_ids": set(), "categories": {}})
        date_summary["order_ids"].add(order["id"])
        for item in order["items"]:
            category_products = date_summary["categories"].setdefault(item["categoria"], {})
            product_label = (
                f"Mitad {item['producto']} / mitad {item['combo']}"
                if item["combo"]
                else item["producto"]
            )
            category_products[product_label] = category_products.get(product_label, 0) + int(item["cantidad"])

    ordered: dict[str, dict[str, Any]] = {}
    for delivery_date in sorted(summary, key=lambda value: datetime.strptime(value, "%d-%m-%Y")):
        data = summary[delivery_date]
        ordered[delivery_date] = {
            "order_count": len(data["order_ids"]),
            "categories": {
                category: dict(sorted(products.items()))
                for category, products in sorted(data["categories"].items())
            },
        }
    return ordered


def _transition_label(state: EstadoPedido) -> str:
    return {
        EstadoPedido.PEDIDO: "🟡 Marcar pedido",
        EstadoPedido.PENDIENTE_CONFIRMACION: "🟡 Pendiente de confirmacion",
        EstadoPedido.EN_PROCESO: "🟠 Pasar a preparacion",
        EstadoPedido.ENTREGADO: "🟢 Marcar entregado",
        EstadoPedido.CANCELADO: "🔴 Cancelar pedido",
    }[state]


def _state_badge(state: str) -> str:
    label, background, color = {
        EstadoPedido.PEDIDO.value: ("Pedido", "#fff3bf", "#674d00"),
        EstadoPedido.PENDIENTE_CONFIRMACION.value: ("Pendiente de confirmacion", "#fff3bf", "#674d00"),
        EstadoPedido.EN_PROCESO.value: ("En preparacion", "#ffe8cc", "#8a3b00"),
        EstadoPedido.ENTREGADO.value: ("Entregado", "#d3f9d8", "#14532d"),
        EstadoPedido.CANCELADO.value: ("Cancelado", "#ffe3e3", "#991b1b"),
    }.get(state, (state, "#eeeeee", "#333333"))
    return (
        f'<span style="display:inline-block;padding:.2rem .55rem;border-radius:999px;'
        f'background:{background};color:{color};font-weight:700">{label}</span>'
    )
