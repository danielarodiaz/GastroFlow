# Deploy interno en Streamlit Community Cloud

Esta guia corresponde a la app interna de gestion.

## Entry point

Streamlit debe apuntar al archivo:

```text
streamlit_deploy/streamlit_app.py
```

Ese archivo delega en `gastroflow.internal_app.streamlit_app`.

## Dependencias

Usar:

```text
streamlit_deploy/requirements.txt
```

El archivo de dependencias del entrypoint fija Streamlit en la versión estable
probada para Community Cloud. No debe
reemplazarse por un rango abierto: Community Cloud podría iniciar el servidor con
un frontend distinto al probado y dejar módulos del navegador incompatibles en caché.

## Secrets

Configurar en Streamlit Community Cloud:

```toml
APP_ENV = "production"
APP_SECRET_KEY = "<valor-largo-y-secreto>"
DATABASE_URL = "postgresql+psycopg://..."
MEDIA_STORAGE_BACKEND = "supabase"
SUPABASE_URL = "https://<project-ref>.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "<service-role-key>"
SUPABASE_STORAGE_BUCKET = "gastroflow-media"
GOOGLE_MAPS_API_KEY = ""
EXPENSE_OCR_ENGINE = "tesseract"
TESSERACT_LANGUAGE = "spa"
STORE_NAME = "Las Pizzas De Alejo"
PIZZERIA_WHATSAPP_PHONE = ""
TRANSFER_TITULAR = "Alvaro Alejo Marquez"
TRANSFER_ALIAS = "marquezale.uala"
```

La app interna puede usar `SUPABASE_SERVICE_ROLE_KEY` porque corre server-side. No se debe usar esa key en la app publica del cliente.

## Funcionalidad inicial

Incluido:

- login con usuarios existentes;
- navegacion interna;
- listado de pedidos;
- modal de detalle de pedidos;
- cambio de estado de pedidos;
- listado de gastos por ítem y por comprobante;
- modal de detalle de gastos;
- carga de gasto con varios items en un solo ticket.
- captura asistida de PDF/imagen con QR local y Tesseract OCR en español;
- listado y edicion basica de categorias;
- listado y edicion basica de productos por categoria;
- listado, alta y edicion de promociones.
- subida/cambio de logo;
- subida/cambio de fotos de categorias;
- subida/cambio de fotos de productos por categoria.
- administración intuitiva de zonas de envío, categorías, agregados y usuarios;
- permisos por módulo, bajas reversibles y registro de cambios administrativos.

Pendiente para fases siguientes:

- mejoras visuales del editor de catalogo.

## Migración administrativa

Antes de iniciar esta versión, aplicar la migración que incorpora estados activos,
permisos y auditoría:

```powershell
python -m alembic upgrade head
```

La revisión esperada es `0016_admin_management`.
