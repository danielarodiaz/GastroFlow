# Pedidos especiales

Fugazzetta y Napolitana en Lista para hornear y Eventos se ofrecen únicamente
desde **Consultar pedido especial**. Conservan el precio cargado en cada
categoría: no es un precio de referencia ni queda pendiente de negociación.
La única condición pendiente es que el local acepte la disponibilidad.

## Cliente

1. Entrar al catálogo de Horno o Eventos y elegir Consultar pedido especial.
2. Elegir el sabor y la cantidad. En Horno también se puede elegir mitad y mitad
   con otro sabor de la misma categoría, al promedio de los dos precios.
3. El carrito identifica los renglones especiales. Si alguno de los sabores
   de una mitad y mitad es especial, toda la pizza se considera especial.
4. Enviar la solicitud. El pedido completo queda pendiente de aceptación.

El mensaje final y WhatsApp explican que el precio es definitivo y que no se
debe pagar hasta que el local acepte la disponibilidad. En solicitudes especiales
no se muestran alias ni instrucciones para realizar transferencias.

Eventos mantiene el mínimo de 10 unidades sumando todos sus productos,
habituales y especiales. Los productos de otras categorías no cuentan.

Los especiales conservan el precio de su categoría de origen: no reciben
promociones ni se trasladan automáticamente a la tarifa Mayorista. Las pizzas
de Horno siguen contando como unidades completas para el umbral de su categoría;
los productos habituales mantienen sus reglas de precio existentes.

## Gestión interna

La lista de pedidos muestra **Pedido especial — Pendiente de aceptación de
disponibilidad**, y el detalle identifica los renglones especiales.

- **Aceptar disponibilidad** pasa el pedido a Pedido, conservando sus importes.
  Después puede pasar a preparación.
- **Rechazar solicitud** lo pasa a Cancelado sin eliminar sus datos.
- **Coordinar con el cliente por WhatsApp**, en el detalle, abre una conversación
  para acordar alternativas. No envía mensajes automáticamente ni modifica
  productos o precios del pedido.

Las solicitudes pendientes de aceptación no entran en el resumen de producción.
El servidor también impide pasar un pedido especial directamente de pendiente
de aceptación a preparación.

En Catálogo, editar la presentación y marcar **Permitir pedido especial (por
encargo)**. Esta opción la oculta del catálogo habitual. Desactivar Activo la
retira también de los pedidos especiales. Ocultar un producto sin habilitar
esta opción no autoriza su compra.

## Datos y despliegue

La migración `0010_special_orders` agrega `producto_categoria.permite_pedido_especial`
y `pedido_item.es_especial`. Habilita las cuatro presentaciones solicitadas y
conserva precios y pedidos históricos. Los renglones históricos comienzan con
la marca desactivada: no se infiere retroactivamente qué pedidos eran especiales.
La marca de un pedido nuevo queda guardada aunque cambie después el catálogo.

```powershell
python -m alembic upgrade head
python -m pytest tests/test_special_orders.py -q
```

Publicar tanto la app pública como la gestión interna con esta versión. La
lectura de catálogo puede mantener la configuración anterior durante 30 segundos
por proceso; al confirmar se vuelve a consultar y validar la base.
