# -*- coding: utf-8 -*-
"""Configuración central del bot MDT — único lugar con parámetros de operación.

Los NÚMEROS DE LA BIBLIA (fibo) también viven aquí con nombre: no son ajustables
(son la estrategia), pero nombrarlos una sola vez evita typos al usarlos.
"""
import os

# --- Mercado ---
SYMBOL = "BNBUSDT"           # símbolo por defecto; todo el pipeline acepta --symbol
TZ_LOCAL = "America/Bogota"  # zona horaria del operador (COT)

# --- Análisis de muñecas rusas (Sección 2): origen del ciclo macro alcista ---
# El mapa lo deriva AUTOMÁTICAMENTE del diario (derivar_estructura_macro): cada
# retroceso que supera el 61.8% del impulso corrido SELLA el fractal y re-funda
# el origen en el fondo de ese retroceso; el origen macro es la re-fundación con
# el impulso más grande hasta el ATH ("el impulso mayor absoluto del gráfico").
# Para BNBUSDT reproduce el análisis manual validado (182.97 @ 2022-06-18).
# La biblia dice que CUALQUIER muñeca es un origen 100% correcto (elección del
# operador): si se prefiere otra, fijar aquí una banda (low_min, low_max) del
# low diario por símbolo — la banda manual manda sobre la derivación.
ORIGENES_MACRO_MANUAL = {}   # ej.: {"BNBUSDT": (182.0, 183.5)}

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

# Lupa máxima del patrón. El BOT AUTOMÁTICO respeta la escalera de la Secc 10
# (None): meterle la lupa fina le daba stops de lotería — una zona macro con el
# objetivo a 50 puntos operada con un SL de 0.77 (R:B 1:67), que cualquier mecha
# de ruido salta. Su propia regla del 4 jul lo dice: el stop de una oportunidad
# macro es de tamaño macro.
# La lupa fina (3m) es SOLO para lo que el operador pide a mano — sus anclas —,
# donde él elige el contexto y opera intradía: ahí "en 15m se pierden muchos
# detalles internos" (regla usuario 13 jul). Ver TF_ANCLA_FINA en mdt_escaner.
TF_PATRON_MAX = os.environ.get("MDT_TF_PATRON_MAX") or None

# --- Capa operativa (regla usuario 3 jul 2026) ---
# Ciclo OPERABLE = grado >= 1% del precio actual (el macro siempre es operable).
# Los sub-operables viven en el motor (desgrane/pendientes) sin zonas operativas.
GRADO_MIN_OPERABLE_PCT = 0.01

# --- Gestión monetaria (Secc 1 y 20) ---
# Video GESTIÓN EN BENEFICIO: "nunca entraremos a mercado a por operaciones que
# al menos no nos den un 1 a 3" — el 1:4 del resumen viejo era una de las combos
# (parcial 1:2 -> final 1:4), no el mínimo de entrada.
# --- QUÉ PATRONES SE OPERAN (decisión 14 jul, con el backtest del año delante) ---
# Un año de walk-forward (1.356 operaciones con ratio 1:3), segmentado por la
# familia que el propio patrón se pone al nacer (no por cómo acabó):
#   ENTRADA PROFUNDA (Secc 16): 695 ops | +507.8R | +0.73R por operación  <- el motor
#   ENGAÑO EXTREMO   (Secc 17): 523 ops | +143.5R | +0.27R                <- rentable
#   ENGAÑO 3 PAUTAS  (Secc 9-13): 85 ops | -14.2R | -0.17R    <- PIERDE dinero
#   DOBLE TECHO/SUELO (Secc 18):  53 ops | -15.7R | -0.30R    <- PIERDE dinero
# El bot es rentable A PESAR del engaño clásico de 3 Pautas, no gracias a él. Se
# operan solo las dos familias del "engaño profundo" (nombre del usuario).
# Para volver a operarlas todas: MDT_FAMILIAS="ENTRADA PROFUNDA,ENGAÑO EXTREMO,ENGAÑO 3 PAUTAS,DOBLE TECHO/SUELO"
FAMILIAS_OPERABLES = tuple(
    f.strip() for f in os.environ.get(
        "MDT_FAMILIAS", "ENTRADA PROFUNDA,ENGAÑO EXTREMO").split(",") if f.strip())

RATIO_MINIMO = 3.0   # Ratio Riesgo/Beneficio mínimo de ENTRADA (1:3)
PARCIAL_R = 2.0      # Punto de descarga de presión (parcial mínimo 1:2, Secc 20)
FINAL_R = 4.0        # Objetivo final = doble del parcial (perfil estándar 1:2 -> 1:4)
MAX_OPS_DIA = 4      # Límite operativo diario (capa de ejecución, aún sin bucle en vivo)

# Comisión de ida y vuelta (taker a la entrada + taker a la salida, 0.05% c/u).
# No es un detalle: SUMA a lo que pierdes en el stop y RESTA de lo que ganas en
# el TP, así que un 1:3 bruto puede no ser un 1:3 real (regla usuario 14 jul:
# "que cuando sea 1:3 verdaderamente sea 1:3, no que las comisiones nos resten").
COMISION_IDA_VUELTA = 0.001

# SL más cerca que esto (% de la entrada): las comisiones se comen el riesgo antes
# de que el trade respire. Lo que pesa NO es cuántos dólares arriesgues, sino lo
# ceñido que sea el stop en PORCENTAJE: la comisión se lleva 0.1%/riesgo_pct de tu
# riesgo. Con 0.35% se llevaba el 29% de cada pérdida; con 0.5% se lleva el 20%
# (regla usuario 14 jul: "la idea es que las operaciones sean rentables").
#   SL 0.09% -> comisión = 111% del riesgo (la comisión sola supera al stop)
#   SL 0.35% -> 29%   |   SL 0.50% -> 20%   |   SL 1% -> 10%   |   SL 2% -> 5%
MIN_RIESGO_PCT = 0.005

# --- Ejecución real (Testnet) — regla usuario 14 jul: "que operen como si
# fueran reales, sin meter dinero" ---
# 'observacion' (default): el bot sigue exactamente igual que siempre, esta
#   capa no se llama nunca.
# 'testnet': cada gatillo nuevo coloca ÓRDENES REALES en Binance Futures
#   TESTNET (saldo ficticio, motor de matching real) — ver mdt_ejecutor.py.
#   La decisión de cuándo entrar/salir la sigue dando mdt_gestion (ya
#   validada); esta capa solo la REPRODUCE con órdenes reales.
MDT_MODO = os.environ.get('MDT_MODO', 'observacion').lower()
BALANCE_VIRTUAL_INICIAL = float(os.environ.get('MDT_BALANCE_INICIAL', '1000'))
RIESGO_CUENTA_PCT = float(os.environ.get('MDT_RIESGO_PCT', '0.01'))

# --- Preferencia operativa (usuario, 4 jul 2026) ---
# "Yo no trabajaría una zona macro, tardaría mucho en darme profit; prefiero
# trabajar las zonas pequeñas que me den oportunidades de entrada y sean
# rentables. Las zonas macro siempre van a tener oportunidades en sus zonas
# pequeñas." Las zonas más anchas que este % del precio son CONTEXTO (dirección,
# mapa) — no se operan; sus oportunidades llegan por los sub-ciclos de adentro.
ZONA_MAX_OPERABLE_PCT = 0.05

# --- Números de la biblia (NO tocar: son la estrategia) ---
ZONA_191 = 0.191     # tamaño de cada zona de trabajo (Secc 4)
NIVEL_382 = 0.382    # activación del ciclo / extensiones de muerte ±38.2 (Secc 3 y 6)
NIVEL_618 = 0.618    # zona media / RESET / retroceso de seguimiento (Secc 4, 7)
NIVEL_809 = 0.809    # límite exterior de la zona media / de seguimiento (Secc 4, 16)
ENGANO_1382 = 1.382  # inicio de la Zona de Engaños (Secc 10)
ENGANO_1618 = 1.618  # fin de la Zona de Engaños: consumo obligatorio (Secc 10-12)
