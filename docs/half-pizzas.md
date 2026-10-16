# Mitad y mitad

En la ficha de una pizza, elegir **Mitad y mitad**, seleccionar el segundo sabor
y agregar la cantidad de pizzas completas al carrito. El precio se muestra
antes de agregar. Para Especial a $8.000 y Fugazzetta a $7.500, una pizza cuesta
$7.750.

Se habilita en Lista para hornear y Lista para comer cuando ambos sabores están
activos y visibles en la misma categoría y existe una regla en `combo_regla`.
La categoría seleccionada determina los dos precios. No existe ni se necesita
`combo_regla_categoria`.

El carrito agrupa una pareja sin importar el orden de selección y distingue
pizzas enteras, otras combinaciones y categorías diferentes. El pedido guarda
`producto_id` y `producto_combo_id`, y WhatsApp y la gestión interna muestran los
dos sabores. Una unidad equivale a una pizza completa para el umbral Mayorista.
Las promociones de pizzas enteras y los paquetes combinados no se aplican a
mitad y mitad. Mayorista usa el promedio de los dos precios mayoristas.

## Carga de combinaciones

Con los cinco productos activos en la base, ejecutar:

```powershell
python -m scripts.seed_half_pizzas
```

El script registra los 10 pares distintos de Muzzarella, Especial, Calabresa,
Fugazzetta y Napolitana, con regla `PROMEDIO`, sin precio fijo y sin confirmación
manual. Reutiliza reglas existentes aunque estén invertidas; ejecutarlo otra
vez no duplica filas. Acepta también la escritura Fugazzeta. Si falta un sabor
o hay nombres ambiguos, se detiene sin crear combinaciones parciales.

No agrega productos ni modifica sus precios. No requiere una nueva migración;
utiliza las columnas existentes de `combo_regla` y `pedido_item`.

La app pública carga las reglas con el catálogo y comparte esa lectura durante
30 segundos por proceso. La confirmación vuelve a validar las reglas y precios
contra la base.

## Pruebas

```powershell
python -m pytest tests/test_half_pizzas.py -q
```

Incluyen los 10 pares en ambas categorías, registro idempotente, validaciones
de disponibilidad, carrito, precios, promociones y persistencia del pedido.
