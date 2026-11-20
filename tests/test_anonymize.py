import csv
import os
import random
import re
import unicodedata
import unittest

from jevqa.anonymize import anonymize, restore

SINTETICAS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "eval", "sinteticas.csv"
)


def cedula(prefix9: str) -> str:
    """Completa 9 dígitos con el dígito verificador (módulo 10)."""
    total = 0
    for i, d in enumerate(prefix9):
        p = int(d) * (2 if i % 2 == 0 else 1)
        total += p - 9 if p > 9 else p
    return prefix9 + str((10 - total % 10) % 10)


def luhn(prefix: str) -> str:
    """Completa `prefix` con el dígito de control de Luhn."""
    for check in "0123456789":
        digits = prefix + check
        total = 0
        for i, d in enumerate(reversed(digits)):
            n = int(d)
            if i % 2 == 1:
                n = n * 2 - 9 if n > 4 else n * 2
            total += n
        if total % 10 == 0:
            return digits
    raise AssertionError("inalcanzable")


def sin_tildes(texto: str) -> str:
    base = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in base if not unicodedata.combining(c))


def agrupar(digits: str, sep: str, size: int = 4) -> str:
    return sep.join(digits[i:i + size] for i in range(0, len(digits), size))


CEDULA_VALIDA = cedula("171234567")  # Pichincha
TARJETA_VALIDA = luhn("411111111111111")


class NumerosTest(unittest.TestCase):
    def test_cedula_valida_se_tapa(self):
        self.assertEqual(
            anonymize(f"Mi cedula es {CEDULA_VALIDA}."), "Mi cedula es [CEDULA]."
        )

    def test_cedula_con_guion_se_tapa(self):
        texto = f"cedula {CEDULA_VALIDA[:9]}-{CEDULA_VALIDA[9]}"
        self.assertEqual(anonymize(texto), "cedula [CEDULA]")

    def test_diez_digitos_invalidos_no_se_tapan(self):
        # Mismo número con el verificador alterado: es un importe, no una cédula.
        malo = CEDULA_VALIDA[:9] + str((int(CEDULA_VALIDA[9]) + 1) % 10)
        texto = f"El saldo pendiente es {malo} sucres antiguos."
        self.assertEqual(anonymize(texto), texto)

    def test_diez_digitos_con_provincia_invalida_no_se_tapan(self):
        texto = "Referencia 9912345678 del sistema."  # provincia 99 y no empieza por 09
        self.assertEqual(anonymize(texto), texto)

    def test_ruc_persona_natural_y_sociedad(self):
        texto = f"RUC {CEDULA_VALIDA}001 y de la empresa 1790012345001."
        self.assertEqual(anonymize(texto), "RUC [RUC] y de la empresa [RUC].")

    def test_trece_digitos_sin_forma_de_ruc_no_son_ruc(self):
        # Provincia 99: no es RUC; tampoco pasa Luhn, así que queda igual.
        numero = "9912345678901"
        if luhn(numero[:-1]) == numero:
            numero = numero[:-1] + str((int(numero[-1]) + 1) % 10)
        texto = f"Orden {numero}."
        self.assertEqual(anonymize(texto), texto)

    def test_tarjeta_valida_se_tapa_en_varios_formatos(self):
        for formato in (
            TARJETA_VALIDA,
            agrupar(TARJETA_VALIDA, " "),
            agrupar(TARJETA_VALIDA, "-"),
        ):
            with self.subTest(formato=formato):
                self.assertEqual(anonymize(f"tarjeta {formato} gracias"),
                                 "tarjeta [TARJETA] gracias")

    def test_tarjeta_invalida_no_se_tapa(self):
        mala = TARJETA_VALIDA[:-1] + str((int(TARJETA_VALIDA[-1]) + 1) % 10)
        texto = f"tarjeta {agrupar(mala, ' ')} gracias"
        self.assertEqual(anonymize(texto), texto)

    def test_tarjeta_seguida_de_otro_numero(self):
        texto = f"tarjeta {agrupar(TARJETA_VALIDA, ' ')} 22 cuotas"
        self.assertEqual(anonymize(texto), "tarjeta [TARJETA] 22 cuotas")

    def test_telefonos_de_ecuador(self):
        for telefono in (
            "0991234567",
            "099 123 4567",
            "099-123-4567",
            "+593 99 123 4567",
            "+593991234567",
            "00593 99 123 4567",
            "02 234 5678",
            "(02) 234-5678",
            "042345678",
            "+593 2 234 5678",
        ):
            with self.subTest(telefono=telefono):
                self.assertEqual(anonymize(f"llame al {telefono}, gracias"),
                                 "llame al [TELEFONO], gracias")

    def test_numeros_vecinos_no_forman_una_tarjeta(self):
        # 10000 + 0991234567 son 15 dígitos que pasan Luhn: no deben unirse.
        self.assertEqual(anonymize("pedido 10000 0991234567"), "pedido 10000 [TELEFONO]")

    def test_correo(self):
        self.assertEqual(
            anonymize("escriba a camila.perez+qa@correo.com.ec hoy"),
            "escriba a [CORREO] hoy",
        )

    def test_cantidades_y_fechas_intactas(self):
        texto = (
            "El total es $1.250,50 con 3 cuotas de 416,83; vence el 15/03/2024 "
            "(2024-03-15), a las 10:30. Pedido 88214, codigo 1234567, "
            "monto 1.234.567.890,00 y 12 de marzo de 2025. Plan de 25 GB."
        )
        self.assertEqual(anonymize(texto), texto)

    def test_fecha_con_hora_no_es_telefono(self):
        for texto in (
            "La cita es el 09-12-2024 10:30.",
            "La cita es el 02-12-2024 9:30.",
            "La cita es el 09.12.2024 10:30.",
            "La cita es el 09/12/2024 10:30.",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(anonymize(texto), texto)

    def test_telefonos_siguen_tapandose_junto_a_fechas(self):
        for telefono in (
            "0991234567",
            "099-123-4567",
            "099 123 4567",
            "+593 99 123 4567",
            "00593 99 123 4567",
            "+593 9 8765 4321",
            "+593 2 234 5678",
            "(02) 234 5678",
            "02-234-5678",
        ):
            with self.subTest(telefono=telefono):
                self.assertEqual(
                    anonymize(f"el 09-12-2024 10:30 llamó del {telefono}."),
                    "el 09-12-2024 10:30 llamó del [TELEFONO].",
                )

    def test_telefono_seguido_de_otro_numero(self):
        self.assertEqual(anonymize("0991234567 25 minutos"), "[TELEFONO] 25 minutos")


class NombresTest(unittest.TestCase):
    def test_nombre_sin_distinguir_mayusculas_ni_tildes(self):
        names = ["José Pérez"]
        for variante in ("José Pérez", "jose perez", "JOSE PEREZ", "Jose", "pérez"):
            with self.subTest(variante=variante):
                self.assertEqual(
                    anonymize(f"Hola {variante}, bienvenido", names),
                    "Hola [NOMBRE_1], bienvenido",
                )

    def test_nombre_en_columna_sin_tilde_y_texto_con_tilde(self):
        self.assertEqual(anonymize("Soy Ramón", ["Ramon"]), "Soy [NOMBRE_1]")

    def test_texto_en_forma_nfd(self):
        texto = "Soy Rámon Ruiz"  # "á" descompuesta (NFD)
        self.assertEqual(anonymize(texto, ["Ramon Ruiz"]), "Soy [NOMBRE_1]")

    def test_no_tapa_dentro_de_otras_palabras(self):
        texto = "Esta semana la Anaconda llego."
        self.assertEqual(anonymize(texto, ["Ana"]), texto)

    def test_particulas_no_se_tapan_solas(self):
        texto = "Maria de la Cruz llamo por la mañana de ayer."
        self.assertEqual(
            anonymize(texto, ["María de la Cruz"]),
            "[NOMBRE_1] llamo por la mañana de ayer.",
        )

    def test_mapeo_reversible(self):
        names = ["Camila Andrade", "Luis Mora"]
        anon = anonymize("Agente Camila atiende a luis mora", names)
        self.assertEqual(anon, "Agente [NOMBRE_1] atiende a [NOMBRE_2]")
        self.assertEqual(restore(anon, names),
                         "Agente Camila Andrade atiende a Luis Mora")

    def test_no_modifica_la_lista(self):
        names = ["Camila"]
        anonymize("Camila", names)
        self.assertEqual(names, ["Camila"])

    def test_nombres_vacios_se_ignoran(self):
        self.assertEqual(anonymize("hola", ["", "  "]), "hola")

    def test_limite_conocido_nombre_fuera_de_columnas(self):
        # Riesgo documentado: sin columna que lo nombre, un nombre propio se escapa.
        self.assertEqual(anonymize("Hablé con Rosendo", ["Camila"]),
                         "Hablé con Rosendo")


class SinDatosPersonalesTest(unittest.TestCase):
    def test_texto_sin_datos_queda_igual(self):
        texto = "Agente: Buenos dias, en que puedo ayudarle? Cliente: No me llega la factura."
        self.assertEqual(anonymize(texto, ["Camila"]), texto)

    def test_texto_vacio(self):
        self.assertEqual(anonymize(""), "")


AGENTES = ["Camila Andrade", "Mateo Guerrero", "Sofía Núñez", "Andrés Peña"]
CLIENTES = ["José Pérez", "María de los Ángeles Chávez", "Luis Mora", "Ramón Ibáñez"]


class SinteticasSembradasTest(unittest.TestCase):
    """Terminado cuando: 40 interacciones con datos sembrados -> 0 fugas y 0 importes tapados."""

    def test_cero_fugas_y_cero_importes_tapados(self):
        with open(SINTETICAS_PATH, encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
        self.assertEqual(len(filas), 40)

        rng = random.Random(593)
        fugas, tapados = [], []
        for i, fila in enumerate(filas):
            agente = AGENTES[i % len(AGENTES)]
            cliente = CLIENTES[i % len(CLIENTES)]
            ced = cedula("%02d" % rng.randint(1, 24) + str(rng.randint(0, 5))
                         + "%06d" % rng.randint(0, 999999))
            tarjeta = luhn("4" + "%014d" % rng.randint(0, 10**14 - 1))
            movil = "09%d%07d" % (rng.randint(2, 9), rng.randint(0, 9999999))
            fijo = "0%d%07d" % (rng.randint(2, 7), rng.randint(2000000, 9999999))
            correo = f"cliente{i}@ejemplo.ec"
            ruc = ced + "001"
            formatos_movil = [movil, f"{movil[:3]} {movil[3:6]} {movil[6:]}",
                              f"+593 {movil[1:3]} {movil[3:6]} {movil[6:]}"]
            importes = [f"${rng.randint(1, 999)}.{rng.randint(100, 999)},{rng.randint(10, 99)}",
                        f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/2024",
                        f"pedido {rng.randint(10000, 99999)}"]
            # Nombres con otra capitalización y sin tildes, como los dictaría un transcriptor.
            texto = (
                f"Agente: Le atiende {agente.split()[0]}. {fila['texto']} "
                f"Cliente: Soy {cliente.upper()}, cedula {ced}, RUC {ruc}, "
                f"tarjeta {agrupar(tarjeta, ' ')}, celular {formatos_movil[i % 3]}, "
                f"fijo ({fijo[:2]}) {fijo[2:]}, correo {correo}. "
                f"Pague {importes[0]} el {importes[1]}, {importes[2]}. "
                f"Agente: Gracias senor {cliente.split()[-1].lower()}, "
                f"le saluda {agente.split()[-1]}."
            )
            names = [agente, cliente]
            anon = anonymize(texto, names)

            # Los números se buscan entre los dígitos del texto sin separadores,
            # para detectar también una fuga en formato "+593 99 123 4567".
            digitos = re.sub(r"[^0-9]", "", anon)
            numericos = [ced, ruc, tarjeta, movil[1:], fijo[2:]]
            partes_nombre = [p for n in names for p in n.split()
                             if len(p) >= 3 and p not in ("los", "las", "del")]
            plegado = sin_tildes(anon)
            for dato in numericos:
                if dato in digitos:
                    fugas.append((fila["id"], dato))
            if correo in anon:
                fugas.append((fila["id"], correo))
            for parte in partes_nombre:
                if re.search(rf"(?<!\w){sin_tildes(parte)}(?!\w)", plegado):
                    fugas.append((fila["id"], parte))
            for importe in importes:
                if importe not in anon:
                    tapados.append((fila["id"], importe))
            self.assertGreaterEqual(restore(anon, names).count(agente), 2, fila["id"])

        self.assertEqual(fugas, [])
        self.assertEqual(tapados, [])


if __name__ == "__main__":
    unittest.main()
