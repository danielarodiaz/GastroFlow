# Fecha y horario de entrega

Los separadores se agregan en el navegador en cada evento de entrada, sin esperar
al servidor: `1910` se muestra como `19-10` y `2115` como `21:15`.

Los componentes `delivery_date_input` y `delivery_time_input` usan inputs nativos
sin control de valor por el servidor. El texto se sincroniza al salir del campo;
al confirmar, el formulario lee el valor actual del DOM, aunque todavía no se
haya enviado ese evento. Una respuesta demorada no puede sustituir una edición.
Los componentes impiden configurar `value` u `on_change` para no reintroducir ese
problema: se utilizan `default_value` y `on_blur`.

La máscara mantiene la posición del cursor, acepta reemplazos y permite borrar
sin insertar automáticamente año ni minutos. El servidor conserva la validación
de fechas y horarios y completa el año opcional o los minutos omitidos solo al
confirmar.

La máscara JavaScript es un archivo de la app, sin dependencias adicionales de
producción. Se registra mediante un efecto de React que también atiende el
montaje condicional del formulario del carrito y retira sus eventos al desmontar.

```powershell
python -m pytest tests/test_delivery_mask_browser.py tests/test_public_checkout.py -q
```

Las pruebas de navegador requieren Playwright con Chromium o Microsoft Edge.
Verifican el mismo JavaScript que utiliza el componente: escritura rápida y
lenta, pausas, salida del campo, borrado, cursor, sustitución de dígitos,
respuestas demoradas y envío con Enter sin salir del campo. Si el entorno no
tiene navegador, estas pruebas se omiten; las de integración del componente y
del backend se siguen ejecutando.
