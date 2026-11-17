"""Règle de ponctuation commune aux contenus éditoriaux."""
import re


REGLE_TIRETS = (
    "N'utilise jamais de tiret cadratin (U+2014) ni de demi-cadratin (U+2013), "
    "y compris dans les titres, les incises et les descriptions. "
    "Reformule avec un point, une virgule ou des parenthèses. "
    "Conserve les traits d'union nécessaires."
)

_ENTITES_TIRETS = re.compile(r"&(?:[mn]dash|#0*821[12]|#x0*201[34]);", re.IGNORECASE)
_URL = r"""https?://[^\s<>"']+"""
_LIENS = re.compile(f"({_URL})")
_BALISES_ET_LIENS = re.compile(r"""(<!--.*?-->|<(?:[^'">]|"[^"]*"|'[^']*')+>|""" + _URL + ")", re.DOTALL)


def sans_tirets_longs(texte, *, html=False):
    """Nettoie le texte visible en conservant les URL et, en HTML, les balises."""
    if not isinstance(texte, str) or not texte:
        return texte

    morceaux = (_BALISES_ET_LIENS if html else _LIENS).split(texte)
    for i in range(0, len(morceaux), 2):
        morceau = _ENTITES_TIRETS.sub("\u2014", morceaux[i])
        if not html and i == 0:
            morceau = re.sub(r"(?m)^[^\S\r\n]*[\u2013\u2014]+[^\S\r\n]*", "", morceau)
        if not html and i == len(morceaux) - 1:
            morceau = re.sub(r"(?m)[^\S\r\n]*[\u2013\u2014]+[^\S\r\n]*$", "", morceau)
        morceau = re.sub(r"([.!?,;:])[^\S\r\n]*[\u2013\u2014]+[^\S\r\n]*", r"\1 ", morceau)
        morceau = re.sub(r"[^\S\r\n]*[\u2013\u2014]+[^\S\r\n]*(?=[.!?,;:])", "", morceau)
        morceaux[i] = re.sub(r"[^\S\r\n]*[\u2013\u2014]+[^\S\r\n]*", ", ", morceau)
    return "".join(morceaux)
