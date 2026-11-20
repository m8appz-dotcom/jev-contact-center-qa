"""Anonimización de transcripciones antes de enviarlas a Jev (ley de datos de Ecuador).

Sustituye por etiquetas: cédulas y RUC válidos, tarjetas que pasan Luhn,
teléfonos de Ecuador (móviles, fijos, +593), correos y los nombres que el
llamador toma de las columnas del CSV (sin distinguir mayúsculas ni tildes).

Los números solo se tapan si validan (dígito verificador, Luhn, formato de
teléfono), para no borrar importes, fechas ni números de pedido.

Los nombres se sustituyen por `[NOMBRE_n]`, donde n es su posición (desde 1)
en la lista `names`: el mapeo vive solo en memoria del llamador y `restore`
lo deshace para el informe. Límites conocidos: un nombre propio que no está en
`names` no se detecta; un apellido que también es palabra común ("Peña" y "pena")
se tapa también como palabra (se prefiere tapar de más a filtrar).
"""

from __future__ import annotations

import re
import unicodedata

CEDULA = "[CEDULA]"
RUC = "[RUC]"
TARJETA = "[TARJETA]"
TELEFONO = "[TELEFONO]"
CORREO = "[CORREO]"

# Partículas de nombres compuestos que no se tapan solas ("María de la Cruz").
_PARTICULAS = {"de", "del", "la", "las", "los", "y", "e", "da", "do", "dos", "van", "von"}
_MIN_TOKEN = 3

# Un número no empieza ni termina pegado a otro dígito ni a un separador decimal
# seguido de dígito, para no tomar el trozo de un importe como "1.234.567.890,00".
_ANTES = r"(?<![0-9])(?<![0-9][.,])"
_DESPUES = r"(?![0-9])(?![.,][0-9])"

_CORREO_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RUC_RE = re.compile(_ANTES + r"[0-9]{13}" + _DESPUES)
# Tarjeta: seguida, en grupos de 4 o en formato Amex (4-6-5). Grupos fijos para
# no unir dos números vecinos ("pedido 88214 0991234567") en una falsa tarjeta.
_TARJETA_RE = re.compile(
    _ANTES
    + r"(?:[0-9]{13,19}|[0-9]{4}(?:[ -][0-9]{4}){2}[ -][0-9]{1,7}|[0-9]{4}[ -][0-9]{6}[ -][0-9]{4,5})"
    + _DESPUES
)
_CEDULA_RE = re.compile(_ANTES + r"[0-9]{9}-?[0-9]" + _DESPUES)
_PREFIJO_593 = r"(?:(?:\+|00)[ ]?)?593[ .-]?"
# Un teléfono no empieza donde empieza una fecha dd-mm-yyyy (o con / o .):
# "09-12-2024 10:30" daría los 10 dígitos de un móvil.
_NO_FECHA = r"(?![0-9]{1,2}([-/.])[0-9]{1,2}\1[0-9]{4}(?![0-9]))"
_MOVIL_RE = re.compile(
    r"(?<![\w+])" + _NO_FECHA + r"(?:" + _PREFIJO_593 + r"|0)9(?:[ .-]?[0-9]){8}" + _DESPUES
)
_FIJO_RE = re.compile(
    r"(?<![\w+])" + _NO_FECHA
    + r"(?:" + _PREFIJO_593 + r"\(?|\(?0)[2-7]\)?(?:[ .-]?[0-9]){7}" + _DESPUES
)
_NOMBRE_RE = re.compile(r"\[NOMBRE_([0-9]+)\]")


def _provincia_valida(digits: str) -> bool:
    return 1 <= int(digits[:2]) <= 24 or digits[:2] == "30"


def _cedula_valida(digits: str) -> bool:
    """Cédula de persona natural: provincia, tercer dígito < 6 y módulo 10."""
    if len(digits) != 10 or not _provincia_valida(digits) or int(digits[2]) >= 6:
        return False
    total = 0
    for i, d in enumerate(digits[:9]):
        p = int(d) * (2 if i % 2 == 0 else 1)
        total += p - 9 if p > 9 else p
    return (10 - total % 10) % 10 == int(digits[9])


def _ruc_valido(digits: str) -> bool:
    """RUC: cédula + establecimiento, o sociedad (tercer dígito 6 o 9)."""
    if len(digits) != 13 or digits[10:] == "000" or not _provincia_valida(digits):
        return False
    return digits[2] in "69" or _cedula_valida(digits[:10])


def _luhn_valido(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _sustituir_si(pattern: re.Pattern, text: str, valido, etiqueta: str) -> str:
    def repl(m: re.Match) -> str:
        digits = re.sub(r"[^0-9]", "", m.group(0))
        return etiqueta if valido(digits) else m.group(0)

    return pattern.sub(repl, text)


def _plegar(text: str) -> tuple[str, list[int]]:
    """Minúsculas sin tildes, con el índice original de cada carácter plegado."""
    chars: list[str] = []
    origen: list[int] = []
    for i, ch in enumerate(text):
        for base in unicodedata.normalize("NFD", ch):
            if unicodedata.combining(base):
                continue
            for c in base.casefold():
                if not unicodedata.combining(c):
                    chars.append(c)
                    origen.append(i)
    return "".join(chars), origen


def _patron_nombres(names: list[str]) -> tuple[re.Pattern | None, list[str]]:
    """Una alternancia (de más larga a más corta) con el nombre completo y sus partes."""
    etiquetas: dict[str, str] = {}
    for n, name in enumerate(names, start=1):
        tokens = re.findall(r"\w+", _plegar(name)[0])
        if not tokens:
            continue
        candidatos = [r"\W+".join(map(re.escape, tokens))]
        candidatos += [
            re.escape(t) for t in tokens
            if len(t) >= _MIN_TOKEN and t not in _PARTICULAS
        ]
        for c in candidatos:
            etiquetas.setdefault(c, f"[NOMBRE_{n}]")
    if not etiquetas:
        return None, []
    alternativas = sorted(etiquetas, key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(f"({a})" for a in alternativas) + r")(?!\w)"
    )
    # Cada alternativa es un grupo: el grupo n que casa da su etiqueta.
    return pattern, [etiquetas[a] for a in alternativas]


def _sustituir_nombres(text: str, names: list[str]) -> str:
    pattern, etiquetas = _patron_nombres(names)
    if pattern is None:
        return text
    plegado, origen = _plegar(text)
    partes: list[str] = []
    fin_anterior = 0
    for m in pattern.finditer(plegado):
        inicio = origen[m.start()]
        fin = origen[m.end() - 1] + 1
        # Arrastra las marcas combinantes de un texto en forma NFD.
        while fin < len(text) and unicodedata.combining(text[fin]):
            fin += 1
        partes.append(text[fin_anterior:inicio])
        partes.append(etiquetas[m.lastindex - 1])
        fin_anterior = fin
    partes.append(text[fin_anterior:])
    return "".join(partes)


def anonymize(text: str, names: list[str] = []) -> str:
    """Devuelve `text` con los datos personales sustituidos por etiquetas.

    `names` son los nombres de agente y cliente tomados de las columnas del
    CSV; no se modifica.
    """
    text = _CORREO_RE.sub(CORREO, text)
    text = _sustituir_si(_RUC_RE, text, _ruc_valido, RUC)
    text = _sustituir_si(_TARJETA_RE, text, _luhn_valido, TARJETA)
    text = _sustituir_si(_CEDULA_RE, text, _cedula_valida, CEDULA)
    text = _MOVIL_RE.sub(TELEFONO, text)
    text = _FIJO_RE.sub(TELEFONO, text)
    return _sustituir_nombres(text, names)


def restore(text: str, names: list[str]) -> str:
    """Deshace `[NOMBRE_n]` con la misma lista `names` usada al anonimizar."""

    def repl(m: re.Match) -> str:
        n = int(m.group(1))
        return names[n - 1] if 1 <= n <= len(names) else m.group(0)

    return _NOMBRE_RE.sub(repl, text)
