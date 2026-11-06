"""
Tests del panel. Se ejecutan sin dependencias extra, desde la raíz del repo:

    python -m unittest discover -s tests

Antes de importar nada del panel, SERVERS_PATH apunta a una carpeta temporal
para que ningún test toque los servidores de verdad.
"""
import os
import tempfile

os.environ["SERVERS_PATH"] = tempfile.mkdtemp(prefix="mcdeployer-tests-")
