# Análisis técnico de GastroFlow

**Alcance y método.** Análisis estático del repositorio al 6 de noviembre de 2026: código Python, configuración, modelos SQLModel, migraciones Alembic, scripts, pruebas existentes y documentación. No se ejecutaron pruebas ni se modificaron archivos de aplicación. Los archivos nuevos de esta entrega son este informe y los tres diagramas Mermaid. Las pruebas existentes se leyeron como evidencia de casos cubiertos, no se tomaron como prueba de que el sistema remoto esté desplegado.

## 1. Visión general del sistema

GastroFlow gestiona el ciclo operativo de un comercio gastronómico pequeño: el cliente consulta un catálogo y envía un pedido; el personal lo procesa y registra compras/gastos; usuarios autorizados ajustan catálogo, promociones, zonas, agregados, marca y avisos. La configuración inicial y los recursos del repositorio están orientados a una pizzería, aunque el catálogo y las reglas se modelan de forma más general.

Hay dos interfaces que comparten modelos, servicios y base relacional:

- **Pública:** aplicación Reflex montada desde `gastroflow/public_app.py`, con catálogo, detalle de productos, carrito, entrega/retiro, pago y confirmación. `gastroflow/states/public_order_state.py` mantiene estado reactivo y delega el guardado/precio en `OrderService`; `gastroflow/public_ui.py` dibuja las vistas. No requiere inicio de sesión.
- **Interna:** aplicación Streamlit montada desde `streamlit_deploy/streamlit_app.py` (delegación) o `streamlit_app.py`, cuya lógica está en `gastroflow/internal_app/streamlit_app.py`. Ofrece acceso interno, pedidos y transiciones, edición de pedido, gastos por ticket, catálogo, promociones, usuarios, permisos, zonas, agregados, marca e imágenes, avisos/campañas.

El núcleo común vive en `gastroflow/models/`, `services/`, `domain/`, `data/`, `security/` y `config/`. Ambas UIs acceden directamente al mismo PostgreSQL mediante SQLModel/SQLAlchemy, sin una API HTTP REST propia entre ellas. La aplicación Reflex sí usa el mecanismo reactivo de Reflex entre navegador y backend; el Streamlit ejecuta callbacks Python del servidor. Las fotos y otros medios se guardan como archivos en disco local o se suben desde servidor a Supabase Storage; en DB quedan rutas/URLs. Los avisos se leen de la base y los enlaces de WhatsApp se construyen para que el cliente continúe manualmente la conversación.

**Flujo general comprobable:** (1) el arranque carga settings desde entorno/`.env`, crea el engine; (2) Alembic prepara el esquema y los scripts pueden inicializar datos/usuarios; (3) la interfaz pública obtiene categorías, productos, agregados, zonas y combos visibles; (4) al confirmar vuelve a leer catálogo/reglas desde DB, valida y calcula precios en `OrderService`, crea/reutiliza cliente y persiste pedido e ítems; (5) Streamlit vuelve a consultar las mismas tablas, permite gestionar el pedido y sus estados; (6) gastos y configuración se guardan por sus servicios; (7) imágenes usan el backend elegido por configuración. No encontré una API de pagos ni confirmación automática con el proveedor de WhatsApp.

## 2. Stack tecnológico

| Tecnología | Uso comprobado |
|---|---|
| Python 3.12 (Dockerfiles) | Backend, servicios, estados, scripts y configuración. |
| Reflex 0.8.x | UI pública reactiva y, en `gastroflow/app.py`, UI interna Reflex heredada/alternativa. `rxconfig.py` fija Tailwind v3 y el módulo de entrada seleccionable por `REFLEX_APP_MODULE_IMPORT`. |
| Streamlit 1.36+ | Interfaz interna actual separada en `gastroflow/internal_app/streamlit_app.py`. `streamlit_deploy/requirements.txt` fija dependencias de esa publicación. |
| SQLModel, SQLAlchemy, Pydantic | Modelos tipados, consultas/ORM, validación y sesiones. El driver PostgreSQL es psycopg 3. |
| PostgreSQL 16 | Base relacional local en Compose; el despliegue documentado apunta a PostgreSQL de Supabase. No se verificó una instancia externa. |
| Alembic | 18 revisiones de esquema en `alembic/versions/`, desde `0001_initial_schema` hasta `0018_notice_rich_text`. |
| bcrypt | Hash y verificación de passwords en `gastroflow/security/passwords.py`. |
| Docker / Compose | Imagen Python y entorno local app + PostgreSQL. `Dockerfile.public` construye frontend público Reflex. |
| Tailwind CSS v3 | Plugin/configuración de tema para Reflex en `rxconfig.py`. |
| OpenPyXL | Exportación/lectura de Excel y herramientas de importación. Node `.mjs` construye workbook de gastos. |
| Tesseract + pytesseract, OpenCV, PyMuPDF | Lectura local OCR de comprobantes (imagen/PDF); `packages.txt` instala ejecutables/datos lingüísticos para el despliegue Streamlit. |
| Supabase Storage (opcional/configurable) | Subida de medios server-side por HTTP en `services/media_storage.py`; URL pública almacenada. Las instrucciones de despliegue lo proponen como backend cloud. |
| Google Maps (configurado pero no implementado de punta a punta) | Hay setting `GOOGLE_MAPS_API_KEY` y campos de latitud/longitud. El código inspeccionado no acredita geocodificación o selector integrado. |
| Azure Document Intelligence (integración opcional en código) | `AzureDocumentReader` y settings existen. README dice que no se usa por defecto; el motor por defecto es Tesseract. |
| WhatsApp (`wa.me`) | Enlace URL preformateado para continuación manual; no es API de mensajería ni evidencia de mensaje enviado. |

La razón de varias elecciones puede inferirse del código: Decimal/Numeric preserva importes a centavos, snapshots conservan precios históricos, los servicios concentran reglas compartidas por ambas UIs y los códigos de negocio usan secuencias PostgreSQL. Son inferencias consistentes con implementación y documentación, no métricas de rendimiento.

## 3. Arquitectura general

### Capas y responsabilidades

1. **Presentación:** `public_ui.py` + `PublicOrderState`; `internal_app/streamlit_app.py`; existe además `app.py`/`states/app_state.py` como frontend Reflex interno alternativo. Las UIs coordinan formularios, filtros, vistas y mensajes.
2. **Casos de uso / servicios:** `OrderService`, `ExpenseService`, `AuthService`, `AdminManagementService`, `AdminCrudService`, servicios de avisos/promos/documentos. Reciben sesiones SQLModel y aplican reglas/commit.
3. **Dominio:** `domain/enums.py`, `order_state.py`, `errors.py`; estados, permisos, tipos y errores de negocio.
4. **Persistencia:** modelos de `models/`, engine/sesiones en `data/database.py`, PostgreSQL; migraciones versionadas en Alembic.
5. **Adaptadores:** Supabase Storage, OCR local y lector Azure disponible, URL de WhatsApp, importación/exportación Excel. No se identifica capa de API REST o cola de trabajos.

### Comunicación, validación y errores

Las dos aplicaciones instancian `Session(engine)` y llaman servicios compartidos; no existe un servidor API independiente. En Reflex, eventos de `rx.State` se ejecutan en backend y las llamadas a DB se desvían a threads en algunos flujos (`asyncio.to_thread` en estado público) para no bloquear el bucle async. Streamlit maneja formularios/callbacks en su proceso. La validación está en las entradas del servicio y restricciones/unique/FK/check del modelo/migración; parte de la validación de UX también se hace en estados/UI. `DomainError` se divide en autenticación, autorización, conflicto y validación; UIs muestran mensajes amigables y capturan errores inesperados. No hay un formato uniforme de error HTTP porque no hay API propia.

### Autenticación y archivos

La tienda pública no autentica. La app interna verifica credenciales con `AuthService`, mantiene identidad en `st.session_state` y persiste una credencial firmada HMAC en query param con expiración (`_create_auth_token`, `_decode_auth_token`); al restaurarla vuelve a consultar que el usuario siga activo. `APP_SECRET_KEY` firma el token. Autorización por roles/permisos se aplica en servicios para acciones sensibles. Para archivos, `save_media_bytes` selecciona disco `uploaded_files/` o Supabase; para OCR de comprobantes, el código carga el archivo, lee QR/OCR local, prepara propuesta editable y confirma el documento/gasto tras revisión.

Diagrama de contexto/componentes: [architecture.mmd](architecture.mmd).

## 4. Análisis del frontend

### Estructura y navegación

- `gastroflow/public_ui.py`: navegación pública, marca, catálogo por categorías, tarjetas de producto, combinaciones, agregados, carrito, checkout, avisos y `/ping`.
- `gastroflow/states/public_order_state.py`: estado público: carga de catálogo/avisos, selección, cantidades, carrito, entrega, pago, validación de fecha/hora y envío; `submit_order` ejecuta confirmación y presenta resultado/link de WhatsApp.
- `gastroflow/components/delivery_input.py`, `delivery_mask.js`, `public_interactions.py`, `public_interactions.js`: componentes JS de máscara/formato y pequeñas interacciones del formulario.
- `gastroflow/internal_app/streamlit_app.py`: login y navegación lateral por módulos; pedidos (abiertos, pendientes, producción, entregados), detalle/edición, gastos por producto o ticket, captura de comprobantes, catálogo, promos, administración y avisos.
- `gastroflow/internal_app/public_notice_editor.py`, `rich_text.py`, `rich_text_editor/index.html`: editor de texto enriquecido de avisos. El HTML se filtra en `services/notice_formatting.py` antes de guardarse/mostrarse.
- `gastroflow/app.py` + `states/app_state.py`: versión interna construida también con Reflex (rutas `/login`, `/pedidos`, `/gastos`, `/catalogo-admin`, `/promociones`, `/admin`, entre otras). `Dockerfile`/Compose apuntan a ella por defecto, mientras que la guía de despliegue divide público e interno. Debe entenderse como entrypoint alternativo/legado disponible; no es el entrypoint indicado por la guía de Streamlit.

### Estado, formularios, UX

Reflex maneja estado servidor en clases `rx.State`, expresado como vars/eventos y sincronizado con navegador. El carrito guarda selecciones y subtotales de presentación, pero la confirmación vuelve a tarificar desde DB; no confía en el precio mostrado. Los formularios normalizan teléfono, fecha/hora y dinero, y verifican nombre, dirección, pago, disponibilidad y coherencia de entrega. Agregar al carrito valida categoría, combo, cantidad y agregados. Streamlit usa `st.session_state` para login, filtros, formularios y editor; varias tablas/cálculos auxiliares se forman en funciones `_load_*` y `_render_*` del mismo módulo. Esto ofrece un flujo directo, aunque el archivo Streamlit es grande y mezcla UI, consulta y parte de lógica de edición.

La caché del catálogo/brand dura 30 segundos por proceso (`services/public_catalog.py`); precios del checkout se leen en vivo. Hay lazy loading de imágenes según documentación. No se observó analítica de uso ni pruebas de accesibilidad automatizadas.

## 5. Análisis del backend

### Organización y funciones principales

- `services/orders.py`: `OrderService.create_public_order`, `transition_order`, upsert cliente por teléfono, tarifa de envío, combos, agregados, precios por categoría, mayorista, promociones, pagos y total. `normalize_phone` normaliza número argentino.
- `services/expenses.py`: `ExpenseService` crea/actualiza/elimina ticket y detalles; calcula total, reutiliza/crea motivo y marca de forma case-insensitive y valida cantidades/precios.
- `services/auth.py`: alta, primer admin, login, lectura de usuario, rol y permiso.
- `services/admin_management.py`: CRUD con bajas reversibles y auditoría para zonas, categorías, agregados y usuarios; permisos `CONFIGURACION`/`USUARIOS`.
- `services/admin_crud.py`: CRUD genérico con whitelist (`CRUD_TABLES`), hashing de password y exclusión de `password_hash` en serialización.
- `services/promotions.py` y `promotion_packages.py`: validación de alcance/categorías/componentes y asignación de paquetes completos al menor costo aplicable sin apilar descuentos sobre las mismas líneas.
- `services/combo_rules.py`: garantiza 10 combinaciones de mitad y mitad para cinco sabores configurados.
- `services/public_notices.py`: ventana horaria Argentina, orden de prioridad, suspensión de envíos y reglas de aviso.
- `services/expense_documents.py`: contratos de lectura, análisis de QR, parser de ticket/transferencia, Tesseract, y lector Azure opcional.
- `services/media_storage.py`: disco local/Supabase Storage; `services/brand_media.py` define clave de imagen de menú.
- `services/codes.py`: `nextval` sobre secuencias para `PED-*` y `GAS-*`.

No hay endpoints REST de negocio. El entrypoint Reflex es `gastroflow/public_app.py` para público (`/`, `/ping`) y `gastroflow/app.py` para la app Reflex con rutas internas. El entrypoint Streamlit es el archivo wrapper `streamlit_deploy/streamlit_app.py` o el raíz `streamlit_app.py`, ambos delegan en `internal_app.streamlit_app.main`.

### Reglas comprobadas

- `Pedido` captura snapshot de precio unitario/subtotal, categoría de venta, extras y envío; `monto_total` es calculado, no una cifra enviada por cliente.
- Pedido puede iniciar `PENDIENTE_CONFIRMACION` si lo determina la regla comercial; estados y transiciones son explícitos en `domain/order_state.py`. El dominio permite volver de pendiente a pedido además de pasar a proceso/cancelar.
- Combo requiere una regla para el par y aplica `MAYOR_VALOR`, `PROMEDIO` o `PRECIO_FIJO`.
- Servicio valida elegibilidad/alcance de promociones y categorías; la regla de paquetes se aplica para precio total de paquete, incluye reparto proporcional de centavos.
- Pagos aceptan transferencia, efectivo o mixto (`PedidoPago` contiene montos); la suma se valida frente al pedido en servicio.
- Suspensión configurada por aviso se vuelve a comprobar al guardar pedido en DB; retiro sigue disponible.
- Gastos persisten cabecera y filas de detalle, total agregado, datos de pago y, cuando corresponde, documento vinculado.
- La edición de pedidos en Streamlit registra snapshot antes/después y motivo en `pedido_revision` según el flujo `_update_order`.

## 6. Base de datos

### Motor, modelo y relaciones

Motor soportado/configurado: PostgreSQL, URL SQLAlchemy con `postgresql+psycopg`. `models/base.py` usa PK enteras autoincrementales, dinero `NUMERIC(12,2)`, cantidad `NUMERIC(12,3)`, coordenadas `NUMERIC(10,7)` y timestamps UTC. Algunos campos JSON usan JSONB (fotos de producto), otros JSON para permisos. El ERD se genera a partir de los modelos actuales, no de una instancia remota: [er_diagram.mmd](er_diagram.mmd).

Entidades: `usuario`, `cambio_administrativo`; `cliente`, `pedido`, `pedido_item`, `pedido_pago`, `pedido_item_agregado`, `pedido_revision`; `gasto`, `gasto_detalle`, `gasto_documento`; `categoria`, `producto`, `producto_categoria`, `promocion`, `promocion_producto`, `promocion_categoria`, `promocion_item`, `combo_regla`, `zona_envio`, `agregado`, `agregado_categoria`, `motivo_gasto`, `marca`, `app_config`, `aviso_publico`.

Relaciones destacadas: categoría y producto N:M por `producto_categoria` (precio/visibilidad/orden por contexto de venta); producto y categoría N:M para agregados/promos; pedido 1:N ítems/pagos/revisiones; ítem 1:N agregados; producto referencia dos veces desde ítem para mitad y mitad; gasto 1:N detalles/documentos; usuario puede ser autor de cambios/revisiones. `pedido.zona_envio_id` es nullable y `costo_envio` es snapshot. El campo cliente teléfono y códigos de negocio son únicos. `gasto_documento.contenido_sha256` es único. Reglas de promociones tienen unicidad compuesta y check de cantidad. `aviso_publico` checks de tipo, acción, ventana fin posterior al inicio y acción compatible con aviso informativo.

Los índices se declaran principalmente en columnas de búsqueda/foreign keys mediante `Field(index=True)`, además de índices únicos/constraints (username, códigos, teléfono, hash, relaciones únicas). No se observó una estrategia general documentada de índices de analítica; validar consultas reales antes de añadir índices.

### Migraciones

La cadena es `0001_initial_schema` … `0018_notice_rich_text` en `alembic/versions/`, configurada con `alembic.ini` y `alembic/env.py`. El esquema actual contiene ampliaciones posteriores (categorías-contexto, pedidos especiales, pagos parciales/agregados, historial de edición, documentos de gasto, bajas/permisos/auditoría, avisos y HTML seguro). El despliegue documentado ejecuta `python -m alembic upgrade head`; seeds separados están en `scripts/seed_catalog.py` y `scripts/seed_half_pizzas.py`. Los datos reales de un servidor no se pueden inferir de migraciones.

Diagrama ER: [er_diagram.mmd](er_diagram.mmd).

## 7. Flujos de negocio

Los diagramas de secuencia están en [business_flows.mmd](business_flows.mmd).

### Registro y autenticación

No hay registro público. El primer administrador se crea con `scripts/create_admin.py` o flujo de bootstrap; `AuthService.create_first_admin` rehúsa crear un segundo admin inicial. `hash_password` exige 8 caracteres mínimo y 72 bytes máximo (límite bcrypt), genera bcrypt. Login Streamlit normaliza username a mayúsculas, verifica password y usuario activo; crea token firmado con vencimiento en query param. Permisos efectivos se refrescan desde DB. `UsuarioRead` no lleva hash.

### Creación/confirmación de pedido

1. `PublicOrderState.load_catalog` obtiene producto-categoría activo/visible, reglas, agregados y zonas; avisos se cargan aparte.
2. Cliente selecciona producto, contexto de venta, combo y agregados; el UI calcula una vista provisional del total.
3. Checkout recopila contacto, fecha/hora, entrega/retiro, zona, dirección, instrucciones y forma(s) de pago. El código valida formato y datos obligatorios.
4. `submit_order` vuelve a construir inputs y ejecuta `OrderService.create_public_order` fuera del event loop. El servicio vuelve a cargar productos y reglas, verifica aviso de suspensión y combina precios actuales; no confía en importes del navegador.
5. Upsert cliente por teléfono normalizado, toma secuencia `PED`, construye pedido e ítems/pagos/agregados con snapshots, inicializa estado apropiado y confirma transacción.
6. La UI muestra el código/total y puede abrir enlace de WhatsApp. La apertura no confirma envío del mensaje. `submission_token` único permite evitar repetir la misma confirmación según el flujo del estado.

### Gestión y cambios de estado de pedidos

Streamlit `_load_order_rows` forma el listado y `_render_orders` presenta estados; `_transition_order` invoca `OrderService.transition_order`, que valida permiso y máquina de estados. Puede pasar de pedido a pendiente/proceso/cancelado; pendiente puede volver a pedido o avanzar/cancelarse; en proceso puede entregarse/cancelarse; terminales no avanzan. Edición más amplia usa `_update_order` y guarda revisión/auditoría con usuario, motivo y resúmenes anterior/nuevo. El estado de pago y los pagos parciales se muestran/editan según formulario.

### Catálogo, promociones y avisos

Los usuarios con permiso de catálogo editan asociación categoría-producto, precios por contexto, visibilidad, textos e imágenes. Admin Management administra zonas/categorías/agregados y usuarios, con auditoría y bajas reversibles. Promociones se configuran con categorías, productos/componentes y criterios; `configure_promotion` verifica que categorías activas y productos elegibles coincidan. Al confirmar pedido se recalcula promoción elegible en servicio. Avisos se editan en `public_notice_editor.py`, validan HTML permitido y fechas, se guardan en `aviso_publico`; app pública los ordena por prioridad y puede bloquear fecha/hora de delivery.

### Gastos y documentos

`_render_expense_form` permite ticket con uno o varios ítems. `ExpenseService` valida, obtiene/crea motivo/marca, calcula subtotal/total, genera código `GAS`, guarda cabecera y detalle en una transacción. Edición sustituye las líneas y recalcula total; borrado elimina detalles/documentos asociados por lógica de servicio. Captura opcional recibe imagen/PDF, hash deduplicable, decodifica QR/ejecuta OCR local (o Azure si se configura) y crea un borrador de datos. Usuario revisa/edita y confirma; extracción no constituye asiento contable automáticamente.

### Funciones adicionales

Exportación XLSX en flujos internos; carga/importación de datos históricos mediante `scripts/import_historical_orders.py`, `import_historical_expenses.py`, pasos preparatorios de gastos; seeds de catálogo y reglas; menú compartible por URL WhatsApp; carga de imágenes de marca/producto/categoría; resumen de producción de pedidos. El repositorio contiene estos procesos, no prueba que se hayan ejecutado en producción.

## 8. Infraestructura y despliegue

### Local

`docker-compose.yml` inicia PostgreSQL 16 y app Python/Reflex, publica app en `3000` y DB en `5433` (5432 dentro de la red), usa volumen persistente `postgres_data`; healthcheck usa `pg_isready`. La app Compose ejecuta Reflex con módulo por defecto `gastroflow.app`, es decir, la aplicación Reflex completa. La guía documenta `docker compose up --build`, Alembic y creación inicial de admin. `Dockerfile` compila y sirve Reflex en puerto 3000.

### Despliegue documentado/separado

- Público: Render Web Service con `Dockerfile.public`, `REFLEX_APP_MODULE_IMPORT=gastroflow.public_app`, endpoint `/ping`; comparte PostgreSQL y lee medios públicos desde Supabase Storage. `render_public.py` usa el puerto `PORT` (fallback 10000), mientras el doc de despliegue lista puerto 3000; la configuración de plataforma debe alinear el puerto efectivo.
- Interno: Streamlit Community Cloud apunta a `streamlit_deploy/streamlit_app.py`, requiere `requirements-internal.txt`/wrapper equivalente y secrets de DB, app, Storage y OCR.
- DB/storage: Supabase es objetivo de despliegue descrito. No hay evidencia en código de que los servicios externos estén provisionados ni que el deploy esté activo.

Settings leídos por Pydantic en `config/settings.py`: `APP_ENV`, `APP_SECRET_KEY`, `GOOGLE_MAPS_API_KEY`, `DATABASE_URL`, `MEDIA_STORAGE_BACKEND`, `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`, variables de Azure Document Intelligence, `EXPENSE_OCR_ENGINE`, `TESSERACT_LANGUAGE`. La UI también lee variables de marca/pago como `STORE_NAME`, `PIZZERIA_WHATSAPP_PHONE`, `TRANSFER_TITULAR`, `TRANSFER_ALIAS`; algunas no están declaradas en `Settings` pero pueden leerse por entorno en componentes. `DATABASE_URL` normaliza esquema PostgreSQL simple a driver psycopg.

Logs: logging estándar/Streamlit/Reflex/Docker. En la app Reflex existen detalles técnicos de excepción con control de acceso según código; Streamlit presenta error amigable y puede registrar detalle. No se vio centralización de logs, APM, métricas, alertas ni política de retención/backups implementada en este repositorio.

Puntos de falla: DB indisponible o credenciales/conexiones agotadas; migración no aplicada; token/secret mal configurado; storage Supabase o permisos/bucket; OCR y datos del ticket ambiguos; dependencia de Tesseract/lenguaje; latencia de Render/Streamlit; caché de hasta 30s; incompatibilidad entre la versión de Streamlit desplegada y frontend en caché; flags/variables distintas entre dos servicios. WhatsApp/Maps no deben considerarse disponibles solo por variables de entorno.

## 9. Seguridad y calidad

### Controles observados

- Password hash bcrypt, sin password serializado en `UsuarioRead` y protegido en CRUD genérico.
- Login rechaza inactivos y comparación de firma HMAC usa `compare_digest`; token expira y se vuelve a consultar usuario en DB.
- Permisos por módulo y chequeos en capa servicio; whitelist CRUD evita nombres arbitrarios de tabla.
- Restricciones SQL y validaciones de cantidades, estados, montos y reglas de dominio; recálculo server-side en checkout.
- Secretos configurados desde entorno/Streamlit Secrets; service role key solo se usa en servidor para upload.
- Sanitización del rich text con tags/estilos permitidos y eliminación de elementos peligrosos.
- Hash SHA256 para evitar duplicidad de documentos.

### Riesgos/deuda a revisar

- El token de autenticación se lleva en query string (`?auth=...`); puede quedar en historial, logs, capturas o referer. El vencimiento reduce pero no elimina exposición. Preferir cookie Secure/HttpOnly/SameSite o mecanismo de sesión de Streamlit con CSRF/session protections verificadas.
- No se observa MFA, limitación de intentos, recuperación/cambio de contraseña ni segundo factor. El esquema HMAC propio debe revisarse en despliegue TLS y rotación de `APP_SECRET_KEY`.
- El README raíz describe una arquitectura Reflex monolítica que contradice la separación actual. Existen dos UIs internas posibles y diferencias entre entrypoints/scripts/docs; esto facilita desplegar interfaz equivocada.
- `AdminCrudService` permite que un admin edite modelos transaccionales vía CRUD genérico (pedido/gasto/cliente/ítems) además de flujos con auditoría; aclarar si la vía técnica debe mantenerse y asegurar controles operativos en interfaz/servicio.
- Algunas acciones administrativas tienen auditoría explícita y otras CRUD genéricas no muestran auditoría en el código revisado. Revisar trazabilidad uniforme y quién puede borrar datos.
- OCR procesa archivos subidos. Validar límites de tamaño/página, tipo real del contenido, protección contra archivos maliciosos, conservación y acceso a documentos; el hash no es control antimalware.
- Supabase Storage URL pública está diseñada para assets públicos; no guardar allí comprobantes sensibles sin política privada/URLs firmadas. El código genera URL pública para cualquier upload al backend Supabase; separar buckets/políticas para documentos.
- Catálogo-cache es local por worker; invalidación entre procesos no se comparte, con posible ventana de inconsistencia documentada de 30s.
- Engine global de SQLModel no muestra configuración explícita de pool_size/recycle/timeouts. Dimensionar en función de workers y límite de conexiones PostgreSQL.
- Tests cubren pedidos, checkout, auth, gastos, promociones, OCR, combos, avisos e interacciones. No se ejecutaron en este análisis por solicitud de no alterar el estado/validación del repositorio; la cobertura no reemplaza verificación de producción.

## 10. Evaluación técnica

### Decisiones y fortalezas

- Compartir servicios/modelos entre interfaces previene duplicar reglas comerciales.
- Capas de dominio y servicios reconocibles; errores de dominio separados de excepciones de infraestructura.
- PostgreSQL/SQLModel/Alembic, claves foráneas, índices, snapshots Decimal y secuencias para folios aportan consistencia transaccional y consultas de negocio.
- Precio recalculado en servidor, idempotencia por token, transiciones de estado explícitas, snapshots de revisión, permisos por módulo y bajas reversibles fortalecen operaciones.
- OCR humano en circuito, con motores local/opcional en vez de contabilización ciega.

### Debilidades y escalabilidad

- `internal_app/streamlit_app.py` es monolítico y contiene UI, consultas, cálculos y mutaciones; dificulta aislar pruebas y dividir equipo. Estados Reflex duplican parte de las funciones internas.
- Ambas apps comparten base y despliegue, pero no hay API intermedia. Operativamente es simple, aunque cada proceso debe cargar credenciales y librerías DB y las reglas quedan acopladas a sesiones SQL.
- No hay colas ni tareas asíncronas para OCR/importaciones; en comprobantes largos la latencia queda en la interacción Streamlit.
- Cache por proceso y acceso directo a DB pueden generar muchas conexiones a medida que crecen workers/sesiones. Listados cargan/transforman datos dentro de funciones UI; revisar paginación para volumen alto.
- Falta evidencia de pruebas de carga, observabilidad, backups, recuperación, rate limiting de checkout y protección de abuso público.
- Hay inconsistencia de documentación/entrypoints y setup: Compose levanta Reflex completo, despliegue separado propone Render + Streamlit; algunas guías están desactualizadas respecto a modelo/stack y conviven varios requirements.

### Recomendaciones

**Corto plazo:** actualizar README/diagramas y elegir entrypoints oficiales; comprobar que `Dockerfile.public` y los docs usan el mismo puerto; inventariar variables efectivamente requeridas; retirar/rotular claramente UI Reflex interna alternativa; revisar token por URL; hacer privado el storage de comprobantes; asegurar auditoría también en edición/borrado administrativo; definir migración y backup antes de publicar; revisar constraints/índices contra consultas reales.

**Mediano/largo plazo:** dividir `streamlit_app.py` en páginas, repositorios/consultas y casos de uso; quitar duplicación entre estado Reflex interno y Streamlit; definir una interfaz de aplicación/API si se agregan otros clientes o se necesita aislamiento de DB; añadir tareas en background para OCR/importaciones, observabilidad y alertas, estrategia de retención/restore, límites de pool, paginación y pruebas de concurrencia/carga. Incorporar Maps o pagos solo con flujo y claves reales, actualmente no comprobables.

## 11. Artefactos generados

- [ARQUITECTURA_TECNICA.md](ARQUITECTURA_TECNICA.md): informe completo.
- [architecture.mmd](architecture.mmd): arquitectura de componentes.
- [er_diagram.mmd](er_diagram.mmd): entidades y relaciones.
- [business_flows.mmd](business_flows.mmd): secuencias de checkout, operación y gastos.

## 12. Explicación para presentación

### Audiencia técnica

GastroFlow es un monorepo Python con dos frontends desplegables: checkout público en Reflex y gestión interna en Streamlit. Ambos usan un núcleo compartido SQLModel/SQLAlchemy con PostgreSQL y servicios de dominio para recalcular pedidos, promociones, extras, pagos, gastos y permisos. Alembic versiona el esquema. El público crea pedidos con snapshots e idempotencia y el interno actualiza estados con reglas y registra cambios. Los medios se guardan localmente o en Supabase Storage; OCR de comprobantes es local por defecto y requiere revisión humana. No hay API REST independiente ni integración transaccional con WhatsApp/Maps/pagos comprobable.

### Audiencia no técnica

GastroFlow reemplaza planillas separadas por una herramienta compartida. El cliente arma su pedido desde el catálogo y el sistema vuelve a verificar precios y condiciones antes de registrarlo. El personal ve ese pedido en otra pantalla, lo prepara y marca su avance. En el mismo lugar puede registrar tickets de compras, administrar productos, precios, promociones y avisos. Las dos pantallas consultan una única base de datos, por lo que el pedido del cliente aparece en la gestión interna. La lectura automática de comprobantes ayuda a cargar datos, pero una persona los revisa antes de guardar.
