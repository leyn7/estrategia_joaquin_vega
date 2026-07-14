# -*- coding: utf-8 -*-
"""Bot MDT en vivo: bucle de escaneo + alertas a Telegram.

Este archivo es solo la ORQUESTACIÓN. Cada pieza vive en su módulo:
  mdt_estado.py    estado persistente (con backup) + caché de velas
  mdt_formato.py   textos de los mensajes
  mdt_ops.py       operaciones reales (gatillos ejecutados + gestión Secc 20)
  mdt_eventos.py   qué cambió y qué se notifica (dedup) + anclas del operador
  mdt_comandos.py  comandos de Telegram

El ciclo: escanear cada símbolo (mapa global + tramos), detectar eventos nuevos,
avisar; luego re-mapear las anclas marcadas por el operador; y en la ventana que
queda hasta el próximo escaneo, atender comandos.

Prueba local sin token (los mensajes salen por consola):
  python mdt_vivo.py --una-pasada
"""
import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('mdt.vivo')

import mdt_telegram
# OJO: mdt_estado debe importarse ANTES que el escáner — al importarse parchea
# el feed con la caché de velas (si no, cada escaneo re-descarga meses de 1m).
from mdt_estado import INTERVALO, RUTA_ESTADO, cargar_estado, guardar_estado
from mdt_comandos import procesar_comandos
from mdt_escaner import escanear_completo
from mdt_eventos import detectar_eventos, vigilar_anclas, vigilar_rsi3m


def escanear_simbolos(estado, tolerar_fallos=True):
    """Escanea la watchlist y envía los eventos nuevos de cada símbolo."""
    for sym in list(estado['watchlist']):
        mem = estado['simbolos'].setdefault(sym, {})
        try:
            resultado = escanear_completo(verbose=False, symbol=sym)
            for ev in detectar_eventos(sym, resultado, mem):
                log.info("evento %s: %s", sym, ev.splitlines()[0])
                mdt_telegram.enviar(estado.get('chat_id'), ev)
        except Exception:  # noqa: BLE001 — el bucle jamás muere por un símbolo
            if not tolerar_fallos:
                raise
            log.exception("escaneo %s falló; se reintenta en el próximo ciclo", sym)
        guardar_estado(estado)


def revisar_anclas(estado):
    """Anclas marcadas por el operador: avisa si el precio entró en sus zonas, y
    las señales de la rsi_3m en las anclas donde él pidió esa estrategia."""
    for nombre, vigilar in (("anclas", vigilar_anclas), ("rsi3m", vigilar_rsi3m)):
        try:
            for ev in vigilar(estado):
                log.info("evento %s: %s", nombre, ev.splitlines()[0])
                mdt_telegram.enviar(estado.get('chat_id'), ev)
        except Exception:  # noqa: BLE001 — una vigilancia rota no tumba el bucle
            log.exception("vigilancia de %s falló", nombre)
    guardar_estado(estado)


def una_pasada(estado):
    escanear_simbolos(estado, tolerar_fallos=False)
    revisar_anclas(estado)


def main():
    ap = argparse.ArgumentParser(description="Bot MDT en vivo (escaneo + Telegram)")
    ap.add_argument("--una-pasada", action="store_true",
                    help="un solo escaneo de la watchlist y salir (prueba local)")
    args = ap.parse_args()

    estado = cargar_estado()
    log.info("watchlist %s | intervalo %ss | estado en %s",
             estado['watchlist'], INTERVALO, RUTA_ESTADO)

    if args.una_pasada:
        una_pasada(estado)
        return

    if not mdt_telegram.TOKEN:
        log.warning("MDT_TG_TOKEN vacío: los mensajes saldrán solo al log. "
                    "Crear el bot en @BotFather y ponerlo en el .env")

    while True:
        inicio = time.time()
        escanear_simbolos(estado)
        revisar_anclas(estado)
        # Ventana de comandos hasta el próximo escaneo (long-poll de Telegram)
        while time.time() - inicio < INTERVALO:
            if mdt_telegram.TOKEN:
                procesar_comandos(estado)
            else:
                time.sleep(30)
        guardar_estado(estado)


if __name__ == "__main__":
    main()
