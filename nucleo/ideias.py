"""Ideias de edição em teste.

Nenhuma ideia vira regra para todos os vídeos. Cada corte novo recebe uma das ideias ligadas, e o Clipador
usa mais a que funciona melhor para você:
- o que você posta conta a favor; o que você apaga sem postar, ou troca no corte, conta contra;
- com o YouTube conectado, as visualizações de cada ideia contam ainda mais.
O sorteio é proporcional à chance de cada ideia ser a melhor (amostragem de Thompson): a melhor
aparece mais, e as outras continuam aparecendo de vez em quando, para o Clipador perceber se o gosto mudou.
"""
from __future__ import annotations

IDEIAS = {
    "padrao": {
        "nome": "Seu estilo",
        "descricao": "Tela dividida fixa e a legenda escolhida em Estilo do vídeo.",
        "estilo": {"camera_dinamica": False},
    },
    "react": {
        "nome": "React com câmera dinâmica",
        "descricao": "O jogo ocupa a tela quando conta a história, o rosto aparece de perto na reação, legenda curta e amarela na divisão.",
        "estilo": {"legenda": "react", "camera_dinamica": True},
    },
}
PADRAO_LIGADAS = {"padrao": True, "react": True}


def estilo(ident: str | None) -> dict:
    return dict((IDEIAS.get(ident or "") or {}).get("estilo") or {})


def nome(ident: str | None) -> str:
    return (IDEIAS.get(ident or "") or {}).get("nome") or ""
