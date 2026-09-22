"""Tests del anonimizador. Lo que se mide es que no se escape nada y que no
se tape de más: las dos cosas rompen el producto, una por ley y la otra
porque deja a Jev sin lo que necesita para juzgar la llamada.
"""

from __future__ import annotations

import csv
import os
import unittest

from jevqa.anonymize import (
    ETIQUETA_CEDULA,
    ETIQUETA_CORREO,
    ETIQUETA_NOMBRE,
    ETIQUETA_RUC,
    ETIQUETA_TARJETA,
    ETIQUETA_TELEFONO,
    anonimizar_con_mapa,
    anonymize,
    cedula_valida,
    luhn_valido,
    ruc_valido,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINTETICAS = os.path.join(RAIZ, "data", "eval", "sinteticas.csv")

CEDULA = "1712345675"
CEDULA_GUAYAS = "0923456784"
#: Mismos diez dígitos con el último cambiado: ya no es una cédula.
NO_CEDULA = "1712345670"
RUC_NATURAL = "1712345675001"
TARJETA = "4532012345678902"
NO_TARJETA = "4532012345678901"


class TestValidadores(unittest.TestCase):
    def test_cedula(self):
        self.assertTrue(cedula_valida(CEDULA))
        self.assertTrue(cedula_valida(CEDULA_GUAYAS))
        self.assertFalse(cedula_valida(NO_CEDULA))
        self.assertFalse(cedula_valida("9912345675"), "provincia 99 no existe")
        self.assertFalse(cedula_valida("1762345675"), "tercer dígito 6 no es natural")
        self.assertFalse(cedula_valida("171234567"), "solo nueve dígitos")
        self.assertFalse(cedula_valida("17123456a5"))

    def test_ruc(self):
        self.assertTrue(ruc_valido(RUC_NATURAL))
        self.assertFalse(ruc_valido("1712345675000"), "establecimiento 000 no existe")
        self.assertFalse(ruc_valido("1712345670001"), "la cédula base no es válida")
        self.assertFalse(ruc_valido("171234567500"), "solo doce dígitos")

    def test_luhn(self):
        self.assertTrue(luhn_valido(TARJETA))
        self.assertTrue(luhn_valido("5178456734120099"))
        self.assertFalse(luhn_valido(NO_TARJETA))
        self.assertFalse(luhn_valido("4532 0123"))


class TestDatosQueSeTapan(unittest.TestCase):
    def test_cedula(self):
        self.assertEqual(
            anonymize(f"Mi cédula es {CEDULA}."), f"Mi cédula es {ETIQUETA_CEDULA}."
        )

    def test_ruc(self):
        self.assertEqual(
            anonymize(f"El RUC es {RUC_NATURAL}."), f"El RUC es {ETIQUETA_RUC}."
        )

    def test_el_ruc_gana_a_la_cedula_que_contiene(self):
        # Los diez primeros dígitos de un RUC natural son una cédula válida:
        # si se comprobara la cédula primero, quedarían tres dígitos sueltos.
        self.assertEqual(anonymize(RUC_NATURAL), ETIQUETA_RUC)

    def test_celular_y_fijos(self):
        self.assertEqual(anonymize("Llame al 0991234567"), f"Llame al {ETIQUETA_TELEFONO}")
        self.assertEqual(anonymize("Fijo 022345678"), f"Fijo {ETIQUETA_TELEFONO}")
        self.assertEqual(anonymize("Fijo 042987654"), f"Fijo {ETIQUETA_TELEFONO}")

    def test_celular_con_codigo_de_pais(self):
        for numero in ("+593987654321", "+593 98 765 4321", "593987654321"):
            with self.subTest(numero=numero):
                self.assertEqual(anonymize(f"Al {numero} ya"), f"Al {ETIQUETA_TELEFONO} ya")

    def test_correo(self):
        self.assertEqual(
            anonymize("Escriba a maria.lopez@correo.com hoy"),
            f"Escriba a {ETIQUETA_CORREO} hoy",
        )

    def test_tarjeta_con_y_sin_separadores(self):
        for numero in (TARJETA, "4532 0123 4567 8902", "4532-0123-4567-8902"):
            with self.subTest(numero=numero):
                self.assertEqual(
                    anonymize(f"La tarjeta {numero} se bloquea"),
                    f"La tarjeta {ETIQUETA_TARJETA} se bloquea",
                )

    def test_varios_datos_en_la_misma_linea(self):
        texto = f"Soy {CEDULA}, mi correo ana@x.com y mi celular 0987654321."
        self.assertEqual(
            anonymize(texto),
            f"Soy {ETIQUETA_CEDULA}, mi correo {ETIQUETA_CORREO} "
            f"y mi celular {ETIQUETA_TELEFONO}.",
        )


class TestDatosQueNoSeTapan(unittest.TestCase):
    def test_diez_digitos_que_no_son_cedula(self):
        # Un número de caso no es una cédula aunque tenga diez dígitos.
        self.assertEqual(
            anonymize(f"Su caso es el {NO_CEDULA}"), f"Su caso es el {NO_CEDULA}"
        )

    def test_tarjeta_con_digito_de_control_invalido(self):
        self.assertEqual(anonymize(f"Dictó {NO_TARJETA}"), f"Dictó {NO_TARJETA}")

    def test_importes(self):
        texto = "Le cobraron $342,80 y su cupo es de $1.250,00, más $19,90 al mes."
        self.assertEqual(anonymize(texto), texto)

    def test_fechas(self):
        texto = "Fue el 15/08/2026, se resuelve el 2026-09-01, en 48 horas."
        self.assertEqual(anonymize(texto), texto)

    def test_cantidades(self):
        texto = "Son 5 GB, 200 megas, 3 cuotas y 15 días hábiles."
        self.assertEqual(anonymize(texto), texto)

    def test_texto_sin_datos_personales_queda_igual(self):
        texto = (
            "Agente: Buenos días, gracias por llamar.\n"
            "Cliente: El internet se corta cada media hora.\n"
            "Agente: ¿Ya intentó reiniciar el módem?"
        )
        self.assertEqual(anonymize(texto), texto)

    def test_texto_vacio(self):
        self.assertEqual(anonymize(""), "")
        self.assertEqual(anonymize("   "), "   ")


class TestNombres(unittest.TestCase):
    def test_nombre_completo_y_apellido_suelto(self):
        texto = "Agente: Con gusto, María López. ¿Señora López, me confirma?"
        salida = anonymize(texto, ["María López"])
        self.assertNotIn("María", salida)
        self.assertNotIn("López", salida)
        self.assertEqual(salida.count(ETIQUETA_NOMBRE), 2)

    def test_sin_distinguir_tildes(self):
        # La columna trae la tilde y la transcripción no, o al revés.
        self.assertNotIn("Lopez", anonymize("Señora Lopez, buenas", ["María López"]))
        self.assertNotIn("Pérez", anonymize("Señora Pérez, buenas", ["Jhoanna Perez"]))

    def test_sin_distinguir_mayusculas(self):
        self.assertNotIn("CEDEÑO", anonymize("Habla BYRON CEDEÑO", ["Byron Cedeño"]))
        self.assertNotIn("cedeño", anonymize("habla byron cedeño", ["Byron Cedeño"]))

    def test_la_ene_se_pliega_a_la_n(self):
        self.assertNotIn("Cedeno", anonymize("El señor Cedeno llamó", ["Byron Cedeño"]))

    def test_no_parte_palabras_que_contienen_el_nombre(self):
        # "Rosa" no debe tapar "Rosario" ni "rosado".
        salida = anonymize("El barrio Rosario y el color rosado", ["Rosa Delgado"])
        self.assertEqual(salida, "El barrio Rosario y el color rosado")

    def test_tokens_de_menos_de_tres_letras_se_ignoran(self):
        # "de" y "la" de un "Ana de la Torre" taparían medio texto.
        salida = anonymize("La casa de la esquina", ["Ana de la Torre"])
        self.assertEqual(salida, "La casa de la esquina")

    def test_el_correo_gana_al_nombre_que_contiene(self):
        salida = anonymize("Escriba a maria.lopez@correo.com", ["María López"])
        self.assertEqual(salida, f"Escriba a {ETIQUETA_CORREO}")

    def test_sin_nombres_no_se_tapa_ninguno(self):
        texto = "Agente: le habla Rosa Delgado."
        self.assertEqual(anonymize(texto), texto)

    def test_nombre_fuera_de_las_columnas_se_escapa(self):
        """Límite conocido: solo se tapan los nombres que vienen en el CSV.

        Un tercero mencionado en la conversación (un familiar, otro agente)
        se va tal cual. Queda documentado en el README, no arreglado.
        """
        salida = anonymize("Mi hermano Freddy Coello está internado", ["Ana Salazar"])
        self.assertIn("Freddy Coello", salida)


class TestMapaReversible(unittest.TestCase):
    def test_guarda_los_valores_por_etiqueta(self):
        texto = f"Soy María López, cédula {CEDULA}, correo m@x.com"
        salida, mapa = anonimizar_con_mapa(texto, ["María López"])

        self.assertEqual(len(mapa), 3)
        self.assertEqual(mapa.valores(ETIQUETA_CEDULA), [CEDULA])
        self.assertEqual(mapa.valores(ETIQUETA_NOMBRE), ["María López"])
        self.assertEqual(mapa.valores(ETIQUETA_CORREO), ["m@x.com"])
        self.assertNotIn(CEDULA, salida)

    def test_restaura_el_texto_original(self):
        texto = (
            f"Agente: le habla Rosa Delgado.\n"
            f"Cliente: mi cédula es {CEDULA} y mi celular 0991234567."
        )
        salida, mapa = anonimizar_con_mapa(texto, ["Rosa Delgado"])
        self.assertEqual(mapa.restaurar(salida), texto)

    def test_el_nombre_del_agente_se_recupera_para_el_informe(self):
        # El informe interno muestra al agente; Jev nunca vio ese nombre.
        _, mapa = anonimizar_con_mapa("Le habla Kevin Morales.", ["Kevin Morales"])
        self.assertEqual(mapa.valores(ETIQUETA_NOMBRE), ["Kevin Morales"])

    def test_texto_sin_datos_da_un_mapa_vacio(self):
        salida, mapa = anonimizar_con_mapa("No hay nada que tapar.")
        self.assertEqual(len(mapa), 0)
        self.assertEqual(mapa.restaurar(salida), "No hay nada que tapar.")


class TestConjuntoSintetico(unittest.TestCase):
    """Sobre las 40 interacciones: 0 fugas y 0 importes tapados."""

    @classmethod
    def setUpClass(cls):
        with open(SINTETICAS, encoding="utf-8", newline="") as archivo:
            cls.filas = list(csv.DictReader(archivo))

    def test_hay_cuarenta_interacciones(self):
        self.assertEqual(len(self.filas), 40)

    def test_cero_fugas(self):
        fugas = []
        for fila in self.filas:
            salida = anonymize(fila["texto"], [fila["agente"], fila["cliente"]])
            for dato in filter(None, fila["pii_sembrada"].split("|")):
                if dato in salida:
                    fugas.append((fila["id"], dato))
        self.assertEqual(fugas, [], f"{len(fugas)} datos personales se escaparon")

    def test_cero_nombres_de_agente_o_cliente_filtrados(self):
        fugas = []
        for fila in self.filas:
            salida = anonymize(fila["texto"], [fila["agente"], fila["cliente"]])
            for nombre in (fila["agente"], fila["cliente"]):
                for token in nombre.split():
                    if len(token) >= 3 and token in salida:
                        fugas.append((fila["id"], token))
        self.assertEqual(fugas, [])

    def test_cero_importes_fechas_y_cantidades_tapados(self):
        perdidos = []
        for fila in self.filas:
            salida = anonymize(fila["texto"], [fila["agente"], fila["cliente"]])
            for dato in filter(None, fila["no_tapar"].split("|")):
                if dato not in salida:
                    perdidos.append((fila["id"], dato))
        self.assertEqual(perdidos, [], f"{len(perdidos)} valores se taparon de más")

    def test_el_texto_sigue_siendo_util(self):
        # Si la anonimización se comiera la conversación, Jev no podría juzgarla.
        for fila in self.filas:
            salida = anonymize(fila["texto"], [fila["agente"], fila["cliente"]])
            with self.subTest(id=fila["id"]):
                self.assertGreater(len(salida), 0.8 * len(fila["texto"]))
                self.assertIn("Agente:", salida)
                self.assertIn("Cliente:", salida)


if __name__ == "__main__":
    unittest.main()
