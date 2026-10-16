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

Para la versión con promos por categoría, ejecutar las migraciones hasta
`0009_promotion_categories` y publicar también la gestión interna. Revisar las
promos sin categoría asignada antes de habilitarlas. Ver
[Promos por categoría y paquetes combinados](promotion-categories.md).

Probar:

- `/ping` responde `ok`.
- `/` carga el catalogo.
- No usar este deploy para rutas internas.

La gestion de pedidos, gastos, catalogo y promociones debe hacerse desde Streamlit.

## Actualización del carrito y la confirmación

Antes de desplegar esta versión, ejecutar `python -m alembic upgrade head` con la
conexión de Supabase. Las migraciones agregan el identificador único de confirmación
y separan presentación de normalización. Nombres, títulos, descripciones,
direcciones y observaciones conservan la escritura ingresada. Códigos internos y
usuarios se normalizan en mayúsculas. Marcas, motivos y usuarios se comparan sin
distinguir mayúsculas/minúsculas. Si hay valores ya duplicados que resultan
equivalentes, la migración se detiene para que se resuelvan manualmente.

Los textos que una migración anterior ya convirtió a mayúsculas no pueden recuperar
su formato original automáticamente. El administrador puede editarlos una vez y
desde entonces se conservará la escritura elegida.

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

La carga pública usa tres consultas: categorías/productos visibles en un JOIN,
zonas de envío y reglas de mitad y mitad. El logo se lee en paralelo. Los datos de catálogo y logo se
comparten durante 30 segundos por proceso del servidor; cambios desde Streamlit
pueden tardar hasta 30 segundos en aparecer en una nueva carga. Los precios al
confirmar siguen consultándose en la base, sin usar esa caché. Las imágenes del
catálogo se cargan a medida que se acercan al área visible.

La selección de mitad y mitad y la carga de sus 10 combinaciones se describen en
[Mitad y mitad](half-pizzas.md). Las reglas se cargan con
`python -m scripts.seed_half_pizzas`; no requieren una migración nueva.

Al confirmar queda solo el texto de carga junto al spinner. El resumen de
WhatsApp incluye por separado la fecha del pedido y la fecha de entrega.

El celular se guarda como número nacional argentino de 10 dígitos y funciona como
identificador del cliente. Se aceptan formatos con `+54 9`, `0`, espacios y
guiones. El formulario exige repetirlo; un número incompleto, como uno de nueve
dígitos, se rechaza antes de guardar. Dos formatos equivalentes reutilizan el
mismo cliente. Esto valida estructura y reduce errores de tipeo, pero comprobar
que el número existe o pertenece al cliente requeriría verificación por WhatsApp
o SMS.

La migración convierte al formato nacional los celulares históricos que sean
estructuralmente válidos. Los registros históricos incompletos quedan visibles
para corregirlos manualmente. Si dos clientes existentes terminan con el mismo
celular normalizado, la migración se detiene sin fusionarlos para evitar asociar
pedidos automáticamente al cliente equivocado.
