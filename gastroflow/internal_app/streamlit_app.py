from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import streamlit as st
from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.domain.enums import EstadoPedido, RolUsuario, TipoPromocion
from gastroflow.domain.errors import DomainError
from gastroflow.domain.order_state import valid_next_states
from gastroflow.models import (
    AppConfig,
    Categoria,
    Cliente,
    Gasto,
    GastoDetalle,
    Marca,
    MotivoGasto,
    Pedido,
    PedidoItem,
    Producto,
    ProductoCategoria,
    Promocion,
    PromocionProducto,
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
)
from gastroflow.services.media_storage import save_media_bytes

BRAND_LOGO_CONFIG_KEY = "brand.logo_url"


def main() -> None:
    st.set_page_config(
        page_title="GastroFlow Gestion",
        page_icon="GF",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_session_state()
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
        "selected_expense_id": None,
        "expense_ticket_items": [],
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
            st.rerun()
        except DomainError as exc:
            st.session_state.auth_message = str(exc)
    if st.session_state.auth_message:
        st.error(st.session_state.auth_message)


def _render_orders() -> None:
    st.title("Pedidos")
    orders = _load_order_rows()
    metric_cols = st.columns(4)
    total_amount = sum((row["monto_total"] for row in orders), Decimal("0.00"))
    metric_cols[0].metric("Pedidos", len(orders))
    metric_cols[1].metric("Total", _money_text(total_amount))
    metric_cols[2].metric("Pendientes", sum(1 for row in orders if row["estado"] == EstadoPedido.PEDIDO.value))
    metric_cols[3].metric(
        "En proceso",
        sum(1 for row in orders if row["estado"] == EstadoPedido.EN_PROCESO.value),
    )

    if not orders:
        st.info("Todavia no hay pedidos.")
        return

    for row in orders:
        with st.container(border=True):
            cols = st.columns([1.1, 1.4, 1.2, 1.2, 1.1, 1])
            cols[0].markdown(f"**{row['codigo']}**")
            cols[1].write(row["cliente"])
            cols[2].write(row["fecha_entrega"])
            cols[3].write(row["estado"])
            cols[4].write(_money_text(row["monto_total"]))
            if cols[5].button("Ver detalles", key=f"order_detail_{row['id']}", use_container_width=True):
                st.session_state.selected_order_id = row["id"]
                _show_order_detail(row["id"])

            next_states = valid_next_states(EstadoPedido(row["estado"]))
            if next_states:
                action_cols = st.columns(len(next_states))
                for index, next_state in enumerate(sorted(next_states, key=lambda item: item.value)):
                    if action_cols[index].button(
                        f"Pasar a {next_state.value}",
                        key=f"order_{row['id']}_{next_state.value}",
                    ):
                        _transition_order(row["id"], next_state)
                        st.rerun()


def _render_expenses() -> None:
    st.title("Gastos")
    expenses = _load_expense_rows()
    total_amount = sum((row["monto_total"] for row in expenses), Decimal("0.00"))
    metric_cols = st.columns(3)
    metric_cols[0].metric("Tickets", len(expenses))
    metric_cols[1].metric("Monto total", _money_text(total_amount))
    metric_cols[2].metric(
        "Ticket promedio",
        _money_text(total_amount / Decimal(len(expenses)) if expenses else Decimal("0")),
    )

    with st.expander("Nuevo gasto", expanded=False):
        _render_expense_form()

    if not expenses:
        st.info("Todavia no hay gastos cargados.")
        return

    for row in expenses:
        with st.container(border=True):
            cols = st.columns([1.1, 1, 2.2, 1.2, 1])
            cols[0].markdown(f"**{row['codigo']}**")
            cols[1].write(row["fecha"])
            cols[2].write(row["lugar"])
            cols[3].write(_money_text(row["monto_total"]))
            if cols[4].button("Ver detalles", key=f"expense_detail_{row['id']}", use_container_width=True):
                st.session_state.selected_expense_id = row["id"]
                _show_expense_detail(row["id"])


def _render_catalog() -> None:
    st.title("Catalogo")
    categories, product_rows = _load_catalog_rows()
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
            _render_product_category_editor(product_rows)


def _render_promotions() -> None:
    st.title("Promos")
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
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    else:
        st.warning("Borrar registros puede afectar relaciones. Usar solo para correcciones controladas.")
        if st.button("Borrar registro", use_container_width=True):
            try:
                with Session(engine) as session:
                    AdminCrudService(session).delete_record(table_name, int(record_id or 0), _current_user())
                st.success("Registro borrado.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


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
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if cols[1].button("Quitar logo", disabled=not logo_url):
            _write_app_config(BRAND_LOGO_CONFIG_KEY, "")
            st.success("Logo eliminado.")
            st.rerun()


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
        with Session(engine) as session:
            category = session.get(Categoria, selected.id)
            if category is None:
                st.error("Categoria inexistente.")
                return
            category.nombre = nombre.strip()
            category.descripcion_publica = descripcion.strip() or None
            category.orden = int(orden)
            category.visible_cliente = visible
            category.activa = activa
            session.add(category)
            session.commit()
        st.success("Categoria guardada.")
        st.rerun()
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
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if upload_cols[1].button("Quitar foto", key=f"delete_category_image_{selected.id}"):
        with Session(engine) as session:
            category = session.get(Categoria, selected.id)
            if category is not None:
                category.foto_url = None
                session.add(category)
                session.commit()
        st.success("Foto de categoria eliminada.")
        st.rerun()


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
        submitted = st.form_submit_button("Guardar producto", use_container_width=True)
    if submitted:
        with Session(engine) as session:
            relation = session.get(ProductoCategoria, int(selected["relation_id"]))
            if relation is None:
                st.error("Relacion inexistente.")
                return
            relation.precio = Decimal(str(precio)).quantize(Decimal("0.01"))
            relation.descripcion_publica = descripcion.strip().upper() or None
            relation.orden = int(orden)
            relation.visible = visible
            relation.destacado = destacado
            relation.activo = activo
            session.add(relation)
            session.commit()
        st.success("Producto actualizado.")
        st.rerun()
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
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if upload_cols[1].button("Quitar foto", key=f"delete_product_image_{selected['relation_id']}"):
        with Session(engine) as session:
            relation = session.get(ProductoCategoria, int(selected["relation_id"]))
            if relation is not None:
                relation.foto_url = None
                session.add(relation)
                session.commit()
        st.success("Foto de producto eliminada.")
        st.rerun()


def _render_promotion_editor(promos: list[Promocion], products: list[Producto]) -> None:
    promo_options = {"Nueva promo": None}
    promo_options.update({f"{promo.id} | {promo.nombre}": promo for promo in promos})
    selected_label = st.selectbox("Promo", list(promo_options))
    selected = promo_options[selected_label]
    product_options = {f"{product.id} | {product.nombre}": product.id for product in products}
    selected_product_labels: list[str] = []
    if selected is not None:
        with Session(engine) as session:
            links = session.exec(select(PromocionProducto).where(PromocionProducto.promocion_id == selected.id)).all()
        linked_product_ids = {link.producto_id for link in links}
        selected_product_labels = [
            label for label, product_id in product_options.items() if product_id in linked_product_ids
        ]

    with st.form("promotion_editor"):
        codigo = st.text_input("Codigo", value=selected.codigo if selected else "")
        nombre = st.text_input("Nombre", value=selected.nombre if selected else "")
        cantidad_minima = st.number_input(
            "Cantidad minima",
            min_value=1,
            value=int(selected.cantidad_minima) if selected else 2,
            step=1,
        )
        precio_unitario = st.number_input(
            "Precio unitario promocional",
            min_value=0.0,
            value=float(selected.precio_unitario_promocional) if selected else 0.0,
            step=100.0,
        )
        precio_total_default = float(selected.precio_total_promocional) if selected and selected.precio_total_promocional else 0.0
        precio_total = st.number_input("Precio total del paquete", min_value=0.0, value=precio_total_default, step=100.0)
        activa = st.checkbox("Activa", value=bool(selected.activa) if selected else True)
        chosen_products = st.multiselect(
            "Productos elegibles",
            list(product_options),
            default=selected_product_labels,
        )
        submitted = st.form_submit_button("Guardar promo", use_container_width=True)
    if submitted:
        _save_promotion(
            promo_id=selected.id if selected else None,
            codigo=codigo,
            nombre=nombre,
            cantidad_minima=int(cantidad_minima),
            precio_unitario=Decimal(str(precio_unitario)).quantize(Decimal("0.01")),
            precio_total=Decimal(str(precio_total)).quantize(Decimal("0.01")) if precio_total else None,
            activa=activa,
            product_ids=[product_options[label] for label in chosen_products],
        )
        st.rerun()


def _render_expense_form() -> None:
    st.caption("Carga un ticket completo: fecha y lugar una sola vez, luego agrega todos los items comprados.")
    header_cols = st.columns([1, 2])
    fecha = header_cols[0].date_input("Fecha", key="expense_ticket_date")
    lugar = header_cols[1].text_input("Lugar", key="expense_ticket_place")

    with st.form("expense_ticket_item_form", clear_on_submit=True):
        motivo = st.text_input("Motivo")
        marca = st.text_input("Marca")
        descripcion = st.text_input("Descripcion")
        form_cols = st.columns(3)
        cantidad = form_cols[0].number_input("Cantidad", min_value=0.001, value=1.0, step=1.0)
        unidad = form_cols[1].text_input("Unidad", value="KG")
        precio = form_cols[2].number_input("Precio unitario", min_value=0.0, value=0.0, step=100.0)
        add_item = st.form_submit_button("Agregar item", use_container_width=True)
    if add_item:
        added = _add_expense_ticket_item(
            motivo=motivo,
            marca=marca,
            descripcion=descripcion,
            cantidad=Decimal(str(cantidad)),
            unidad=unidad,
            precio=Decimal(str(precio)),
        )
        if added:
            st.rerun()

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
                            )
                            for item in st.session_state.expense_ticket_items
                        ],
                    ),
                    _current_user(),
                )
            st.session_state.expense_ticket_items = []
            st.success(f"Gasto {expense.codigo} guardado.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if action_cols[1].button("Limpiar ticket", use_container_width=True, disabled=not st.session_state.expense_ticket_items):
        st.session_state.expense_ticket_items = []
        st.rerun()


def _add_expense_ticket_item(
    *,
    motivo: str,
    marca: str,
    descripcion: str,
    cantidad: Decimal,
    unidad: str,
    precio: Decimal,
) -> bool:
    if not motivo.strip() or not marca.strip() or not unidad.strip():
        st.warning("Motivo, marca y unidad son obligatorios para agregar un item.")
        return False
    if cantidad <= 0:
        st.warning("La cantidad debe ser mayor a cero.")
        return False
    if precio < 0:
        st.warning("El precio no puede ser negativo.")
        return False
    subtotal = (cantidad * precio).quantize(Decimal("0.01"))
    st.session_state.expense_ticket_items = [
        *st.session_state.expense_ticket_items,
        {
            "motivo": motivo.strip().upper(),
            "marca": marca.strip().upper(),
            "descripcion": descripcion.strip().upper(),
            "cantidad": str(cantidad),
            "unidad": unidad.strip().upper(),
            "precio_unitario": str(precio),
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
        st.rerun()


def _render_placeholder(title: str) -> None:
    st.title(title)
    st.info("Seccion preparada. Se conectara a los servicios compartidos en la siguiente fase.")


def _load_order_rows() -> list[dict[str, Any]]:
    with Session(engine) as session:
        pedidos = session.exec(select(Pedido).order_by(Pedido.created_at.desc())).all()
        clientes = {cliente.id: cliente for cliente in session.exec(select(Cliente)).all()}
    return [
        {
            "id": pedido.id or 0,
            "codigo": pedido.codigo,
            "fecha_entrega": pedido.fecha_entrega.isoformat(),
            "cliente": clientes[pedido.cliente_id].nombre_apellido if pedido.cliente_id in clientes else "",
            "telefono": clientes[pedido.cliente_id].telefono if pedido.cliente_id in clientes else "",
            "estado": pedido.estado.value,
            "monto_total": pedido.monto_total,
        }
        for pedido in pedidos
    ]


def _load_expense_rows() -> list[dict[str, Any]]:
    with Session(engine) as session:
        gastos = session.exec(select(Gasto).order_by(Gasto.fecha.desc(), Gasto.id.desc())).all()
    return [
        {
            "id": gasto.id or 0,
            "codigo": gasto.codigo,
            "fecha": gasto.fecha.isoformat(),
            "lugar": gasto.lugar_texto,
            "monto_total": gasto.monto_total,
        }
        for gasto in gastos
    ]


def _load_catalog_rows() -> tuple[list[Categoria], list[dict[str, Any]]]:
    with Session(engine) as session:
        categories = session.exec(select(Categoria).order_by(Categoria.orden, Categoria.nombre)).all()
        products = {product.id: product for product in session.exec(select(Producto)).all()}
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
                "destacado": relation.destacado,
                "activo": relation.activo,
            }
        )
    return categories, rows


def _load_promotion_rows() -> tuple[list[Promocion], list[dict[str, Any]], list[Producto]]:
    with Session(engine) as session:
        promos = session.exec(select(Promocion).order_by(Promocion.nombre)).all()
        products = session.exec(select(Producto).order_by(Producto.nombre)).all()
        product_by_id = {product.id: product for product in products}
        links = session.exec(select(PromocionProducto)).all()
    product_names_by_promo: dict[int, list[str]] = {}
    for link in links:
        product = product_by_id.get(link.producto_id)
        if product:
            product_names_by_promo.setdefault(link.promocion_id, []).append(product.nombre)
    rows = [
        {
            "id": promo.id,
            "codigo": promo.codigo,
            "nombre": promo.nombre,
            "cantidad_minima": promo.cantidad_minima,
            "precio_unitario": _money_text(promo.precio_unitario_promocional),
            "precio_total": _money_text(promo.precio_total_promocional) if promo.precio_total_promocional else "",
            "activa": promo.activa,
            "productos": ", ".join(product_names_by_promo.get(promo.id or 0, [])),
        }
        for promo in promos
    ]
    return promos, rows, products


def _load_admin_records(table_name: str) -> list[dict[str, Any]]:
    try:
        with Session(engine) as session:
            return AdminCrudService(session).list_records(table_name, _current_user())
    except Exception as exc:
        st.error(str(exc))
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
) -> None:
    if not codigo.strip() or not nombre.strip():
        st.error("Codigo y nombre son obligatorios.")
        return
    if not product_ids:
        st.error("Selecciona al menos un producto elegible.")
        return
    with Session(engine) as session:
        if promo_id is None:
            promo = Promocion(
                codigo=codigo.strip().upper(),
                nombre=nombre.strip().upper(),
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
                return
            promo.codigo = codigo.strip().upper()
            promo.nombre = nombre.strip().upper()
            promo.cantidad_minima = cantidad_minima
            promo.precio_unitario_promocional = precio_unitario
            promo.precio_total_promocional = precio_total
            promo.activa = activa
            session.add(promo)
            session.flush()
            existing_links = session.exec(select(PromocionProducto).where(PromocionProducto.promocion_id == promo.id)).all()
            for link in existing_links:
                session.delete(link)
        for product_id in dict.fromkeys(product_ids):
            session.add(PromocionProducto(promocion_id=promo.id or 0, producto_id=product_id))
        session.commit()
    st.success("Promo guardada.")


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


def _show_order_detail(order_id: int) -> None:
    if hasattr(st, "dialog"):
        @st.dialog("Detalle del pedido")
        def dialog() -> None:
            _render_order_detail(order_id)

        dialog()
    else:
        with st.expander("Detalle del pedido", expanded=True):
            _render_order_detail(order_id)


def _show_expense_detail(expense_id: int) -> None:
    if hasattr(st, "dialog"):
        @st.dialog("Detalle del gasto")
        def dialog() -> None:
            _render_expense_detail(expense_id)

        dialog()
    else:
        with st.expander("Detalle del gasto", expanded=True):
            _render_expense_detail(expense_id)


def _render_order_detail(order_id: int) -> None:
    with Session(engine) as session:
        pedido = session.get(Pedido, order_id)
        if pedido is None:
            st.error("Pedido inexistente.")
            return
        cliente = session.get(Cliente, pedido.cliente_id)
        zona = session.get(ZonaEnvio, pedido.zona_envio_id) if pedido.zona_envio_id else None
        items = session.exec(select(PedidoItem).where(PedidoItem.pedido_id == order_id)).all()
        products = {product.id: product for product in session.exec(select(Producto)).all()}
        categories = {category.id: category for category in session.exec(select(Categoria)).all()}

    st.subheader(pedido.codigo)
    st.write(f"Cliente: {cliente.nombre_apellido if cliente else ''}")
    st.write(f"Telefono: {cliente.telefono if cliente else ''}")
    st.write(f"Entrega: {pedido.fecha_entrega.isoformat()}")
    st.write(f"Direccion: {pedido.direccion_delivery}")
    st.write(f"Zona: {zona.nombre if zona else 'Sin envio'}")
    st.write(f"Estado: {pedido.estado.value}")
    detail_rows = []
    for item in items:
        product = products.get(item.producto_id)
        combo = products.get(item.producto_combo_id) if item.producto_combo_id else None
        category = categories.get(item.categoria_venta_id)
        detail_rows.append(
            {
                "producto": product.nombre if product else str(item.producto_id),
                "combo": combo.nombre if combo else "",
                "categoria": category.nombre if category else "",
                "cantidad": item.cantidad,
                "precio_unitario": _money_text(item.precio_unitario),
                "subtotal": _money_text(item.subtotal),
            }
        )
    st.dataframe(detail_rows, hide_index=True, use_container_width=True)
    st.write(f"Envio: {_money_text(pedido.costo_envio)}")
    st.write(f"Total: {_money_text(pedido.monto_total)}")


def _render_expense_detail(expense_id: int) -> None:
    with Session(engine) as session:
        gasto = session.get(Gasto, expense_id)
        if gasto is None:
            st.error("Gasto inexistente.")
            return
        details = session.exec(select(GastoDetalle).where(GastoDetalle.gasto_id == expense_id)).all()
        motivos = {motivo.id: motivo for motivo in session.exec(select(MotivoGasto)).all()}
        marcas = {marca.id: marca for marca in session.exec(select(Marca)).all()}

    st.subheader(gasto.codigo)
    st.write(f"Fecha: {gasto.fecha.isoformat()}")
    st.write(f"Lugar: {gasto.lugar_texto}")
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


def _transition_order(order_id: int, next_state: EstadoPedido) -> None:
    try:
        with Session(engine) as session:
            OrderService(session).transition_order(order_id, next_state, _current_user())
        st.success("Estado actualizado.")
    except DomainError as exc:
        st.error(str(exc))


def _current_user() -> UsuarioRead:
    role = RolUsuario(st.session_state.role or RolUsuario.DUENO.value)
    return UsuarioRead(
        id=int(st.session_state.user_id),
        username=str(st.session_state.username),
        rol=role,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _is_authenticated() -> bool:
    return int(st.session_state.get("user_id") or 0) > 0


def _logout() -> None:
    st.session_state.user_id = 0
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.auth_message = ""


def _money_text(value: Decimal | str | int | float) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return f"$ {amount:.2f}".replace(".", ",")
