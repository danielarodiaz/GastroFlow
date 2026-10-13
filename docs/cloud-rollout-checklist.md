# Checklist de rollout cloud

Orden recomendado para pasar GastroFlow a la arquitectura separada.

## 1. Supabase

Crear un proyecto Supabase y preparar:

- PostgreSQL;
- bucket publico `gastroflow-media`;
- `SUPABASE_URL`;
- `SUPABASE_SERVICE_ROLE_KEY`;
- connection string PostgreSQL.

La URL de base debe usarse con driver SQLAlchemy:

```env
DATABASE_URL=postgresql+psycopg://...
```

## 2. Migraciones y seed

Con `DATABASE_URL` apuntando a Supabase:

```bash
alembic upgrade head
python -m scripts.seed_catalog
python -m scripts.create_admin --username <usuario>
```

Si se usa inicializacion automatica:

```bash
FIRST_ADMIN_USERNAME=<usuario> FIRST_ADMIN_PASSWORD=<password> python -m scripts.deploy_init
```

## 3. Render publico

Crear Web Service con:

- Dockerfile: `Dockerfile.public`;
- puerto: `3000`;
- healthcheck: `/ping`.

Variables:

```env
APP_ENV=production
APP_SECRET_KEY=<secret>
DATABASE_URL=postgresql+psycopg://...
MEDIA_STORAGE_BACKEND=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_STORAGE_BUCKET=gastroflow-media
REFLEX_APP_MODULE_IMPORT=gastroflow.public_app
```

No cargar `SUPABASE_SERVICE_ROLE_KEY` en Render publico salvo que se agregue una necesidad server-side concreta.

## 4. Streamlit interno

Crear app en Streamlit Community Cloud:

- entrypoint: `streamlit_app.py`;
- dependencias: `requirements-internal.txt`.

Secrets:

```toml
APP_ENV = "production"
APP_SECRET_KEY = "<secret>"
DATABASE_URL = "postgresql+psycopg://..."
MEDIA_STORAGE_BACKEND = "supabase"
SUPABASE_URL = "https://<project-ref>.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "<service-role-key>"
SUPABASE_STORAGE_BUCKET = "gastroflow-media"
```

## 5. Verificacion funcional

Probar en Render:

- `/ping`;
- `/`;
- carga del catalogo;
- creacion de pedido.

Probar en Streamlit:

- login;
- pedidos aparecen luego de crear uno publico;
- cambio de estado de pedido;
- alta de gasto multi-item;
- modal de detalle de gasto;
- edicion de categoria/producto;
- alta/edicion de promo;
- subida de logo/fotos.

## 6. Pendientes posteriores

- Migracion historica desde Excel de pedidos y gastos.
- Google Maps en flujo publico.
- Mejoras visuales de Streamlit.
- Monitoreo real y backups.
