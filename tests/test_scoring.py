import unittest

from jevqa import scoring

ITEMS = [
    {"id": "saludo", "pregunta": "¿saluda?", "peso": 0.1, "critico": False},
    {"id": "escucha", "pregunta": "¿escucha?", "peso": 0.15, "critico": False},
    {"id": "resolucion", "pregunta": "¿resuelve?", "peso": 0.3, "critico": False},
    {"id": "trato_respetuoso", "pregunta": "¿trato respetuoso?", "peso": 0.25, "critico": True},
    {"id": "proteccion_datos", "pregunta": "¿protege datos?", "peso": 0.1, "critico": True},
    {"id": "despedida", "pregunta": "¿se despide?", "peso": 0.1, "critico": False},
]

ITEM_IDS = [item["id"] for item in ITEMS]


def rubric(umbrales=None):
    r = {"items": [dict(item) for item in ITEMS]}
    if umbrales is not None:
        r["umbrales"] = umbrales
    return r


def fila(id_, agente="ana", campaña="soporte", estado="ok", probabilidades=None, **extra):
    d = {"id": id_, "agente": agente, "campaña": campaña, "estado": estado}
    probabilidades = probabilidades or {}
    for item_id in ITEM_IDS:
        d[item_id] = probabilidades.get(item_id, 0.9)
    d.update(extra)
    return d


class TestUmbralesDe(unittest.TestCase):
    def test_por_defecto(self):
        self.assertEqual(scoring.umbrales_de(rubric()), scoring.DEFAULT_UMBRALES)

    def test_override_parcial(self):
        u = scoring.umbrales_de(rubric({"confianza": 0.5}))
        self.assertEqual(u["confianza"], 0.5)
        self.assertEqual(u["aprobado"], scoring.DEFAULT_UMBRALES["aprobado"])

    def test_clave_desconocida(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.umbrales_de(rubric({"otro": 1}))

    def test_min_mayor_que_max(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.umbrales_de(rubric({"dudosa_min": 0.7, "dudosa_max": 0.6}))

    def test_valor_booleano(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.umbrales_de(rubric({"confianza": True}))

    def test_confianza_fuera_de_rango(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.umbrales_de(rubric({"confianza": 1.5}))

    def test_aprobado_fuera_de_rango(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.umbrales_de(rubric({"aprobado": 150}))


class TestPuntuar(unittest.TestCase):
    def test_todo_cumple(self):
        r = scoring.puntuar(rubric(), fila("1"))
        self.assertEqual(r["nota"], 100.0)
        self.assertEqual(r["estado"], "aprobado")
        self.assertEqual(r["criticos_fallidos"], [])
        self.assertFalse(r["revision"])

    def test_falla_critico_nota_alta_igual_suspenso(self):
        probs = {item_id: 0.9 for item_id in ITEM_IDS}
        probs["trato_respetuoso"] = 0.1
        r = scoring.puntuar(rubric(), fila("1", probabilidades=probs))
        self.assertEqual(r["estado"], "suspenso")
        self.assertIn("trato_respetuoso", r["criticos_fallidos"])
        # nota ponderada: 100 - 25 (peso de trato_respetuoso) = 75
        self.assertEqual(r["nota"], 75.0)

    def test_falla_no_critico_baja_nota_bajo_aprobado(self):
        probs = {item_id: 0.9 for item_id in ITEM_IDS}
        probs["resolucion"] = 0.1  # peso 0.3 -> nota 70, igual al umbral
        probs["escucha"] = 0.1  # peso 0.15 -> nota final 55, bajo el umbral
        r = scoring.puntuar(rubric(), fila("1", probabilidades=probs))
        self.assertEqual(r["nota"], 55.0)
        self.assertEqual(r["estado"], "suspenso")
        self.assertEqual(r["criticos_fallidos"], [])

    def test_item_ambiguo_p_050(self):
        probs = {item_id: 0.9 for item_id in ITEM_IDS}
        probs["saludo"] = 0.5
        r = scoring.puntuar(rubric(), fila("1", probabilidades=probs))
        self.assertTrue(r["revision"])
        self.assertIn("saludo", r["motivos_revision"])

    def test_item_ambiguo_por_banda(self):
        probs = {item_id: 0.9 for item_id in ITEM_IDS}
        probs["saludo"] = 0.6  # dentro de [0.35, 0.65], confianza 0.2 igual dudoso
        r = scoring.puntuar(rubric(), fila("1", probabilidades=probs))
        self.assertTrue(r["revision"])
        self.assertIn("saludo", r["motivos_revision"])

    def test_bordes_de_banda_inclusive(self):
        for p in (0.35, 0.65):
            probs = {item_id: 0.9 for item_id in ITEM_IDS}
            probs["saludo"] = p
            r = scoring.puntuar(rubric(), fila("1", probabilidades=probs))
            self.assertIn("saludo", r["motivos_revision"])

    def test_umbral_confianza_solo_dispara_revision(self):
        probs = {item_id: 0.9 for item_id in ITEM_IDS}
        probs["saludo"] = 0.8  # confianza 0.6 < 0.7 por defecto, fuera de la banda
        self.assertFalse(0.35 <= probs["saludo"] <= 0.65)
        r = scoring.puntuar(rubric(), fila("1", probabilidades=probs))
        self.assertTrue(r["revision"])
        self.assertIn("saludo", r["motivos_revision"])

    def test_umbral_confianza_configurable_evita_revision(self):
        probs = {item_id: 0.9 for item_id in ITEM_IDS}
        probs["saludo"] = 0.8  # confianza 0.6
        r = scoring.puntuar(rubric({"confianza": 0.5}), fila("1", probabilidades=probs))
        self.assertFalse(r["revision"])
        self.assertNotIn("saludo", r["motivos_revision"])

    def test_fila_no_ok_error(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(rubric(), fila("1", estado="error"))

    def test_falta_columna_item(self):
        f = fila("1")
        del f["saludo"]
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(rubric(), f)

    def test_valor_no_numerico(self):
        f = fila("1")
        f["saludo"] = "abc"
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(rubric(), f)

    def test_valor_nan(self):
        f = fila("1")
        f["saludo"] = "nan"
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(rubric(), f)

    def test_valor_fuera_de_rango(self):
        f = fila("1")
        f["saludo"] = "1.5"
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(rubric(), f)

    def test_pesos_en_cero_invalido(self):
        r = {"items": [{"id": "saludo", "pregunta": "x", "peso": 0, "critico": False}]}
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(r, {"id": "1", "estado": "ok", "saludo": 0.9})

    def test_peso_infinito_invalido(self):
        r = rubric()
        r["items"][0]["peso"] = float("inf")
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(r, fila("1"))

    def test_critico_no_booleano_invalido(self):
        r = {"items": [{"id": "saludo", "pregunta": "x", "peso": 1, "critico": "si"}]}
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(r, {"id": "1", "estado": "ok", "saludo": 0.9})

    def test_umbrales_invalidos_se_propagan(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.puntuar(rubric({"dudosa_min": 0.9, "dudosa_max": 0.1}), fila("1"))


class TestPuntuarLote(unittest.TestCase):
    def test_separa_ok_de_sin_nota(self):
        filas = [
            fila("1"),
            fila("2", estado="error"),
            fila("3", estado="demasiado_larga"),
        ]
        puntuadas, sin_nota = scoring.puntuar_lote(rubric(), filas)
        self.assertEqual(len(puntuadas), 1)
        self.assertEqual(sin_nota, 2)


class TestAgregar(unittest.TestCase):
    def test_clave_invalida(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.agregar(rubric(), [fila("1")], "fecha")

    def test_lista_vacia(self):
        self.assertEqual(scoring.agregar(rubric(), [], "agente"), {})

    def test_agente_una_interaccion_vs_muchas(self):
        probs_bajas = {item_id: 0.1 for item_id in ITEM_IDS}
        filas = [
            fila("1", agente="ana"),  # todo cumple, aprobado
            fila("2", agente="beto", probabilidades=probs_bajas),  # todo falla, suspenso, crítico
            fila("3", agente="beto"),  # todo cumple
            fila("4", agente="beto", estado="error"),
        ]
        resultado = scoring.agregar(rubric(), filas, "agente")
        self.assertEqual(resultado["ana"]["n"], 1)
        self.assertEqual(resultado["ana"]["nota_media"], 100.0)
        self.assertEqual(resultado["ana"]["pct_criticas"], 0.0)
        self.assertEqual(resultado["ana"]["cola"], 0)

        self.assertEqual(resultado["beto"]["n"], 2)
        self.assertEqual(resultado["beto"]["sin_nota"], 1)
        self.assertEqual(resultado["beto"]["nota_media"], 50.0)
        self.assertEqual(resultado["beto"]["pct_criticas"], 50.0)
        self.assertEqual(resultado["beto"]["cola"], 0)

    def test_campana_vacia(self):
        filas = [
            fila("1", campaña="vacia", estado="error"),
            fila("2", campaña="vacia", estado="demasiado_larga"),
        ]
        resultado = scoring.agregar(rubric(), filas, "campaña")
        self.assertEqual(resultado["vacia"]["n"], 0)
        self.assertEqual(resultado["vacia"]["sin_nota"], 2)
        self.assertIsNone(resultado["vacia"]["nota_media"])
        self.assertEqual(resultado["vacia"]["pct_criticas"], 0.0)
        self.assertEqual(resultado["vacia"]["cola"], 0)

    def test_cola_cuenta_revision(self):
        probs = {item_id: 0.9 for item_id in ITEM_IDS}
        probs["saludo"] = 0.5
        filas = [fila("1", campaña="c", probabilidades=probs)]
        resultado = scoring.agregar(rubric(), filas, "campaña")
        self.assertEqual(resultado["c"]["cola"], 1)


if __name__ == "__main__":
    unittest.main()
