# Deploy publico en Render

Esta guia corresponde a la app publica de pedidos. La gestion interna queda fuera de este deploy y se publicara aparte en Streamlit Community Cloud.

## Servicio

- Tipo: Web Service.
- Runtime: Docker.
- Dockerfile: `Dockerfile.public`.
- Puerto publico: `3000`.
- Health check path: `/ping`.

`Dockerfile.public` usa `REFLEX_APP_MODULE_IMPORT=gastroflow.public_app`, por lo que solo registra:

- `/`
- `/ping`

No registra rutas internas como `/login`, `/pedidos`, `/gastos`, `/catalogo-admin`, `/promociones` ni `/admin`.

## Variables

```env
APP_ENV=production
APP_SECRET_KEY=<valor-largo-y-secreto>
DATABASE_URL=postgresql+psycopg://...
MEDIA_STORAGE_BACKEND=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_STORAGE_BUCKET=gastroflow-media
GOOGLE_MAPS_API_KEY=
STORE_NAME=Las Pizzas De Alejo
PIZZERIA_WHATSAPP_PHONE=
TRANSFER_TITULAR=Alvaro Alejo Marquez
TRANSFER_ALIAS=marquezale.uala
REFLEX_APP_MODULE_IMPORT=gastroflow.public_app
```

La app publica no necesita subir imagenes desde el cliente. Si en Render no se hacen uploads, no cargar `SUPABASE_SERVICE_ROLE_KEY` en este servicio. Las imagenes se leen desde URLs publicas de Supabase Storage.

## Ping automatico

Para reducir sleeps del free tier se puede configurar un ping externo contra:

```text
https://<render-app>/ping
```

El ping mantiene despierta la app, pero no reemplaza monitoreo real ni pruebas manuales del flujo de pedido.

## Verificacion manual

Probar:

- `/ping` responde `ok`.
- `/` carga el catalogo.
- No usar este deploy para rutas internas.

La gestion de pedidos, gastos, catalogo y promociones debe hacerse desde Streamlit.
