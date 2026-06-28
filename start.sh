#!/bin/bash
# Limpiar __pycache__ para evitar módulos en caché desactualizados
find "$(dirname "$0")" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
cd "$(dirname "$0")"
python3 main.py
