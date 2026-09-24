"""Tests de la comparación contra auditorías humanas (fase 6)."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest

from jevqa.compare import (
    ErrorComparacion,
    a_markdown,
    comparar,
    kappa,
    matriz,
)
from jevqa.pipeline import cabecera_salida
from jevqa.rubric import load_rubric

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINTETICAS = os.path.join(RAIZ, "data", "eval", "sinteticas.csv")

C, N = True, False

RUBRICA = {
    "id": "mini",
    "version": "1",
    "items": [
        {"id": "respeto", "pregunta": "¿Trata con respeto?", "peso": 60, "critico": True},
        {"id": "cierre", "pregunta": "¿Se despide?", "peso": 40, "critico": False},
    ],
    "riesgo": {"pregunta": "¿Riesgo?", "niveles": ["Ninguno", "Alto"]},
    "motivo": {"pregunta": "¿Motivo?", "opciones": {"soporte": "Soporte", "otro": "Otro"}},
}


def rubrica(**umbrales) -> dict:
    datos = dict(RUBRICA)
    if umbrales:
        datos["umbrales"] = umbrales
    ruta = os.path.join(tempfile.mkdtemp(), "mini.json")
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False)
    return load_rubric(ruta)


def escribir(filas: list[dict], columnas: list[str]) -> str:
    ruta = os.path.join(tempfile.mkdtemp(), "datos.csv")
    with io.open(ruta, "w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta


def humano(etiquetas: dict[str, dict[str, bool | str]], columnas=("respeto", "cierre")) -> str:
    filas = []
    for ident, por_item in etiquetas.items():
        fila = {"id": ident}
        for item, valor in por_item.items():
            fila[item] = valor if isinstance(valor, str) else ("cumple" if valor else "no")
        filas.append(fila)
    return escribir(filas, ["id", *columnas])


def resultados(probabilidades: dict[str, dict[str, float]], rub: dict, *, errores=(), sin=()) -> str:
    columnas = [c for c in cabecera_salida(rub) if not any(c.startswith(f"{s}_") for s in sin)]
    filas = []
    for ident, por_item in probabilidades.items():
        fila = {"id": ident, "agente": "Rosa", "campaña": "telco", "fecha": "2026-08-03"}
        fila["estado"] = "error" if ident in errores else "ok"
        for item, p in por_item.items():
            fila[f"{item}_prob"] = p
            fila[f"{item}_conf"] = abs(2 * p - 1)
        filas.append(fila)
    return escribir(filas, columnas)


def jev(valor: bool) -> float:
    return 0.9 if valor else 0.1


class TestKappa(unittest.TestCase):
    def test_valor_conocido(self):
        # 10 pares, 8 de acuerdo; los dos dicen «cumple» 6 de 10 veces.
        # p_o = 0,8 · p_e = 0,6·0,6 + 0,4·0,4 = 0,52 · κ = 0,28 / 0,48 = 0,5833
        humano_ = [C, C, C, C, C, C, N, N, N, N]
        jev_ = [C, C, C, C, C, N, N, N, N, C]
        self.assertAlmostEqual(kappa(list(zip(humano_, jev_))), 0.28 / 0.48)

    def test_acuerdo_total_con_variacion(self):
        pares = [(C, C)] * 6 + [(N, N)] * 4
        self.assertEqual(kappa(pares), 1.0)

    def test_acuerdo_nulo(self):
        pares = [(C, N)] * 5 + [(N, C)] * 5
        self.assertEqual(kappa(pares), -1.0)

    def test_sin_variacion_no_esta_definido(self):
        # Los dos dicen siempre «cumple»: coinciden, pero no hay nada que medir.
        self.assertIsNone(kappa([(C, C)] * 8))

    def test_sin_pares(self):
        self.assertIsNone(kappa([]))

    def test_un_auditor_que_siempre_dice_cumple_tiene_kappa_cero(self):
        # 95 % de acuerdo sin mirar nada: el caso por el que existe el kappa.
        pares = [(C, C)] * 19 + [(N, C)]
        self.assertAlmostEqual(kappa(pares), 0.0)

    def test_matriz(self):
        celdas = matriz([(C, C), (C, C), (C, N), (N, C), (N, N)])
        self.assertEqual(
            celdas, {"cumple_cumple": 2, "cumple_no": 1, "no_cumple": 1, "no_no": 1}
        )


class TestComparar(unittest.TestCase):
    def setUp(self):
        self.rubrica = rubrica()

    def test_acuerdo_total(self):
        etiquetas = {f"I{i}": {"respeto": i % 2 == 0, "cierre": i % 3 == 0} for i in range(10)}
        r = comparar(
            humano(etiquetas),
            resultados({i: {k: jev(v) for k, v in e.items()} for i, e in etiquetas.items()}, self.rubrica),
            self.rubrica,
        )
        for item in ("respeto", "cierre"):
            self.assertEqual(r["items"][item]["acuerdo"], 1.0)
            self.assertEqual(r["items"][item]["kappa"], 1.0)
        self.assertEqual(r["global"]["acuerdo"], 1.0)
        self.assertEqual(r["interacciones_comparadas"], 10)

    def test_acuerdo_nulo(self):
        etiquetas = {f"I{i}": {"respeto": i % 2 == 0, "cierre": i % 2 == 1} for i in range(10)}
        r = comparar(
            humano(etiquetas),
            resultados({i: {k: jev(not v) for k, v in e.items()} for i, e in etiquetas.items()}, self.rubrica),
            self.rubrica,
        )
        for item in ("respeto", "cierre"):
            self.assertEqual(r["items"][item]["acuerdo"], 0.0)
            self.assertEqual(r["items"][item]["kappa"], -1.0)

    def test_kappa_esperado_de_extremo_a_extremo(self):
        humano_ = [C, C, C, C, C, C, N, N, N, N]
        jev_ = [C, C, C, C, C, N, N, N, N, C]
        ids = [f"I{i}" for i in range(10)]
        r = comparar(
            humano({i: {"respeto": h, "cierre": h} for i, h in zip(ids, humano_)}),
            resultados({i: {"respeto": jev(j), "cierre": jev(j)} for i, j in zip(ids, jev_)}, self.rubrica),
            self.rubrica,
        )
        self.assertAlmostEqual(r["items"]["respeto"]["kappa"], 0.28 / 0.48)
        self.assertEqual(r["items"]["respeto"]["matriz"]["no_cumple"], 1)

    def test_ids_humanos_que_no_estan_en_los_resultados(self):
        r = comparar(
            humano({"A": {"respeto": C, "cierre": C}, "B": {"respeto": N, "cierre": C}, "FALTA": {"respeto": C, "cierre": C}}),
            resultados({"A": {"respeto": 0.9, "cierre": 0.9}, "B": {"respeto": 0.1, "cierre": 0.9}, "EXTRA": {"respeto": 0.9, "cierre": 0.9}}, self.rubrica),
            self.rubrica,
        )
        self.assertEqual(r["ids_sin_resultado"], ["FALTA"])
        self.assertEqual(r["ids_solo_en_resultados"], ["EXTRA"])
        self.assertEqual(r["interacciones_comparadas"], 2)
        self.assertEqual(r["items"]["respeto"]["n"], 2)

    def test_ids_que_jev_no_pudo_auditar_se_listan_aparte(self):
        r = comparar(
            humano({"A": {"respeto": C, "cierre": C}, "B": {"respeto": C, "cierre": C}}),
            resultados({"A": {"respeto": 0.9, "cierre": 0.9}, "B": {"respeto": 0.9, "cierre": 0.9}}, self.rubrica, errores={"B"}),
            self.rubrica,
        )
        self.assertEqual(r["ids_con_error_en_jev"], ["B"])
        self.assertEqual(r["ids_sin_resultado"], [])
        self.assertEqual(r["interacciones_comparadas"], 1)

    def test_item_que_falta_en_el_csv_humano(self):
        r = comparar(
            humano({"A": {"respeto": C}}, columnas=("respeto",)),
            resultados({"A": {"respeto": 0.9, "cierre": 0.9}}, self.rubrica),
            self.rubrica,
        )
        self.assertEqual(list(r["items"]), ["respeto"])
        self.assertEqual(r["items_sin_comparar"], [{"item": "cierre", "falta_en": "humano"}])

    def test_item_que_falta_en_los_resultados(self):
        r = comparar(
            humano({"A": {"respeto": C, "cierre": C}}),
            resultados({"A": {"respeto": 0.9}}, self.rubrica, sin={"cierre"}),
            self.rubrica,
        )
        self.assertEqual(list(r["items"]), ["respeto"])
        self.assertEqual(r["items_sin_comparar"], [{"item": "cierre", "falta_en": "resultados"}])

    def test_sin_ningun_item_en_comun(self):
        with self.assertRaises(ErrorComparacion):
            comparar(
                humano({"A": {"otro": C}}, columnas=("otro",)),
                resultados({"A": {"respeto": 0.9, "cierre": 0.9}}, self.rubrica),
                self.rubrica,
            )

    def test_etiquetas_vacias_o_ilegibles_quedan_fuera(self):
        r = comparar(
            humano({"A": {"respeto": C, "cierre": ""}, "B": {"respeto": "tal vez", "cierre": N}}),
            resultados({"A": {"respeto": 0.9, "cierre": 0.9}, "B": {"respeto": 0.9, "cierre": 0.1}}, self.rubrica),
            self.rubrica,
        )
        self.assertEqual(r["items"]["respeto"]["n"], 1)
        self.assertEqual(r["items"]["cierre"]["n"], 1)
        self.assertEqual(len(r["etiquetas_invalidas"]), 2)

    def test_usa_el_umbral_por_item_de_la_rubrica(self):
        # Con 0,6 de probabilidad, el umbral general (0,5) dice «cumple»; si la
        # rúbrica sube el de `respeto` a 0,7, dice «no» y coincide con el humano.
        estricta = rubrica(cumple_respeto=0.7)
        h = humano({"A": {"respeto": N, "cierre": C}})
        j = resultados({"A": {"respeto": 0.6, "cierre": 0.9}}, estricta)
        self.assertEqual(comparar(h, j, self.rubrica)["items"]["respeto"]["acuerdo"], 0.0)
        self.assertEqual(comparar(h, j, estricta)["items"]["respeto"]["acuerdo"], 1.0)

    def test_archivo_que_no_existe(self):
        with self.assertRaises(ErrorComparacion):
            comparar(os.path.join(tempfile.mkdtemp(), "no.csv"), SINTETICAS, self.rubrica)

    def test_markdown_con_todas_las_secciones(self):
        r = comparar(
            humano({"A": {"respeto": C, "cierre": C}, "FALTA": {"respeto": C, "cierre": C}}),
            resultados({"A": {"respeto": 0.9, "cierre": 0.9}}, self.rubrica),
            self.rubrica,
        )
        md = a_markdown(r)
        for seccion in ("Acuerdo y kappa por ítem", "Matriz de confusión", "Lo que quedó fuera"):
            self.assertIn(seccion, md)
        self.assertIn("`FALTA`", md)
        self.assertIn("por debajo de las 100", md)


class TestCLI(unittest.TestCase):
    def test_comparar_las_sinteticas(self):
        from jevqa.__main__ import main

        carpeta = tempfile.mkdtemp()
        salida_auditar = os.path.join(carpeta, "resultados.csv")
        comparacion = os.path.join(carpeta, "comparacion.md")
        self.assertEqual(main(["auditar", SINTETICAS, "--salida", salida_auditar, "--fake"]), 0)
        self.assertEqual(
            main(["comparar", SINTETICAS, salida_auditar, "--salida", comparacion, "--fake"]), 0
        )
        with open(comparacion, encoding="utf-8") as archivo:
            contenido = archivo.read()
        self.assertIn("Interacciones comparadas: **40**", contenido)
        for item in load_rubric(os.path.join(RAIZ, "rubrics", "soporte_es.json"))["items"]:
            self.assertIn(f"`{item['id']}`", contenido)


if __name__ == "__main__":
    unittest.main()
