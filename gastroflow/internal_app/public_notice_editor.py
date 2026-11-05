"""Admin editor for public notices (requires catalog permissions)."""

from datetime import datetime

import streamlit as st
from sqlmodel import Session, select

from gastroflow.domain.errors import ValidationError
from gastroflow.models import AvisoPublico
from gastroflow.services.public_notices import argentina_now, validate_notice


@st.fragment
def render_public_notice_editor(engine) -> None:
    with st.expander("Avisos y campañas", expanded=False):
        if st.session_state.pop("public_notice_saved", False):
            st.success("Aviso guardado. Las nuevas visitas usarán esta configuración.")
        st.caption("Ventanas al ingresar: primero avisos informativos, después ofertas. Horarios de Argentina. Cerrar un aviso no desactiva su restricción.")
        try:
            with Session(engine) as session:
                notices = session.exec(select(AvisoPublico).order_by(AvisoPublico.id.desc())).all()
        except Exception:
            st.error("No se pudieron cargar los avisos. Verificá la conexión y que esté aplicada la migración 0017_public_notices.")
            return
        now = argentina_now()
        if notices:
            st.dataframe([{
                "ID": row.id, "Título": row.titulo, "Tipo": row.tipo,
                "Estado": "Deshabilitado" if not row.habilitado else (
                    "Programado" if row.inicio > now else "Finalizado" if row.fin and row.fin <= now else "Vigente"
                ),
                "Acción": row.accion, "Prioridad": row.prioridad,
                "Desde": row.inicio, "Hasta": row.fin,
            } for row in notices], hide_index=True, use_container_width=True)
        selected_id = st.selectbox("Aviso a configurar", [0, *[row.id for row in notices]],
            format_func=lambda value: "Crear aviso" if value == 0 else next(f"{row.id} · {row.titulo}" for row in notices if row.id == value),
            key="public_notice_selected")
        selected = next((row for row in notices if row.id == selected_id), None)
        start = selected.inicio if selected else now.replace(second=0, microsecond=0)
        end = selected.fin if selected else None
        with st.form(f"public_notice_form_{selected_id}"):
            title = st.text_input("Título del aviso", value=selected.titulo if selected else "", max_chars=160)
            message = st.text_area("Mensaje", value=selected.mensaje if selected else "", max_chars=4000, height=150)
            kind = st.selectbox("Tipo de mensaje", ["informativo", "oferta"],
                index=1 if selected and selected.tipo == "oferta" else 0,
                format_func=lambda value: "Aviso informativo" if value == "informativo" else "Oferta")
            action = st.selectbox("Acción asociada", ["ninguna", "suspender_envios"],
                index=1 if selected and selected.accion == "suspender_envios" else 0,
                format_func=lambda value: "Solo mostrar mensaje" if value == "ninguna" else "Suspender envíos (solo retiro)")
            st.caption("Las ofertas comunican precios; los descuentos se configuran en Promos. La suspensión se evalúa por la fecha y hora de entrega del pedido.")
            enabled = st.checkbox("Aviso habilitado", value=selected.habilitado if selected else True)
            priority = st.number_input("Prioridad (menor número aparece primero dentro del mismo tipo)",
                value=selected.prioridad if selected else 0, step=1)
            cols = st.columns(2)
            start_date = cols[0].date_input("Fecha de inicio", value=start.date())
            start_time = cols[1].time_input("Hora de inicio", value=start.time())
            no_end = st.checkbox("Sin fecha de fin", value=end is None)
            cols = st.columns(2)
            end_date = cols[0].date_input("Fecha de fin", value=(end or start).date())
            end_time = cols[1].time_input("Hora de fin (desde este momento deja de aplicar)", value=(end or start).time())
            save = st.form_submit_button("Guardar aviso")
        if save:
            try:
                row = AvisoPublico(id=selected_id or None, titulo=title.strip(), mensaje=message.strip(),
                    tipo=kind, accion=action, habilitado=enabled, prioridad=int(priority),
                    inicio=datetime.combine(start_date, start_time),
                    fin=None if no_end else datetime.combine(end_date, end_time))
                validate_notice(row)
                with Session(engine) as session:
                    session.merge(row)
                    session.commit()
                st.session_state.public_notice_saved = True
                st.rerun()
            except ValidationError as exc:
                st.error(str(exc))
            except Exception:
                st.error("No se pudo guardar el aviso. Revisá la conexión e intentá nuevamente.")
        st.markdown("**Vista previa**")
        st.markdown("**" + (title or "Título del aviso") + "**")
        st.text(message or "El mensaje aparecerá aquí.")
        st.caption("Cada ventana incluye un botón Cerrar; al cerrarla se muestra el siguiente aviso vigente.")
