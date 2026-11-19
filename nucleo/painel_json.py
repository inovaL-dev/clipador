"""Conversão de valores que o JSON padrão não aceita (números do numpy, conjuntos)."""


def para_json(valor):
    if hasattr(valor, "item") and callable(valor.item):
        return valor.item()
    if hasattr(valor, "tolist"):
        return valor.tolist()
    if isinstance(valor, (set, frozenset, tuple)):
        return list(valor)
    return str(valor)
