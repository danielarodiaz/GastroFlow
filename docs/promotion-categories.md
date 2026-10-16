# Promos por categoría y paquetes combinados

Antes de publicar esta versión de las apps pública e interna, ejecutar:

```powershell
python -m alembic upgrade head
```

La migración `0009_promotion_categories` agrega `promocion_categoria` y
`promocion_item`. No modifica pedidos históricos ni sus importes.

Las promos existentes con una categoría identificable por su código (`HORNO`,
`COMER`, `PRE_PIZZA` o `PREPIZZA`) se vinculan a esa categoría si todos sus
productos pertenecen a ella. Sin indicación en el código, solo se asigna cuando
existe una única categoría común a todos los productos. Las demás conservan sus
datos y quedan sin categoría: **no se aplican** hasta configurarlas en Promos.
La grilla y el editor muestran este estado para revisarlas.

## Promo por cantidad

En la gestión interna, abrir **Promos** y elegir una promo o crearla:

1. Seleccionar una o más **Categorías de la promo**, encima de Productos elegibles.
2. Elegir los productos, filtrados por esas categorías.
3. Completar cantidad mínima y precio unitario o precio total por grupo.
4. Guardar.

La promo se evalúa por separado dentro de cada categoría seleccionada. Una
Muzzarella de Horno y otra de Comer no completan un grupo de dos. Una promo
habilitada solamente en Horno nunca se aplica a la presentación de Comer.
Las unidades fuera de grupos completos mantienen el precio base.

## Paquete combinado

Para **2 muzzarellas de Horno + 3 prepizzas**:

1. Seleccionar Lista para hornear y Pre Pizzas.
2. Elegir Muzzarella y Prepizza.
3. Activar **Paquete combinado con cantidades por producto y categoría**.
4. Indicar 2 unidades de Muzzarella / Horno y 3 de Prepizza / Pre Pizzas.
   Si aparecen otras presentaciones de esos productos, dejarlas en 0.
5. Completar **Precio total del paquete** y guardar.

La cantidad mínima se obtiene de los componentes. El precio se aplica una sola
vez por paquete completo, incluso si sus productos pertenecen a categorías
diferentes. Cada sobrante se cobra al precio base. El total del paquete se
distribuye proporcionalmente entre los renglones con precisión de centavos,
sin cambiar el importe total, para conservar el detalle por producto del pedido.
El carrito y WhatsApp identifican el nombre de la promo aplicada.

Un paquete reemplaza otros descuentos de sus renglones solo si reduce el total;
no se acumulan dos promociones sobre el mismo renglón. Si varios paquetes
compiten, se prioriza el de mayor ahorro y luego los que no comparten renglones.
Mayorista, Eventos y mitad y mitad conservan sus reglas y no participan de estos
paquetes. La validación y el cálculo se realizan en el servidor al actualizar
el carrito y al confirmar el pedido.

## Verificación

```powershell
python -m pytest tests/test_promotion_scope.py tests/test_orders.py tests/test_public_catalog.py tests/test_public_checkout.py tests/test_internal_streamlit.py -q
```

Las pruebas verifican aislamiento de categorías, selección múltiple, composición
y sobrantes de paquetes, importes exactos, migración de promos existentes y el
guardado desde el editor de Streamlit.
