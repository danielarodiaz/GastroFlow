# Fase 2 - Docker y setup local

Este documento describe el entorno de desarrollo local del MVP.

## Requisitos

- Docker Desktop o Docker Engine con Docker Compose.
- Copia local del repositorio.

No hace falta instalar Postgres localmente: el servicio `db` lo levanta Compose.

## Variables de entorno

1. Copiar `.env.example` a `.env` si queres sobrescribir los defaults locales.
2. Cambiar al menos `APP_SECRET_KEY` y `POSTGRES_PASSWORD` para cualquier entorno que no sea local.
3. Dejar `GOOGLE_MAPS_API_KEY` vacia hasta tener una clave real. La UI debe degradar a campo de texto en fases futuras.

Compose puede levantar con valores por defecto aunque `.env` no exista. El archivo `.env.example` documenta todas las variables esperadas.

Variables principales:

| Variable | Uso |
| --- | --- |
| `APP_ENV` | Entorno logico de la app. |
| `APP_SECRET_KEY` | Secreto de aplicacion para auth/sesiones en fases futuras. |
| `GOOGLE_MAPS_API_KEY` | Clave opcional para selector de ubicacion. |
| `POSTGRES_DB` | Nombre de la base Postgres. |
| `POSTGRES_USER` | Usuario Postgres. |
| `POSTGRES_PASSWORD` | Password Postgres. |
| `POSTGRES_HOST` | Host de Postgres dentro de Compose: `db`. |
| `POSTGRES_PORT` | Puerto publicado para herramientas locales. |
| `DATABASE_URL` | URL SQLAlchemy/SQLModel con driver `psycopg`. |

## Levantar el entorno

```bash
docker compose up --build
```

Servicios:

- App Reflex: http://localhost:3000
- Backend Reflex/WebSocket: http://localhost:8000
- Postgres para herramientas locales: localhost:5433

El puerto externo `5433` evita chocar con instalaciones locales de PostgreSQL que suelen usar `5432`.
Dentro de Docker, la app se conecta al servicio `db` por el puerto interno `5432`.

## Apagar el entorno

```bash
docker compose down
```

Para borrar tambien los datos locales de Postgres:

```bash
docker compose down -v
```

## Estado de esta fase

Incluido:

- `Dockerfile` para la app Reflex.
- `docker-compose.yml` con app y Postgres 16.
- `.env.example` con variables documentadas.
- `requirements.txt` con dependencias base del MVP.
- App Reflex minima para verificar que el contenedor arranca.

Pendiente despues de Fase 3:

- Convertir `gastroflow/seed/catalog_seed.json` en inserts reales de catalogo.

## Migraciones

Con los servicios levantados, ejecutar migraciones con:

```bash
docker compose run --rm app alembic upgrade head
```

Para volver atras la primera migracion:

```bash
docker compose run --rm app alembic downgrade base
```

## Prueba de humo de pedidos

Para validar la capa de pedidos contra Postgres real:

```bash
docker compose run --rm app python -m scripts.smoke_order_service
```

El script crea datos `SMOKE_*` idempotentes y genera pedidos de prueba usando `OrderService`.

## Prueba de humo de gastos

Para validar la capa de gastos contra Postgres real:

```bash
docker compose run --rm app python -m scripts.smoke_expense_service
```

El script crea un gasto, reutiliza motivo/marca con busqueda case-insensitive y verifica la secuencia `GAS-*`.

## Prueba de humo CRUD Admin

Para validar el CRUD administrativo contra Postgres real:

```bash
docker compose run --rm app python -m scripts.smoke_admin_crud
```

El script crea, edita, lista y borra datos de catalogo, y valida que la creacion de usuario no exponga `password_hash`.

## Primer Admin

El sistema no trae un usuario Admin hardcodeado. Despues de correr migraciones, crear el primer Admin con:

```bash
docker compose run --rm app python -m scripts.create_admin --username tu_usuario
```

El comando pedira la password de forma interactiva. Para entornos no interactivos tambien acepta variables:

```bash
FIRST_ADMIN_USERNAME=tu_usuario FIRST_ADMIN_PASSWORD=tu_password docker compose run --rm app python -m scripts.create_admin
```
