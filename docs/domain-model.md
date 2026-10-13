# Modelo de dominio

## Entidades y relaciones

```text
categoria 1 ── * producto
categoria 1 ── * regla_mayorista

producto 1 ── * combo_regla.producto_a
producto 1 ── * combo_regla.producto_b
producto * ── * promocion through promocion_producto
producto 1 ── * precio_mayorista_producto
regla_mayorista 1 ── * precio_mayorista_producto

zona_envio 1 ── * pedido
cliente 1 ── * pedido
pedido 1 ── * pedido_item
producto 1 ── * pedido_item.producto
producto 1 ── * pedido_item.producto_combo

gasto 1 ── * gasto_detalle
motivo_gasto 1 ── * gasto_detalle
marca 1 ── * gasto_detalle

usuario
```

`pedido_item.producto_combo_id` es nullable. Cuando tiene valor, representa el segundo sabor/producto de un combo de 2 productos. El producto principal queda en `producto_id`.

## Enums de dominio

### RolUsuario

- `ADMIN`
- `DUENO`

### EstadoPedido

- `PEDIDO`
- `PENDIENTE_CONFIRMACION`
- `EN_PROCESO`
- `ENTREGADO`
- `CANCELADO`

### FormaPago

- `TRANSFERENCIA`
- `EFECTIVO`

### UnidadVenta

- `PIEZA`
- `UNIDAD`

### ReglaPrecioCombo

- `MAYOR_VALOR`
- `PROMEDIO`
- `PRECIO_FIJO`

### TipoPromocion

- `PRECIO_UNITARIO_POR_CANTIDAD`

## Tablas de catalogo

### categoria

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| codigo | str | Unico, indexado |
| nombre | str | Requerido |

### producto

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| codigo | str | Unico, indexado |
| categoria_id | int | FK a `categoria.id` |
| nombre | str | Requerido |
| descripcion | str null | Texto para catalogo publico |
| fotos | list[str] null | JSONB con una o mas URLs/rutas de imagen |
| precio | Decimal | NUMERIC, requerido |
| unidad_venta | enum | `PIEZA` o `UNIDAD` |

El producto mantiene solo su precio base y datos de catalogo publico. Promociones y precios mayoristas se modelan en tablas separadas para que el Admin pueda administrarlos sin mezclar reglas comerciales con el producto.

### promocion

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| codigo | str | Unico, indexado |
| nombre | str | Requerido |
| tipo | enum | Inicialmente `PRECIO_UNITARIO_POR_CANTIDAD` |
| cantidad_minima | int | Mayor a 0 |
| precio_unitario_promocional | Decimal | NUMERIC |
| activa | bool | Requerido |
| vigencia_desde | date/datetime null | Opcional |
| vigencia_hasta | date/datetime null | Opcional |

### promocion_producto

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| promocion_id | int | FK a `promocion.id` |
| producto_id | int | FK a `producto.id` |

La cantidad minima de la promocion se calcula sobre la suma de unidades de los productos elegibles. Esto permite cubrir tanto "2 Muzzarella" como "1 Especial + 1 Calabresa" sin duplicar reglas en la UI.

Ejemplos:

- Muzzarella lista para hornear cuesta 5500, pero llevando 2 o mas unidades de Muzzarella queda a 5000 cada una.
- Especial y Calabresa cuestan 7000, pero llevando 2 o mas unidades combinadas entre ambas quedan a 6500 cada una.

### regla_mayorista

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| codigo | str | Unico, indexado |
| categoria_id | int | FK a `categoria.id` |
| nombre | str | Requerido |
| cantidad_minima_total | int | Minimo total del pedido para activar mayorista |
| activa | bool | Requerido |

La regla mayorista se evalua por total de items elegibles dentro de una categoria o grupo comercial, no por item aislado. Para el caso inicial, si el pedido suma 10 pizzas de `LISTA_HORNO`, cada item elegible usa su propio precio mayorista.

### precio_mayorista_producto

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| regla_mayorista_id | int | FK a `regla_mayorista.id` |
| producto_id | int | FK a `producto.id` |
| precio_unitario_mayorista | Decimal | NUMERIC |

Regla de unicidad recomendada: un producto no puede tener dos precios para la misma regla mayorista activa.

### combo_regla

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| producto_a_id | int | FK a `producto.id` |
| producto_b_id | int | FK a `producto.id` |
| requiere_confirmacion | bool | Requerido |
| regla_precio | enum | `MAYOR_VALOR`, `PROMEDIO`, `PRECIO_FIJO` |
| precio_fijo_combo | Decimal null | Requerido si `regla_precio = PRECIO_FIJO` |

Regla de unicidad recomendada: no permitir duplicados para el mismo par de productos, independientemente del orden. En Postgres puede resolverse con columnas normalizadas o indice funcional en una migracion posterior.

### zona_envio

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| nombre | str | Requerido |
| costo | Decimal | NUMERIC, snapshot hacia pedido |

### motivo_gasto

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| nombre | str | Unico recomendado normalizado case-insensitive |

### marca

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| nombre | str | Unico recomendado normalizado case-insensitive |

## Tablas transaccionales

### usuario

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| username | str | Unico, indexado |
| password_hash | str | Nunca se expone en `UsuarioRead` |
| rol | enum | `ADMIN` o `DUENO` |
| created_at | datetime | Requerido |
| updated_at | datetime | Requerido |

### cliente

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| nombre_apellido | str | Requerido |
| telefono | str | Normalizado, unico recomendado |
| created_at | datetime | Requerido |
| updated_at | datetime | Requerido |

Antes de crear un cliente desde el formulario publico se hace upsert por telefono normalizado.

### pedido

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| codigo | str | Unico, indexado, formato `PED-0001` |
| fecha_entrega | date/datetime | Requerido |
| cliente_id | int | FK a `cliente.id` |
| direccion_delivery | str | Texto o `Retiro en el local` |
| direccion_lat | Decimal null | Coordenada opcional |
| direccion_lng | Decimal null | Coordenada opcional |
| zona_envio_id | int null | FK a `zona_envio.id` |
| costo_envio | Decimal | NUMERIC, snapshot |
| forma_pago | enum | Requerido |
| estado | enum | Maquina explicita |
| observaciones | str null | Texto libre operativo |
| monto_total | Decimal | NUMERIC, calculado en servicio |
| created_at | datetime | Requerido |
| updated_at | datetime | Requerido |

### pedido_item

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| pedido_id | int | FK a `pedido.id` |
| producto_id | int | FK a `producto.id` |
| producto_combo_id | int null | FK a `producto.id`, segundo sabor |
| cantidad | int | Mayor a 0 |
| precio_unitario | Decimal | NUMERIC, snapshot |

### gasto

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| codigo | str | Unico, indexado, formato `GAS-0001` |
| fecha | date | Requerido |
| lugar_texto | str | Requerido |
| lugar_lat | Decimal null | Coordenada opcional |
| lugar_lng | Decimal null | Coordenada opcional |
| observaciones | str null | Texto libre del ticket |
| monto_total | Decimal | Suma de subtotales de `gasto_detalle` |
| created_at | datetime | Requerido |
| updated_at | datetime | Requerido |

`gasto` representa la cabecera de un ticket de compra: fecha, lugar, ubicacion opcional y total.

### gasto_detalle

| Campo | Tipo | Reglas |
| --- | --- | --- |
| id | int | PK tecnica autoincremental |
| gasto_id | int | FK a `gasto.id` |
| motivo_gasto_id | int | FK a `motivo_gasto.id` |
| marca_id | int | FK a `marca.id` |
| descripcion | str null | Detalle libre del item comprado |
| cantidad | Decimal | NUMERIC |
| unidad_medida | str | Ej. `kg`, `unidad`, `litro` |
| precio_unitario | Decimal | NUMERIC |
| subtotal | Decimal | Snapshot calculado como `cantidad * precio_unitario` |

## Maquina de estados de pedido

Transiciones validas:

| Desde | Hacia |
| --- | --- |
| `PEDIDO` | `EN_PROCESO` |
| `PEDIDO` | `CANCELADO` |
| `PEDIDO` | `PENDIENTE_CONFIRMACION` |
| `PENDIENTE_CONFIRMACION` | `EN_PROCESO` |
| `PENDIENTE_CONFIRMACION` | `CANCELADO` |
| `EN_PROCESO` | `ENTREGADO` |
| `EN_PROCESO` | `CANCELADO` |

Estados terminales:

- `ENTREGADO`
- `CANCELADO`

Transiciones invalidas explicitas:

- `ENTREGADO` no vuelve a ningun estado anterior.
- `CANCELADO` no vuelve a ningun estado anterior.
- `PEDIDO` no salta directo a `ENTREGADO`.
- `PENDIENTE_CONFIRMACION` no salta directo a `ENTREGADO`.

## Reglas criticas para servicios

- Mayorista: se calcula por `regla_mayorista`. Si el total de unidades elegibles de la categoria alcanza `cantidad_minima_total`, cada item usa su precio de `precio_mayorista_producto`.
- Promociones: se calculan por grupo de productos elegibles antes de confirmar el pedido. Una promocion por cantidad puede reemplazar el precio base si la cantidad total del grupo cumple el minimo y no aplica una regla mayorista de mayor prioridad.
- Combos: una combinacion solo es valida si existe `combo_regla` para el par elegido.
- Confirmacion manual: si una `combo_regla` requiere confirmacion, el pedido inicia en `PENDIENTE_CONFIRMACION` y se genera link `wa.me/` con `urllib.parse.quote`.
- Precio historico: `pedido_item.precio_unitario` y `pedido.costo_envio` se copian desde catalogo/zona/regla vigente al crear el pedido.
- Total: `pedido.monto_total = suma(cantidad * precio_unitario) + costo_envio`.
- Cliente: upsert por telefono normalizado.
- Codigos: `PED-*` y `GAS-*` se generan de forma atomica, nunca calculando `max(id) + 1` en aplicacion sin proteccion.

## Ambiguedades detectadas

La separacion de promociones y mayorista quedo resuelta antes de implementar modelos:

- `producto.precio` es precio base.
- `promocion` + `promocion_producto` cubren promociones por cantidad sobre uno o mas productos elegibles.
- `regla_mayorista` define el minimo total elegible.
- `precio_mayorista_producto` define el precio mayorista por producto para esa regla.

No quedan ambiguedades bloqueantes para Fase 2 con los datos actuales.
