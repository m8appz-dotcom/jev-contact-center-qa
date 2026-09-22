"""Anonimizador: ningún dato personal del cliente final sale hacia Jev.

La Ley Orgánica de Protección de Datos Personales de Ecuador obliga a
minimizar los datos que se transfieren a un tercero. Jev no necesita saber
quién es el cliente para juzgar cómo lo atendieron, así que se tapa todo lo
que lo identifique antes de armar la petición.

    >>> anonymize("Mi cédula es 1712345675 y pagué $19,90")
    'Mi cédula es [CEDULA] y pagué $19,90'

Dos decisiones de diseño que conviene tener presentes:

* **Se detecta sobre el texto original, de una sola pasada.** Todos los
  detectores marcan tramos sobre el mismo texto y después se resuelven los
  solapamientos por prioridad. Así un nombre dentro de un correo no parte el
  correo por la mitad, y ninguna etiqueta ya puesta se vuelve a analizar.
* **Solo se tapa lo que se puede verificar.** Una cédula se tapa porque su
  dígito verificador cuadra, y una tarjeta porque pasa Luhn. Diez dígitos
  cualesquiera son un número de caso, no una cédula, y un importe no es un
  teléfono. Tapar de más deja el texto sin la información que Jev necesita
  para juzgar la llamada.
"""

from __future__ import annotations

import re
import unicodedata

ETIQUETA_CEDULA = "[CEDULA]"
ETIQUETA_RUC = "[RUC]"
ETIQUETA_TELEFONO = "[TELEFONO]"
ETIQUETA_CORREO = "[CORREO]"
ETIQUETA_TARJETA = "[TARJETA]"
ETIQUETA_NOMBRE = "[NOMBRE]"

ETIQUETAS = (
    ETIQUETA_CEDULA,
    ETIQUETA_RUC,
    ETIQUETA_TELEFONO,
    ETIQUETA_CORREO,
    ETIQUETA_TARJETA,
    ETIQUETA_NOMBRE,
)

#: Prioridad al resolver solapamientos: gana el número más bajo.
_PRIORIDAD = {"correo": 0, "numero": 1, "nombre": 2}

#: Un token de un nombre más corto que esto se ignora: "de", "la", "Ma".
LARGO_MINIMO_NOMBRE = 3

_PATRON_CORREO = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

#: Grupos de dos o más dígitos separados por espacio o guion. Exige dos
#: dígitos por grupo para no enganchar el "5" de "5 GB", y no admite ni "/"
#: ni "." como separador para no unir las partes de una fecha o un importe.
_PATRON_NUMERO = re.compile(r"(?<![\w@.,])\+?\d{2,}(?:[ \-]\d{2,})*(?![\w])")

#: Provincias válidas en una cédula: 01 a 24, más 30 para los extranjeros.
_PROVINCIAS = set(range(1, 25)) | {30}


# ---------------------------------------------------------------------------
# Validadores
# ---------------------------------------------------------------------------

def cedula_valida(numero: str) -> bool:
    """Diez dígitos con provincia, tercer dígito de persona natural y módulo 10."""
    if len(numero) != 10 or not numero.isdigit():
        return False
    if int(numero[:2]) not in _PROVINCIAS:
        return False
    if int(numero[2]) > 5:
        return False
    total = 0
    for posicion, digito in enumerate(numero[:9]):
        producto = int(digito) * (2 if posicion % 2 == 0 else 1)
        total += producto - 9 if producto > 9 else producto
    return (10 - total % 10) % 10 == int(numero[9])


def _modulo_11(numero: str, coeficientes: tuple[int, ...], posicion: int) -> bool:
    total = sum(int(d) * c for d, c in zip(numero, coeficientes))
    resto = total % 11
    verificador = 0 if resto == 0 else 11 - resto
    return verificador == int(numero[posicion])


def ruc_valido(numero: str) -> bool:
    """Trece dígitos: persona natural, sociedad privada o entidad pública."""
    if len(numero) != 13 or not numero.isdigit():
        return False
    if int(numero[:2]) not in _PROVINCIAS:
        return False
    if numero[10:] == "000":
        return False

    tercero = int(numero[2])
    if tercero < 6:  # persona natural: cédula + código de establecimiento
        return cedula_valida(numero[:10])
    if tercero == 6:  # entidad pública: verificador en la novena posición
        return numero[9:] != "0000" and _modulo_11(
            numero[:8], (3, 2, 7, 6, 5, 4, 3, 2), 8
        )
    if tercero == 9:  # sociedad privada o extranjero sin cédula
        return _modulo_11(numero[:9], (4, 3, 2, 7, 6, 5, 4, 3, 2), 9)
    return False


def luhn_valido(numero: str) -> bool:
    """Dígito de control de una tarjeta (ISO/IEC 7812)."""
    if not numero.isdigit():
        return False
    total = 0
    for posicion, caracter in enumerate(reversed(numero)):
        digito = int(caracter)
        if posicion % 2 == 1:
            digito *= 2
            if digito > 9:
                digito -= 9
        total += digito
    return total % 10 == 0


def _telefono(numero: str) -> bool:
    """Celular (09 y ocho dígitos) o fijo (0, código de área y siete dígitos)."""
    if len(numero) == 10 and numero.startswith("09"):
        return True
    return len(numero) == 9 and numero[0] == "0" and numero[1] in "234567"


def clasificar_numero(crudo: str) -> str | None:
    """Devuelve la etiqueta que corresponde a un número, o None si no es un dato personal.

    El orden importa: un RUC contiene una cédula y una tarjeta de trece dígitos
    puede parecer un RUC, así que se comprueba de lo más específico a lo menos.
    """
    digitos = re.sub(r"\D", "", crudo)
    if crudo.lstrip().startswith("+") or digitos.startswith("593"):
        sin_pais = digitos[3:] if digitos.startswith("593") else digitos
        if sin_pais and not sin_pais.startswith("0"):
            sin_pais = "0" + sin_pais
        if _telefono(sin_pais):
            return ETIQUETA_TELEFONO

    if ruc_valido(digitos):
        return ETIQUETA_RUC
    if cedula_valida(digitos):
        return ETIQUETA_CEDULA
    if 13 <= len(digitos) <= 19 and luhn_valido(digitos):
        return ETIQUETA_TARJETA
    if _telefono(digitos):
        return ETIQUETA_TELEFONO
    return None


# ---------------------------------------------------------------------------
# Comparación de nombres sin tildes ni mayúsculas
# ---------------------------------------------------------------------------

def _plegar(texto: str) -> str:
    """Quita tildes y baja a minúsculas conservando la longitud del texto.

    Conservar la longitud es lo que permite buscar sobre el texto plegado y
    aplicar el resultado sobre el original por posición.
    """
    salida = []
    for caracter in texto:
        base = unicodedata.normalize("NFD", caracter)
        base = "".join(c for c in base if not unicodedata.combining(c)) or caracter
        minuscula = base[0].lower()
        salida.append(minuscula[0] if minuscula else base[0])
    return "".join(salida)


def _terminos_de_nombres(names: list[str]) -> list[str]:
    """El nombre completo y cada uno de sus tokens, de más largo a más corto."""
    terminos: set[str] = set()
    for nombre in names:
        if not isinstance(nombre, str):
            continue
        plegado = _plegar(nombre).strip()
        if not plegado:
            continue
        terminos.add(plegado)
        for token in re.split(r"[\s'\-]+", plegado):
            if len(token) >= LARGO_MINIMO_NOMBRE:
                terminos.add(token)
    return sorted(terminos, key=len, reverse=True)


# ---------------------------------------------------------------------------
# Detección y sustitución
# ---------------------------------------------------------------------------

def _detectar(texto: str, names: list[str]) -> list[tuple[int, int, str, str]]:
    tramos: list[tuple[int, int, str, str]] = []

    for coincidencia in _PATRON_CORREO.finditer(texto):
        tramos.append((coincidencia.start(), coincidencia.end(), "correo", ETIQUETA_CORREO))

    for coincidencia in _PATRON_NUMERO.finditer(texto):
        etiqueta = clasificar_numero(coincidencia.group())
        if etiqueta is not None:
            tramos.append((coincidencia.start(), coincidencia.end(), "numero", etiqueta))

    terminos = _terminos_de_nombres(names)
    if terminos:
        plegado = _plegar(texto)
        patron = re.compile(
            r"(?<![\w])(?:" + "|".join(re.escape(t) for t in terminos) + r")(?![\w])"
        )
        for coincidencia in patron.finditer(plegado):
            tramos.append(
                (coincidencia.start(), coincidencia.end(), "nombre", ETIQUETA_NOMBRE)
            )

    return tramos


def _sin_solapamientos(
    tramos: list[tuple[int, int, str, str]]
) -> list[tuple[int, int, str]]:
    """Resuelve los solapamientos: gana la prioridad y, a igualdad, el más largo."""
    ordenados = sorted(
        tramos, key=lambda t: (t[0], _PRIORIDAD[t[2]], -(t[1] - t[0]))
    )
    elegidos: list[tuple[int, int, str]] = []
    fin_anterior = -1
    for inicio, fin, clase, etiqueta in ordenados:
        if inicio < fin_anterior:
            continue
        elegidos.append((inicio, fin, etiqueta))
        fin_anterior = fin
    return elegidos


class Mapa:
    """Correspondencia entre cada etiqueta puesta y el valor original.

    Vive solo en memoria y nunca se serializa: es lo que permite que el
    informe interno muestre el nombre del agente sin que ese nombre haya
    viajado a Jev. Las ocurrencias se guardan en orden, así que `restaurar`
    puede deshacer la anonimización de ese mismo texto.
    """

    __slots__ = ("entradas",)

    def __init__(self, entradas: list[tuple[str, str]] | None = None) -> None:
        #: Lista de (etiqueta, valor original), en el orden en que aparecen.
        self.entradas: list[tuple[str, str]] = list(entradas or [])

    def __len__(self) -> int:
        return len(self.entradas)

    def valores(self, etiqueta: str) -> list[str]:
        """Los valores originales tapados con una etiqueta, sin repetir."""
        vistos: dict[str, None] = {}
        for puesta, original in self.entradas:
            if puesta == etiqueta:
                vistos.setdefault(original, None)
        return list(vistos)

    def restaurar(self, texto: str) -> str:
        """Deshace la anonimización de un texto producido por este mismo mapa."""
        partes: list[str] = []
        posicion = 0
        patron = re.compile("|".join(re.escape(e) for e in ETIQUETAS))
        for numero, coincidencia in enumerate(patron.finditer(texto)):
            if numero >= len(self.entradas):
                break
            partes.append(texto[posicion : coincidencia.start()])
            partes.append(self.entradas[numero][1])
            posicion = coincidencia.end()
        partes.append(texto[posicion:])
        return "".join(partes)

    def __repr__(self) -> str:  # pragma: no cover - ayuda al depurar
        return f"<Mapa {len(self.entradas)} valores tapados>"


def anonimizar_con_mapa(text: str, names: list[str] | None = None) -> tuple[str, Mapa]:
    """Como `anonymize`, pero devuelve además el mapa reversible en memoria."""
    if not text:
        return text, Mapa()

    tramos = _sin_solapamientos(_detectar(text, list(names or [])))
    if not tramos:
        return text, Mapa()

    partes: list[str] = []
    entradas: list[tuple[str, str]] = []
    posicion = 0
    for inicio, fin, etiqueta in tramos:
        partes.append(text[posicion:inicio])
        partes.append(etiqueta)
        entradas.append((etiqueta, text[inicio:fin]))
        posicion = fin
    partes.append(text[posicion:])
    return "".join(partes), Mapa(entradas)


def anonymize(text: str, names: list[str] = []) -> str:
    """Tapa los datos personales de `text`.

    `names` son los nombres que vienen en las columnas del CSV (agente y
    cliente). Se comparan sin distinguir mayúsculas ni tildes, tanto el nombre
    completo como cada uno de sus tokens de tres letras o más.

    Límite conocido: un nombre propio que no esté en ninguna columna no se
    detecta. Si en la conversación aparece el nombre de un tercero, se va tal
    cual. Ver el test `test_nombre_fuera_de_las_columnas_se_escapa`.
    """
    return anonimizar_con_mapa(text, names)[0]
