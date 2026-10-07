# Deploy en Northflank

Guia de produccion para GastroFlow usando Northflank para la app y PostgreSQL, y Supabase Storage para imagenes persistentes sin volumen local.

## 1. Supabase Storage

1. Crear un proyecto en Supabase.
2. Crear un bucket publico llamado `gastroflow-media`.
3. Copiar:
   - Project URL como `SUPABASE_URL`.
   - Service role key como `SUPABASE_SERVICE_ROLE_KEY`.
4. En Northflank, cargar estas variables solo como secretos de runtime.

El bucket debe ser publico porque las imagenes del catalogo y logo se sirven directamente al navegador. La service role key se usa solo desde el servidor para subir archivos; no se expone al frontend.

## 2. Northflank PostgreSQL

1. Crear un addon PostgreSQL.
2. Usar la connection string interna del addon.
3. Cargarla en la app como `DATABASE_URL`.

La URL debe usar el driver de SQLAlchemy:

```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/database
```

Si Northflank entrega `postgresql://...`, agregar `+psycopg` despues de `postgresql`.

## 3. Variables de runtime de la app

```env
APP_ENV=production
APP_SECRET_KEY=<valor-largo-y-secreto>
DATABASE_URL=postgresql+psycopg://...
MEDIA_STORAGE_BACKEND=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_STORAGE_BUCKET=gastroflow-media
GOOGLE_MAPS_API_KEY=
STORE_NAME=Las Pizzas De Alejo
PIZZERIA_WHATSAPP_PHONE=
TRANSFER_TITULAR=Alvaro Alejo Marquez
TRANSFER_ALIAS=marquezale.uala
```

Opcional para inicializar admin en el primer deploy:

```env
FIRST_ADMIN_USERNAME=<usuario>
FIRST_ADMIN_PASSWORD=<password>
```

## 4. Servicio web

- Build: Dockerfile.
- Puerto publico: `3000`.
- No publicar `8000`.
- Health check: `/ping` sobre el puerto `3000`.

El `Dockerfile` corre Reflex en modo produccion y expone un solo puerto publico. En modo `prod`, Reflex sirve frontend y backend desde el mismo origen, por eso no hace falta publicar `8000`.

## 5. Inicializacion de base

Con la app ya conectada a PostgreSQL, ejecutar una vez:

```bash
python -m scripts.deploy_init
```

Ese comando ejecuta:

1. `alembic upgrade head`
2. `scripts.seed_catalog`
3. creacion de admin si existen `FIRST_ADMIN_USERNAME` y `FIRST_ADMIN_PASSWORD`

## 6. Verificacion

Probar:

- `/`
- `/login`
- `/pedidos`
- `/gastos`
- `/catalogo-admin`
- `/promociones`
- `/admin`

Luego subir una imagen desde `/catalogo-admin`, redeployar el servicio y confirmar que la imagen sigue visible. Si sigue visible, Supabase Storage quedo funcionando y no hay dependencia de `uploaded_files`.

Tambien se puede automatizar parte de la verificacion con:

```bash
python -m scripts.verify_deploy https://<url-publica-northflank>
python -m scripts.smoke_media_storage
```

`verify_deploy` comprueba rutas publicas y `smoke_media_storage` sube un archivo chico al backend de media configurado por variables de entorno.
`SUPABASE_KEY` tambien es aceptado como alias de `SUPABASE_SERVICE_ROLE_KEY`, pero debe ser una service role key. No usar `sb_publishable...` ni anon key para subidas desde el servidor.
