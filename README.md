# Analista de disponibilidad

Herramienta personal para vigilar el stock de perfumes de la tienda **The Fragrance** en
[walmart.com.mx](https://www.walmart.com.mx) y avisar por Telegram cuando un producto agotado
vuelva a estar disponible. La idea era correrla con un cron en GitHub Actions.

> **Estado: en pausa.** La prueba de viabilidad mostró que Walmart bloquea a GitHub Actions con
> su protección anti-bots. Solo existe la prueba de viabilidad (probe); el vigilante no se construyó.

## Resultado de la prueba de viabilidad

El probe abrió los 3 productos de `products.yaml` desde GitHub Actions. **Las 3 páginas fueron
bloqueadas**:

| Producto | HTTP | Veredicto | Título de la página |
|---|---|---|---|
| Goodgirl 80 ml EDP Spray | 200 | ⛔ blocked | Verifica tu identidad |
| Carolina Herrera Very Good Girl EDP 80 ml | 200 | ⛔ blocked | Verifica tu identidad |
| Sauvage Parfum 100 ml EDP (Dior) | 200 | ⛔ blocked | Verifica tu identidad |

En lugar del producto, Walmart sirve su página de protección (PerimeterX, "Mantén presionado el
botón para confirmar que no eres un robot"). Ojo: la responde con **HTTP 200**, así que el
código HTTP por sí solo no sirve para detectar el bloqueo; el probe lo detecta por el texto
de la página.

Causa probable: GitHub Actions usa IPs de centros de datos, que Walmart bloquea.

Por decisión del proyecto **no** se usan proxies, ni se resuelven CAPTCHAs, ni se intenta evadir
el bloqueo.

## Qué hay en el repo

| Archivo | Qué hace |
|---|---|
| `products.yaml` | Productos a vigilar y vendedor (`seller_name`). Se edita a mano. |
| `scripts/analista_de_disponibilidad_probe.py` | Abre cada URL con Playwright (Chromium) y guarda HTML, screenshot y metadatos. Al final marca cada página como `ok` / `blocked` / `empty` / `error`. |
| `.github/workflows/analista-de-disponibilidad-probe.yml` | Corre el probe en GitHub Actions, solo de forma manual. |
| `requirements.txt` | Playwright, PyYAML, python-dotenv y httpx. |

### `products.yaml`

```yaml
seller_name: "The Fragrance"   # solo cuentan las ofertas de este vendedor

products:
  - name: "Goodgirl 80 ml EDP Spray"
    url: "https://www.walmart.com.mx/ip/good-girl-80-ml-edp-spray/00046064599687"
    offer_filter: "any"          # any | walmart_fulfilled | seller_fulfilled
    notify_price_drop: false
```

- `walmart_fulfilled`: "Vendido por The Fragrance, enviado por Walmart".
- `seller_fulfilled`: "Vendido y enviado por The Fragrance".
- Si un producto está disponible pero lo vende Walmart u otra tienda, cuenta como **no
  disponible**.

## Cómo correr el probe

El probe es cortés: revisa un producto a la vez, espera entre 5 y 15 s al azar entre
productos, usa un solo contexto de navegador y no reintenta. Siempre termina en verde; el
veredicto queda en el resumen.

### En GitHub Actions

1. Ve a **Actions** → **analista-de-disponibilidad · probe** → **Run workflow**.
2. Al terminar, la tabla de resultados aparece en el resumen del run.
3. El artifact **analista-de-disponibilidad-probe** trae, por producto, `page.html`,
   `screenshot.png` y `meta.json`.

### En local (Windows o WSL)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      WSL/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # en WSL: python -m playwright install --with-deps chromium

python scripts/analista_de_disponibilidad_probe.py            # resultados en probe_output/
python scripts/analista_de_disponibilidad_probe.py --headed   # muestra el navegador
```

## Si se retoma el proyecto

No se ha probado desde una conexión de casa (IP residencial). Antes de construir nada más,
corre el probe en local:

- **Si sale `ok`:** se puede seguir con la versión local, usando el Programador de tareas de
  Windows o cron en WSL. Otra opción es un *runner self-hosted* de GitHub Actions en la PC: el
  cron sigue en GitHub, pero el navegador sale desde la IP de casa. En ambos casos la PC tiene
  que estar prendida.
- **Si también sale `blocked`:** Walmart bloquea el navegador automatizado sin importar la IP,
  y no hay forma limpia de seguir con Walmart como fuente.

Pendiente menor: `actions/checkout@v4`, `actions/setup-python@v5` y
`actions/upload-artifact@v4` usan Node 20, que GitHub ya marca como obsoleto. Conviene
actualizarlas si se vuelve a usar el workflow.
