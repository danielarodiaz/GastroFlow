# Arquitectura de separacion: app publica + gestion interna

Este documento define la arquitectura objetivo para separar GastroFlow en dos aplicaciones desplegadas de forma independiente, manteniendo una sola base de datos PostgreSQL y un unico storage de imagenes en Supabase.

## Objetivo

Separar responsabilidades sin duplicar reglas de negocio:

- La app publica atiende el flujo de pedidos de clientes.
- La app interna en Streamlit atiende gestion operativa y administrativa.
- PostgreSQL en Supabase es la fuente unica de verdad.
- Supabase Storage guarda imagenes de categorias, productos y marca.
- Los modelos, migraciones, servicios y reglas de negocio quedan compartidos dentro del mismo repositorio.

## Decision principal

GastroFlow queda como monorepo con dos aplicaciones y un nucleo compartido.

```text
GastroFlow/
  gastroflow/
    core compartido actual:
      config/
      data/
      domain/
      models/
      services/
      security/

    public_app/
      app.py
      pages/
      components/

    internal_app/
      streamlit_app.py
      pages/
      components/

  alembic/
  scripts/
  tests/
  docs/
  Dockerfile.public
  requirements-public.txt
  requirements-internal.txt
```

La estructura puede migrarse en pasos. No es necesario mover todo de una vez: primero se estabiliza el nucleo compartido, despues se crea el entrypoint publico y luego el entrypoint interno.

## Arquitectura logica

```text
Cliente
  |
  v
App publica en Render
  |
  v
Servicios compartidos de GastroFlow
  |
  v
Supabase PostgreSQL
  ^
  |
Streamlit Community Cloud
  |
  v
Servicios compartidos de GastroFlow

Supabase Storage
  ^
  |
App publica lee URLs publicas
Streamlit sube y administra imagenes
```

## Responsabilidades

### Nucleo compartido

El nucleo compartido contiene todo lo que no debe duplicarse:

- modelos SQLModel;
- migraciones Alembic;
- conexion a base de datos;
- enums y errores de dominio;
- servicios de pedidos, gastos, auth, admin y storage;
- reglas de promociones, mayorista, combos, estados y codigos de negocio;
- utilidades comunes de formato o normalizacion cuando sean independientes de UI.

El nucleo no debe depender de Reflex ni de Streamlit. Si una funcion necesita `rx.State`, componentes Reflex o widgets Streamlit, pertenece a la app correspondiente, no al nucleo.

### App publica

Responsabilidad: flujo de cliente.

Incluye:

- catalogo publico;
- categorias visibles;
- productos activos;
- carrito;
- checkout;
- metodo de entrega;
- forma de pago;
- creacion de pedido;
- confirmacion y link de WhatsApp cuando aplique;
- futura integracion con Google Maps.

No incluye:

- login interno;
- gestion de pedidos;
- gastos;
- catalogo admin;
- promos admin;
- CRUD tecnico;
- service role key expuesta al navegador.

Deploy objetivo:

- Render;
- Dockerfile dedicado;
- ruta `/`;
- healthcheck `/ping`;
- ping automatico externo para reducir sleeps del free tier.

### App interna Streamlit

Responsabilidad: gestion interna.

Incluye:

- login interno;
- pedidos;
- gastos;
- catalogo;
- promociones;
- admin;
- subida de imagenes a Supabase Storage;
- vistas resumen con modal de detalle.

Patron de UX para pedidos y gastos:

```text
Listado principal:
  codigo | fecha | cliente/lugar | estado | total | Ver detalles

Modal de detalle:
  cabecera del registro
  tabla de items
  totales
  acciones permitidas
```

Deploy objetivo:

- Streamlit Community Cloud;
- secrets de Streamlit para `DATABASE_URL`, `APP_SECRET_KEY`, `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`;
- acceso directo server-side a PostgreSQL y Storage usando los servicios compartidos.

## Base de datos

La base queda en Supabase PostgreSQL.

No se crean dos bases. La app publica y Streamlit leen/escriben en la misma base mediante el nucleo compartido.

Ventajas:

- no hay sincronizacion entre bases;
- pedidos creados por clientes aparecen en gestion interna;
- cambios de catalogo y promociones impactan en el flujo publico;
- Power BI o herramientas externas pueden consultar una sola fuente.

## Storage

Las imagenes no se guardan como binarios en PostgreSQL.

Supabase Storage guarda:

- logo/marca;
- fotos de categorias;
- fotos de productos por categoria;
- futuros assets publicos.

PostgreSQL guarda solo URLs:

- `categoria.foto_url`;
- `producto.fotos`;
- `producto_categoria.foto_url`;
- `app_config` para logo u otros valores de marca.

El bucket debe ser publico para que el navegador pueda mostrar imagenes. Las subidas se hacen solo desde servidor usando service role key.

## Modelo de gastos tipo ticket

Gastos debe evolucionar de un registro plano a cabecera + detalle.

Modelo objetivo:

```text
gasto
  id
  codigo
  fecha
  lugar_texto
  lugar_lat
  lugar_lng
  observaciones
  monto_total
  created_at
  updated_at

gasto_detalle
  id
  gasto_id
  motivo_gasto_id
  marca_id
  descripcion
  cantidad
  unidad_medida
  precio_unitario
  subtotal
```

Ejemplo:

```text
GAS-0001
Fecha: 2026-10-08
Lugar: DISTRIBUIDORA VDIT
Total: 23500

Detalle:
  HARINA | GASTALDI | 000 25KG | 25 KG | 19000 | 19000
  LEVADURA | DUQUESA | 1KG | 1 KG | 4500 | 4500
```

La UI interna debe permitir agregar varios items antes de guardar el gasto. El guardado debe persistir cabecera y lineas en una transaccion.

## Pedidos con modal de detalle

Pedidos ya tiene cabecera + detalle mediante `pedido` y `pedido_item`.

La app interna debe mostrar un listado resumido y abrir detalle en modal:

```text
PED-0001
Cliente: Juan Perez
Telefono: 381...
Entrega: 2026-10-08
Direccion: ...
Estado: PEDIDO

Detalle:
  Muzzarella x2 | 5500 | 11000
  Especial x1 | 7000 | 7000

Envio: 1000
Total: 19000
```

El modal tambien puede incluir acciones de estado cuando corresponda.

## Google Maps futuro

El modelo ya contempla coordenadas:

- `pedido.direccion_lat`;
- `pedido.direccion_lng`;
- `gasto.lugar_lat`;
- `gasto.lugar_lng`.

La app publica debe seguir funcionando con direccion manual si no hay `GOOGLE_MAPS_API_KEY`.

Cuando se incorpore Google Maps:

- el cliente podra elegir direccion o ubicacion;
- se guardara texto + coordenadas;
- el costo de envio seguira resolviendose con zonas configuradas hasta que se defina calculo por distancia.

## Deploys

### Render: app publica

Usa:

- `Dockerfile.public`;
- `requirements-public.txt`;
- `DATABASE_URL`;
- `MEDIA_STORAGE_BACKEND=supabase`;
- `SUPABASE_URL`;
- claves necesarias solo del lado servidor;
- `/ping` para healthcheck.

El deploy publico no debe registrar rutas internas.

### Streamlit Community Cloud: app interna

Usa:

- `streamlit_app.py` o `gastroflow/internal_app/streamlit_app.py`;
- `requirements-internal.txt`;
- secrets de Streamlit;
- conexion directa a Supabase PostgreSQL;
- Supabase Storage para uploads.

## Orden recomendado de implementacion

1. Limpiar y validar migraciones para que una base Supabase nueva pueda correr desde cero.
2. Crear modelo `gasto_detalle` y adaptar `ExpenseService` a cabecera + items.
3. Extraer helpers compartidos que hoy estan dentro de `states/app_state.py` y no son UI.
4. Crear entrypoint publico separado con solo `/` y `/ping`.
5. Crear app Streamlit interna reutilizando servicios.
6. Agregar modales de detalle para pedidos y gastos en Streamlit.
7. Configurar Supabase PostgreSQL y Storage.
8. Deploy publico en Render.
9. Deploy interno en Streamlit Community Cloud.
10. Migrar datos historicos desde Excel cuando el flujo nuevo ya este probado.

## Riesgos y controles

- Migraciones actuales: deben revisarse antes de Supabase porque algunas revisiones parecen mezclar estado inicial y cambios posteriores.
- Secretos: `SUPABASE_SERVICE_ROLE_KEY` nunca debe exponerse al navegador.
- UI Reflex actual: contiene mucha logica de consulta/formato dentro de `rx.State`; conviene extraer solo lo reusable y no trasladar deuda innecesaria a Streamlit.
- Streamlit: debe tener flujo de auth suficiente para uso interno, incluso si el acceso a la URL no es publico.
- Render free tier: el ping automatico reduce sleeps, pero no reemplaza pruebas de disponibilidad.

## Resultado esperado

Al terminar esta separacion:

- clientes usan una app publica simple y enfocada en pedidos;
- administracion usa Streamlit;
- ambas apps comparten base, storage y reglas;
- gastos y pedidos se visualizan con el mismo patron cabecera + detalle;
- la arquitectura queda preparada para Google Maps y migracion historica desde Excel.
