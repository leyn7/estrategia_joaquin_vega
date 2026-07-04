# -*- coding: utf-8 -*-
"""Configuración central del bot MDT — único lugar con parámetros de operación.

Los NÚMEROS DE LA BIBLIA (fibo) también viven aquí con nombre: no son ajustables
(son la estrategia), pero nombrarlos una sola vez evita typos al usarlos.
"""

# --- Mercado ---
SYMBOL = "BNBUSDT"           # futuros USDT-M de Binance (feed fapi: último trade)
TZ_LOCAL = "America/Bogota"  # zona horaria del operador (COT)

# --- Análisis de muñecas rusas (Sección 2): origen del ciclo macro alcista ---
# Mínimo de junio 2022 en ~183 USDT. Se localiza la ÚLTIMA vela diaria cuyo low
# cae en la banda. Si se cambia de símbolo, este análisis debe rehacerse a mano.
ORIGEN_MACRO_BANDA = (182.0, 183.5)

# --- Cascada de temporalidades del mapa (Regla 1: siempre termina en 1m) ---
TF_LADDER = ["1d", "2h", "30m", "3m", "1m"]
TF_MINUTOS = {"1d": 1440, "4h": 240, "2h": 120, "1h": 60, "30m": 30, "15m": 15, "3m": 3, "1m": 1}
MIN_VELAS_TF = 40            # una TF con menos velas que esto no aporta estructura
MAX_VELAS_DESCARGA = 15000   # presupuesto de velas por descarga (1m -> ~10 días de cola)

# --- TF del patrón (Secc 10): "bajar UNA temporalidad por debajo del tamaño
# del ciclo que se está trabajando" (ej. de la biblia: ciclo H1 -> patrón M30 —
# UN escalón real, no un salto de 12x). La TF del ciclo es donde se halló su
# ancla. Regla del usuario (4 jul): la escala del patrón y la del ciclo van
# juntas — el stop de una oportunidad macro es de tamaño macro.
TF_PATRON = {"1d": "4h", "2h": "1h", "30m": "15m", "3m": "1m", "1m": "1m"}

# --- Capa operativa (regla usuario 3 jul 2026) ---
# Ciclo OPERABLE = grado >= 1% del precio actual (el macro siempre es operable).
# Los sub-operables viven en el motor (desgrane/pendientes) sin zonas operativas.
GRADO_MIN_OPERABLE_PCT = 0.01

# --- Gestión monetaria (Secc 1) ---
RATIO_MINIMO = 4.0   # Ratio Riesgo/Beneficio mínimo estricto 1:4
MAX_OPS_DIA = 4      # Límite operativo diario (capa de ejecución, aún sin bucle en vivo)

# --- Números de la biblia (NO tocar: son la estrategia) ---
ZONA_191 = 0.191     # tamaño de cada zona de trabajo (Secc 4)
NIVEL_382 = 0.382    # activación del ciclo / extensiones de muerte ±38.2 (Secc 3 y 6)
NIVEL_618 = 0.618    # zona media / RESET / retroceso de seguimiento (Secc 4, 7)
NIVEL_809 = 0.809    # límite exterior de la zona media / de seguimiento (Secc 4, 16)
ENGANO_1382 = 1.382  # inicio de la Zona de Engaños (Secc 10)
ENGANO_1618 = 1.618  # fin de la Zona de Engaños: consumo obligatorio (Secc 10-12)
