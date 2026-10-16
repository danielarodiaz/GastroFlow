from __future__ import annotations

import json
import mimetypes
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

import streamlit as st
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.domain.enums import EstadoPedido, RolUsuario, TipoPromocion, UnidadVenta
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
    PromocionCategoria,
    PromocionItem,
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
from gastroflow.services.promotions import configure_promotion

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

    _render_production_summary(orders)

    if not orders:
        st.info("Todavia no hay pedidos.")
        return

    for row in orders:
        with st.container(border=True):
            cols = st.columns([1.1, 1.4, 1.2, 1.2, 1.1, 1])
            cols[0].markdown(f"**{row['codigo']}**")
            cols[1].write(row["cliente"])
            cols[2].write(f"{row['fecha_entrega']} · {row['horario_entrega']}")
            cols[3].markdown(_state_badge(row["estado"]), unsafe_allow_html=True)
            cols[4].write(_money_text(row["monto_total"]))
            if cols[5].button("Ver detalles", key=f"order_detail_{row['id']}", use_container_width=True):
                st.session_state.selected_order_id = row["id"]
                _show_order_detail(row)

            next_states = valid_next_states(EstadoPedido(row["estado"]))
            if next_states:
                action_cols = st.columns(len(next_states))
                for index, next_state in enumerate(sorted(next_states, key=lambda item: item.value)):
                    if action_cols[index].button(
                        _transition_label(next_state),
                        key=f"order_{row['id']}_{next_state.value}",
                        type="primary" if next_state != EstadoPedido.CANCELADO else "secondary",
                        use_container_width=True,
                    ):
                        _transition_order(row["id"], next_state)
                        _load_order_rows.clear()
                        st.rerun()


def _render_production_summary(orders: list[dict[str, Any]]) -> None:
    summary = _build_production_summary(orders)
    st.subheader("Produccion pendiente por fecha de entrega")
    st.caption("Incluye pedidos pendientes y en proceso. No cuenta pedidos entregados ni cancelados.")
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
                relation.visible = visible
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
        relations = session.exec(select(ProductoCategoria).where(ProductoCategoria.activo == True)).all()
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

    with st.form("expense_ticket_item_form", clear_on_submit=True):
        motivo = st.text_input("Motivo")
        marca = st.text_input("Marca")
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


def _add_expense_ticket_item(
    *,
    motivo: str,
    marca: str,
    descripcion: str,
    cantidad: Decimal,
    unidad: str,
    total_item: Decimal,
) -> bool:
    if not motivo.strip() or not marca.strip() or not unidad.strip():
        st.warning("Motivo, marca y unidad son obligatorios para agregar un item.")
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


@st.cache_data(ttl=15, show_spinner=False)
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

    rows_by_id: dict[int, dict[str, Any]] = {}
    for pedido, cliente, zona in order_rows:
        order_id = pedido.id or 0
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
            "direccion": pedido.direccion_delivery,
            "zona": zona.nombre if zona else "Sin envio",
            "costo_envio": pedido.costo_envio,
            "monto_total": pedido.monto_total,
            "observaciones": pedido.observaciones or "",
            "items": [],
        }
    for item, product, combo, category in detail_rows:
        order = rows_by_id.get(item.pedido_id)
        if order is None:
            continue
        order["items"].append(
            {
                "producto": product.nombre,
                "combo": combo.nombre if combo else "",
                "categoria": category.nombre,
                "cantidad": item.cantidad,
                "precio_unitario": _money_text(item.precio_unitario),
                "subtotal": _money_text(item.subtotal),
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
            "monto_total": gasto.monto_total,
        }
        for gasto in gastos
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
    st.write(f"Telefono: {order['telefono']}")
    st.write(f"Entrega: {order['fecha_entrega']} a las {order['horario_entrega']}")
    st.write(f"Direccion: {order['direccion']}")
    st.write(f"Zona: {order['zona']}")
    st.markdown(f"Estado: {_state_badge(order['estado'])}", unsafe_allow_html=True)
    st.dataframe(order["items"], hide_index=True, use_container_width=True)
    if order["observaciones"]:
        st.write(f"Observaciones: {order['observaciones']}")
    st.write(f"Envio: {_money_text(order['costo_envio'])}")
    st.write(f"Total: {_money_text(order['monto_total'])}")


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
    st.write(f"Fecha: {_date_text(gasto.fecha)}")
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


def _is_authenticated() -> bool:
    return int(st.session_state.get("user_id") or 0) > 0


def _is_admin() -> bool:
    return _is_authenticated() and st.session_state.get("role") == RolUsuario.ADMIN.value


def _logout() -> None:
    st.session_state.user_id = 0
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.auth_message = ""


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
    excluded_states = {EstadoPedido.ENTREGADO.value, EstadoPedido.CANCELADO.value}
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
