# -*- coding: utf-8 -*-
"""Doble Suelo/Techo con Impulso (Sección 18).

El patrón que nace cuando el giro NO llega a los niveles de engaño: la Pauta 3
se queda corta (ni siquiera toca el 138.2) y el precio se va en contra rompiendo
la Pauta 2 con fuerza. Ahí el engaño se abandona y manda el impulso nuevo.

Espacio canónico (semántica SELL); ver mdt_canonico.py.
"""
from mdt_config import NIVEL_618, NIVEL_809


def doble_techo_impulso(df, HI, LO, r, palabras, idx_ruptura, dilatacion, extremo, detalles):
    """Patrón de Doble Suelo/Techo con Impulso (Sección 18). Contexto ya validado:
    la P3 nunca llegó a los niveles de engaño (ni al 138.2) y el precio rompió el
    extremo de la Pauta 2 por >= 1/3 de la altura de esa Pauta 2 (regla del tercio).

    El Fibo de Entrada se descarta. Fibo de seguimiento DINÁMICO a todo el nuevo
    impulso: desde la máxima dilatación (mecha absoluta en la base de la Pauta 3,
    donde va el SL) hasta el extremo corrido de la rotura. No existe entrada
    agresiva: se entra al toque de la zona del 61.8 (retroceso del impulso).
    Muerte: el precio tiene prohibido volver a tocar la máxima dilatación.
    """
    detalles["calidad"] = "DOBLE TECHO/SUELO CON IMPULSO (Secc 18)"
    detalles["dilatacion_maxima"] = r(dilatacion)
    ext = extremo
    for i in range(idx_ruptura + 1, len(df)):
        if HI[i] >= dilatacion:
            return {"estado": "ROTO_POR_RETESTEO_DILATACION",
                    "mensaje": f"Retesteó la máxima dilatación ({r(dilatacion):.2f}): patrón roto, nuevo análisis.",
                    "detalles": detalles, "idx_muerte": i}
        if LO[i] < ext:
            ext = LO[i]
        imp = dilatacion - ext
        n618 = ext + imp * NIVEL_618
        if HI[i] >= n618:
            detalles.update({"impulso_dt": imp, "extremo_impulso": r(ext),
                             "entrada_dt_618": r(n618), "limite_gestion_809": r(ext + imp * NIVEL_809),
                             "stop_loss": r(dilatacion), "hora_gatillo": df.loc[i, 'open_time']})
            # Verificación post-gatillo (Secc 18): prohibido retestear la dilatación
            for k in range(i + 1, len(df)):
                if HI[k] >= dilatacion:
                    return {"estado": "ROTO_POR_RETESTEO_DILATACION",
                            "mensaje": "Retesteó la máxima dilatación tras el gatillo (SL).",
                            "detalles": detalles, "idx_muerte": k}
            return {"estado": "DT_IMPULSO_GATILLO",
                    "mensaje": f"{palabras['dt']} con Impulso: toque del 61.8 en {r(n618):.2f}. "
                               f"{palabras['accion']} a mercado. SL {r(dilatacion):.2f}",
                    "detalles": detalles}
    imp = dilatacion - ext
    n618 = ext + imp * NIVEL_618
    detalles.update({"impulso_dt": imp, "extremo_impulso": r(ext),
                     "entrada_dt_618": r(n618), "limite_gestion_809": r(ext + imp * NIVEL_809),
                     "stop_loss": r(dilatacion)})
    return {"estado": "DT_IMPULSO_ESPERANDO",
            "mensaje": f"{palabras['dt']} con Impulso. Esperando retroceso al 61.8 ({r(n618):.2f}, "
                       f"zona hasta {r(ext + imp * NIVEL_809):.2f}). SL {r(dilatacion):.2f}",
            "detalles": detalles}
