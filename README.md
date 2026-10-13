# 🍕 Gastro-Flow (MVP) — Sistema de Pedidos y Gastos

Sistema centralizado de gestión operativa y control de gastos diseñado específicamente para locales gastronómicos pequeños y medianos (parametrizado inicialmente para pizzerías y rotiserías). 

Reemplaza los flujos manuales propensos a pérdidas de información (como planillas de Google Sheets compartidas) mediante una interfaz web ágil y mobile-first, conectada a una base de datos relacional robusta lista para consumo directo desde **Power BI**.

---

## 🚀 Stack Tecnológico

El proyecto está desarrollado **100% en Python**, priorizando una arquitectura desacoplada por capas:

* **Frontend & Backend App:** [Reflex](https://reflex.dev/) (Full-stack Python reactivo sobre Starlette/FastAPI y WebSockets).
* **ORM & Validación:** [SQLModel](https://sqlmodel.tiangolo.com/) (integración de SQLAlchemy 2.0 y Pydantic v2).
* **Base de Datos:** PostgreSQL 16.
* **Control de Esquema y Migraciones:** Alembic.
* **Entorno & Contenedores:** Docker & Docker Compose.
* **Autenticación:** Hashing criptográfico (bcrypt/argon2) y autorización RBAC a nivel de capa de servicios.

---

## 🏛️ Arquitectura y Principios de Diseño

1. **Lógica de Negocio en Servicios (`services/`):** La UI nunca valida reglas de negocio ni ejecuta transacciones complejas directamente. Todo se resuelve mediante casos de uso (`OrderService`, `ExpenseService`, etc.).
2. **Modelo "BI-Friendly":** 
   * Manejo estricto de dinero mediante tipos `Decimal` / `NUMERIC` en PostgreSQL (sin imprecisiones de `float`).
   * **Snapshot de precios históricos:** `pedido_item.precio_unitario` y `pedido.costo_envio` guardan el valor vigente en el momento de compra para no alterar balances pasados ante futuras actualizaciones de catálogo.
   * Cantidades y unidades tipadas (separando magnitudes numéricas de strings de medida).
3. **Claves Primarias Técnicas vs. Códigos de Negocio:** Uso de IDs enteros autoincrementales en la base de datos y secuencias atómicas para códigos correlativos legibles (`PED-0001`, `GAS-0001`).
4. **UI Mobile-First para Despacho:** Interfaz táctil pensada para celulares y tablets en entornos de cocina, con tarjetas grandes de cambio de estado en tiempo real.

---

## 📋 Módulos del Sistema

* **Formulario Público de Pedidos (Sin Login):**
  * Catálogo dinámico (categorías, pizzas simples o combinadas de 2 sabores).
  * Regla mayorista (validación de mínimo de unidades).
  * Cálculo de costos por zona de entrega o retiro en el local.
  * Selector de ubicación con Google Maps (con degradación controlada a texto libre en caso de no disponer de API Key).
  * Enlace preformateado a WhatsApp (`wa.me`) para pedidos que requieran confirmación manual según `combo_regla`.
* **Panel Operativo (Dueño y Admin):**
  * Vista de pedidos agrupada por estados (`PEDIDO`, `PENDIENTE_CONFIRMACION`, `EN_PROCESO`, `ENTREGADO`, `CANCELADO`).
  * Botones de un solo toque para transición de estados sin recargar pantalla.
  * Formulario de gastos con autocompletado y creación en caliente (*on-the-fly*) de motivos y marcas.
* **Panel de Configuración (Solo Admin):**
  * CRUD de categorías, productos, promociones, reglas mayoristas, reglas de combinación (`combo_regla`) y zonas de envío.

---

## 📁 Estructura del Repositorio

```text
.
├── gastroflow/
│   ├── app.py                # Entrada Reflex y registro de paginas
│   ├── domain/               # Enums, maquina de estados y errores de dominio
│   ├── models/               # Modelos SQLModel (Base/Table/Create/Read)
│   ├── data/                 # Sesiones, repositorios, secuencias y UoW
│   ├── services/             # Reglas de negocio y transacciones
│   ├── states/               # Clases rx.State aisladas por flujo
│   ├── ui/                   # Paginas y componentes Reflex
│   └── config/               # Settings desde variables de entorno
├── docs/                     # Arquitectura y modelo de dominio
├── scripts/                  # Comandos seguros de seed/admin
└── tests/                    # Tests unitarios y de integracion
```

## 📌 Estado de entrega

Plan de separacion cloud definido:

* [docs/separation-architecture.md](docs/separation-architecture.md): arquitectura objetivo con app publica en Render, gestion interna en Streamlit Community Cloud, PostgreSQL unica en Supabase y Supabase Storage.
* [docs/deploy-render-public.md](docs/deploy-render-public.md): guia del deploy publico de pedidos usando `Dockerfile.public`.
* [docs/deploy-streamlit-internal.md](docs/deploy-streamlit-internal.md): guia del deploy interno de gestion usando Streamlit Community Cloud.
* [docs/cloud-rollout-checklist.md](docs/cloud-rollout-checklist.md): checklist de Supabase, migraciones, Render, Streamlit y verificacion final.

Fase 1 completada:

* [docs/phase-1-architecture.md](docs/phase-1-architecture.md): capas, responsabilidades, flujos principales y decisiones pendientes.
* [docs/domain-model.md](docs/domain-model.md): entidades, relaciones, enums, maquina de estados y reglas criticas.

Fase 2 completada:

* [docs/setup.md](docs/setup.md): Docker Compose, variables de entorno y setup local.
* [docs/catalog-seed-required-data.md](docs/catalog-seed-required-data.md): datos confirmados para el seed inicial.
* [gastroflow/seed/catalog_seed.json](gastroflow/seed/catalog_seed.json): seed declarativo inicial con datos confirmados.

Fase 3 completada:

* Modelos SQLModel en `gastroflow/models/`.
* Configuracion Alembic en `alembic.ini` y `alembic/env.py`.
* Primera migracion en `alembic/versions/0001_initial_schema.py`.

Fase 4 completada:

* Hash de passwords con bcrypt.
* Servicio de auth y autorizacion por rol.
* Comando seguro para crear el primer Admin.

Fase 5 completada:

* Servicio de pedidos con upsert de cliente por telefono.
* Generacion atomica de codigo `PED-*` con secuencia PostgreSQL.
* Snapshot de precios, envio y total.
* Reglas de mayorista, promociones, combos y confirmacion.
* Maquina de estados de pedido en dominio.

Fase 6 completada:

* Servicio de gastos con alta validada.
* Creacion dinamica de motivo y marca.
* Generacion atomica de codigo `GAS-*` con secuencia PostgreSQL.

Fase 7 completada:

* CRUD administrativo generico para todas las tablas del modelo.
* Whitelist explicita de tablas administrables.
* Manejo especial de `usuario`: password de entrada hasheada y `password_hash` nunca serializado.

El proyecto debe esperar confirmacion antes de avanzar a la Fase 8.
