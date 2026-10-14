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

## Actualización del carrito y la confirmación

Antes de desplegar esta versión, ejecutar `python -m alembic upgrade head` con la
conexión de Supabase. La migración `0006_public_order_safety` agrega un identificador
único de confirmación y reglas de mayúsculas para los textos de negocio de todas
las apps. También normaliza los textos existentes. No modifica contraseñas, hashes,
URLs de imágenes, configuración ni enums. Si existen valores únicos que solo
difieren en mayúsculas/minúsculas, detiene la migración antes de modificar datos;
resolver esos duplicados manualmente y volver a ejecutar. La reversión elimina
las reglas, pero no recupera las mayúsculas/minúsculas originales de los textos.

El formulario conserva la escritura del cliente hasta guardar. Agregar al carrito
muestra una notificación. Fecha sin año usa el año actual de Argentina y una hora
como `21` se completa como `21:00` al salir del campo o confirmar.

Envío/retiro y selección de zona actualizan el total sin consultar Supabase. La
tarificación consulta las promociones en conjunto y las operaciones de base de
la app pública se ejecutan fuera del bucle de eventos del servidor.

La confirmación oculta el botón mientras carga y luego muestra el pedido registrado
y un enlace **Enviar por WhatsApp**. La apertura automática usa la misma pestaña;
el enlace permite reintentar sin crear otro pedido. **Hacer otro pedido** inicia
una nueva confirmación. WhatsApp requiere que el cliente envíe el mensaje: abrir
el enlace no demuestra que se haya enviado.

Verificar en Chrome y en un teléfono: alternar envío/retiro, escribir y confirmar
sin esperar, hacer varios clics al confirmar y abrir WhatsApp desde el enlace de
recuperación. En la base debe quedar un solo pedido por confirmación.
