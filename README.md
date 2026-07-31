# Polymarket Alpha Engine

MVP completo para descubrir mercados líquidos, investigarlos con IA y noticias actuales, estimar probabilidad justa, calcular valor esperado neto de fricción y abrir **solo operaciones simuladas**.

## Qué incluye

- Descubrimiento de mercados mediante Gamma API.
- Filtros por liquidez, volumen, spread y precio.
- Investigación con OpenAI Responses API + búsqueda web.
- Estimación estructurada de probabilidad, confianza, tesis y contra-tesis.
- Ranking por edge, confianza y liquidez.
- Tamaño de posición con cuarto de Kelly y límites duros.
- SQLite con snapshots, análisis y posiciones paper.
- Prevención de posiciones duplicadas.
- CLI, scripts de instalación/ejecución, tests y CI.

## Instalación en Ubuntu

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
./scripts/bootstrap.sh
nano .env
```

Añade `OPENAI_API_KEY` en `.env`. Sin clave funciona en modo conservador para validar la tubería, pero no generará señales reales porque la estimación coincide con el mercado.

## Simular

```bash
./scripts/simulate.sh
```

Escaneo sin abrir operaciones paper:

```bash
./scripts/scan_only.sh
```

Estado:

```bash
source .venv/bin/activate
alpha-engine status
```

## Automatización cada 15 minutos

```bash
crontab -e
*/15 * * * * cd /ruta/polymarket-alpha-engine && ./scripts/simulate.sh >> data/engine.log 2>&1
```

## Seguridad

Este repositorio no contiene claves privadas ni ejecución real de órdenes. No conectes fondos hasta disponer de una muestra amplia de predicciones resueltas, calibración, costes reales y límites de pérdida.

## Próxima fase necesaria para validar rentabilidad

La primera versión captura oportunidades futuras. Para evaluar ventaja real hay que:
1. mantenerla ejecutándose durante semanas;
2. cerrar posiciones cuando el mercado resuelva;
3. medir Brier score, calibración, ROI, drawdown y resultados por categoría;
4. comparar contra el precio de mercado como benchmark.
