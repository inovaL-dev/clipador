"""Cria títulos e descrições, monta a agenda e envia os Shorts programados."""
from __future__ import annotations

import json
import math
import re
import threading
import time
import zlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .youtube import ContaYouTube, ErroYouTube

HORARIOS_PADRAO = ["08:00", "10:00", "12:00", "14:00", "16:00", "17:30", "19:00", "20:00", "21:00", "22:30"]
MARGEM_AGENDA = 20 * 60
MAXIMO_HORARIOS = 48
MAXIMO_POR_HORARIO = 20
MARGEM_TUDO = 10 * 60
MODOS_AGENDA = ("horarios", "dia", "agora")
POTENCIAIS = (0, 50, 60, 70, 75, 80, 85, 90, 95)  # 0: posta todos
ESTADOS_PENDENTES = ("fila", "erro")
DURACAO_MAXIMA_SHORT = 59.5
ESPERA_LIMITE_CANAL = 3600
JANELA_LIMITE_CANAL = 24 * 3600
INTERVALO_CONFERENCIA = 1800
VALIDADE_CONFERENCIA = 600

JOGOS = [
    (r"\bgta\s*(?:6|vi)\b|grand theft auto vi", "GTA 6", "GTA", ["GTA6", "GTAVI", "GTA", "RockstarGames", "GTA6Brasil", "Gaming"]),
    (r"\bminecraft\b", "Minecraft", "Minecraft", ["Minecraft", "MinecraftBrasil", "Gaming"]),
    (r"\bfortnite\b", "Fortnite", "Fortnite", ["Fortnite", "FortniteBrasil", "Gaming"]),
    (r"\bvalorant\b", "Valorant", "Valorant", ["Valorant", "ValorantBrasil", "Gaming"]),
    (r"\bcs\s*2\b|counter[- ]strike", "CS2", "CS2", ["CS2", "CounterStrike", "Gaming"]),
    (r"\bfree\s*fire\b", "Free Fire", "Free Fire", ["FreeFire", "FreeFireBrasil", "Gaming"]),
    (r"\broblox\b", "Roblox", "Roblox", ["Roblox", "RobloxBrasil", "Gaming"]),
    (r"\bea\s*(?:sports\s*)?fc\b|\bfifa\b", "EA FC", "EA FC", ["EAFC", "Futebol", "Gaming"]),
    (r"\bleague of legends\b|\blol\b", "LoL", "LoL", ["LeagueOfLegends", "LoL", "Gaming"]),
]
# (palavras na fala, assunto, plural, nome na descrição)
ASSUNTOS = [
    (r"\bmapa\b|vice city|leonida|\bcidade\b|\bpraia\b", "O MAPA", False, "o mapa"),
    (r"\bpol[ií]cia|policial|viatura|procurado", "A POLÍCIA", False, "a polícia"),
    (r"\bcarros?\b|\bmotos?\b|dirigir|\bbarcos?\b|\bavi[aã]o\b|helic[oó]ptero|ve[ií]culos?", "OS CARROS", True, "os carros"),
    (r"\barmas?\b|\btiros?\b|atirar|pistola|fuzil", "OS TIROS", True, "os tiros"),
    (r"gr[aá]ficos?|realis[mt]|detalhes?|f[ií]sica", "OS GRÁFICOS", True, "os gráficos"),
    (r"\bmiss[aã]o|miss[oõ]es|hist[oó]ria|cutscene", "A HISTÓRIA", False, "a história"),
    (r"\bl[uú]cia\b|\bjason\b|personage", "OS PERSONAGENS", True, "os personagens"),
    (r"jogabilidade|gameplay|controle|mec[aâ]nica", "A JOGABILIDADE", False, "a jogabilidade"),
]
FRASES_REACAO = {
    "admirado": ["{S} FICOU SEM PALAVRAS {L}", "{S} NÃO ACREDITOU NISSO {L}"],
    "risada": ["{S} NÃO AGUENTOU DE RIR {L}", "O CHAT NÃO PAROU DE RIR {L}"],
    "choque": ["NINGUÉM ESPERAVA POR ISSO {L}", "O CHAT FICOU CHOCADO {L}"],
    "jogo": ["OLHA O QUE ACONTECEU {L}", "ISSO ACONTECEU MESMO {L}"],
    "clipe": ["O CHAT PEDIU PRA CLIPAR ISSO {L}"],
    "hype": ["O CHAT FOI À LOUCURA {L}", "ESSE MOMENTO EXPLODIU O CHAT {L}"],
    "streamer": ["A REAÇÃO DE {S} {L}", "{S} REAGIU ASSIM {L}"],
}
EMOJIS = {"risada": "😂🔥", "jogo": "🎮🔥", "hype": "🔥🎮", "clipe": "🔥🎮"}


def _limpar(texto: str) -> str:
    return re.sub(r"[<>]", "", re.sub(r"[ \t]+", " ", texto or "")).strip()


def _hashtag(nome: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.findall(r"[0-9A-Za-zÀ-ÿ]+", nome or ""))


def texto_do_corte(meta: dict) -> str:
    return " ".join(p["p"] for g in meta.get("grupos") or [] for p in g.get("palavras", []))


def gerar_textos(meta: dict, recentes: set[str] | None = None) -> dict:
    recentes = recentes or set()
    fala = texto_do_corte(meta)
    base = f"{meta.get('titulo_live') or ''} {fala}"
    jogo = next((j for j in JOGOS if re.search(j[0], base, re.I)), None)
    assunto = next((a for a in ASSUNTOS if re.search(a[0], fala, re.I)), None) if jogo else None
    streamer = meta.get("canal") or "o streamer"
    s = streamer.upper()
    lugar = f"NO {jogo[1].upper()}" if jogo else "AO VIVO"
    semente = zlib.crc32(meta["id"].encode())

    opcoes: list[str] = []
    if assunto:
        verbo, nome, plural = ("SÃO" if assunto[2] else "É"), assunto[1], assunto[2]
        alvo = jogo[1].upper()
        opcoes = [f"{nome} DO {alvo} {verbo} ASSIM", f"OLHA COMO {'FICARAM' if plural else 'FICOU'} {nome} DO {alvo}",
                  f"{nome} DO {alvo} {'SURPREENDERAM' if plural else 'SURPREENDEU'} {s}"]
    else:
        modelos = FRASES_REACAO.get(meta.get("reacao"), [])
        opcoes = [m.format(S=s, L=lugar) for m in modelos]
        if meta.get("gancho"):
            opcoes.append(f"“{meta['gancho'].upper().rstrip('?!.')}” {lugar}")
    if not opcoes:
        opcoes = [f"OLHA O QUE ACONTECEU {lugar}"]
    opcoes = opcoes[semente % len(opcoes):] + opcoes[:semente % len(opcoes)]

    emoji = EMOJIS.get(meta.get("reacao"), "😱🔥")
    tag_titulo = f"#{jogo[3][0]} #Shorts" if jogo else "#Cortes #Shorts"
    fim = f"?! {emoji} {tag_titulo}"
    titulo = ""
    for opcao in opcoes:
        curto = opcao if len(opcao) + len(fim) <= 96 else opcao[: 96 - len(fim)].rsplit(" ", 1)[0]
        titulo = _limpar(curto + fim)
        if titulo not in recentes:
            break

    franquia = jogo[2] if jogo else streamer
    if assunto:
        abertura = f"{assunto[3][:1].upper()}{assunto[3][1:]} de {jogo[1]} {'estão' if assunto[2] else 'está'} dando o que falar! 🎮🔥"
        pergunta = f"Será que o novo {franquia} vai entregar uma experiência muito mais realista e surpreendente?"
        chamada = f"Confira esse trecho e me conta: o que você achou d{assunto[3]} de {jogo[1]}? 👀"
    elif jogo:
        abertura = f"Olha esse momento de {streamer} jogando {jogo[1]}! 🎮🔥"
        pergunta = f"Será que o novo {franquia} vai surpreender todo mundo?" if jogo[1] == "GTA 6" else "Você esperava por essa reação?"
        chamada = f"Confira esse trecho e me conta: o que você mais quer ver em {jogo[1]}? 👀"
    else:
        abertura = f"Olha esse momento da live de {streamer}! 🔥"
        pergunta = "Você esperava por essa reação?"
        chamada = "Confira esse trecho e me conta o que você achou! 👀"

    marcas = (jogo[3] if jogo else ["Cortes", "Live", "Gaming"]) + [_hashtag(streamer), "Cortes", "Shorts"]
    marcas = list(dict.fromkeys(m for m in marcas if m))
    credito = meta.get("credito") or streamer
    linha_credito = f"🎥 Créditos: {credito}" if streamer.casefold() in credito.casefold() else f"🎥 Créditos: {streamer} ({credito})"
    if meta.get("link"):
        linha_credito += f"\n🔗 Live original: {meta['link']}"
    descricao = (
        f"{abertura}\n\n{pergunta}\n\n{chamada}\n\n"
        f"💬 Deixe sua opinião nos comentários!\n"
        f"👍 Curta e inscreva-se para acompanhar mais clipes e novidades de {franquia}!\n\n"
        f"{linha_credito}\n\n" + " ".join(f"#{m}" for m in marcas)
    )
    tags, total = [], 0
    for tag in [*marcas, streamer, jogo[1] if jogo else "live", "cortes de live", "shorts"]:
        if total + len(tag) + 1 > 400:
            break
        if tag not in tags:
            tags.append(tag)
            total += len(tag) + 1
    return {"titulo": titulo[:100], "descricao": _limpar(descricao)[:4900], "tags": tags}


class Postagem:
    def __init__(self, motor):
        self.motor = motor
        self.arquivo = Path(motor.dados) / "postagem.json"
        self.conta = ContaYouTube(Path(motor.dados))
        dados = motor._ler(self.arquivo, {})
        self.config = {"horarios": HORARIOS_PADRAO, "automatico": False, "auditoria": False, "modo": "horarios", "por_horario": 1, "pastas": None,
                       "dia_unico": "", "janela_inicio": "06:00", "janela_fim": "23:30",
                       "potencial_minimo": 85, "melhores_primeiro": True, **dados.get("config", {})}
        if self.config["pastas"] is None:
            # Na primeira vez, continua só com a live mais recente; as outras ficam guardadas.
            recentes = motor.pastas()
            self.config["pastas"] = {recentes[0]["id"]: True} if recentes else {}
        self.guardados: dict[str, dict] = dados.get("guardados", {})
        self.itens: dict[str, dict] = dados.get("itens", {})
        self.ordem: list[str] = [i for i in dados.get("ordem", []) if i in self.itens]
        self.pausa_ate = 0.0
        self.limite_ate = float(dados.get("limite_ate", 0))
        self.aviso = ""
        self.conferido_canal: str | None = None
        self.conferido_em = 0.0
        self.proxima_conferencia = 0.0
        self.conferencia = {"quando": 0.0, "tirados": 0}
        self.enviando: str | None = None
        self.trava = threading.RLock()
        for item in self.itens.values():
            if item["estado"] == "enviando":
                item["estado"] = "fila"
        threading.Thread(target=self._trabalhar, daemon=True).start()

    def _salvar(self) -> None:
        with self.trava:
            self.motor._gravar(self.arquivo, {"config": self.config, "itens": self.itens, "ordem": self.ordem,
                                              "limite_ate": self.limite_ate, "guardados": self.guardados})

    def ativar_pasta_nova(self, pasta: str) -> None:
        """Respeita a escolha feita depois: uma pasta desmarcada não volta sozinha."""
        with self.trava:
            if pasta not in self.config["pastas"]:
                self.config["pastas"][pasta] = True
                self._salvar()

    def definir_pasta(self, pasta: str, ativa: bool) -> None:
        if pasta not in {p["id"] for p in self.motor.pastas()}:
            raise ValueError("Pasta não encontrada.")
        with self.trava:
            self.config["pastas"][pasta] = bool(ativa)
            self.proxima_conferencia = 0.0
            self._salvar()
        self.sincronizar()

    def _passa(self, meta: dict) -> bool:
        """O corte tem potencial suficiente para entrar na agenda? Você pode liberar um corte à mão."""
        minimo = int(self.config.get("potencial_minimo") or 0)
        if not minimo or meta.get("forcar_postagem"):
            return True
        nota = (meta.get("potencial") or {}).get("nota")
        return nota is not None and nota >= minimo

    @staticmethod
    def _nota(meta: dict | None) -> int:
        return int(((meta or {}).get("potencial") or {}).get("nota") or 0)

    def sincronizar(self) -> None:
        with self.trava:
            mudou = False
            cortes = sorted(self.motor.cortes.values(), key=lambda m: m["criado"])
            recentes = {i["titulo"] for i in self.itens.values()}
            ativas = self.config["pastas"]
            for corte_id in list(self.ordem):
                item, meta = self.itens[corte_id], self.motor.cortes.get(corte_id)
                if meta and meta.get("postado") and item["estado"] in ESTADOS_PENDENTES:
                    # Marcado como postado no editor: não pode continuar esperando na fila.
                    item.update(estado="publicado", marcado=True, erro=None, quando=item["quando"] or time.time())
                    mudou = True
                elif meta and item.get("marcado") and not meta.get("postado"):
                    del self.itens[corte_id]
                    self.ordem.remove(corte_id)
                    mudou = True
                    continue
                if meta and item["estado"] in ESTADOS_PENDENTES and (not ativas.get(meta.get("pasta")) or not self._passa(meta)):
                    # Sai da agenda sem perder os textos: volta igual se a pasta for marcada de novo.
                    self.guardados[corte_id] = {"titulo": item["titulo"], "descricao": item["descricao"], "tags": item["tags"]}
                    del self.itens[corte_id]
                    self.ordem.remove(corte_id)
                    mudou = True
            for meta in cortes:
                if meta["status"] == "pronto" and meta["id"] not in self.itens and not meta.get("postado") and ativas.get(meta.get("pasta")) and self._passa(meta):
                    textos = self.guardados.pop(meta["id"], None) or gerar_textos(meta, recentes)
                    recentes.add(textos["titulo"])
                    self.itens[meta["id"]] = {"id": meta["id"], **textos, "estado": "fila", "quando": 0, "video_id": None,
                                              "erro": None, "progresso": 0}
                    posicao = len(self.ordem)
                    if self.config.get("melhores_primeiro", True):  # entra antes dos que ainda esperam e têm potencial menor
                        nota = self._nota(meta)
                        posicao = next((n for n, i in enumerate(self.ordem) if self.itens[i]["estado"] in ESTADOS_PENDENTES
                                        and not self.itens[i].get("movido") and self._nota(self.motor.cortes.get(i)) < nota), posicao)
                    self.ordem.insert(posicao, meta["id"])
                    mudou = True
            for corte_id in [i for i in self.ordem if i not in self.motor.cortes]:
                if self.itens[corte_id]["estado"] in ESTADOS_PENDENTES:
                    del self.itens[corte_id]
                    self.ordem.remove(corte_id)
                    mudou = True
            mudou = self._encurtar_longos() or mudou
            agora = time.time()
            if self.limite_ate and self.limite_ate <= agora - 6 * ESPERA_LIMITE_CANAL:
                self.limite_ate = 0.0
                mudou = True
            for item in self.itens.values():
                if item["estado"] == "agendado" and item["quando"] <= agora:
                    item["estado"] = "publicado"
                    mudou = True
            if self._reagendar(agora) or mudou:
                self._salvar()

    def _encurtar_longos(self) -> bool:
        """Shorts acima de 1 minuto com reivindicação são bloqueados, então a fila só envia até 59 s."""
        mudou = False
        for corte_id in self.ordem:
            item = self.itens[corte_id]
            meta = self.motor.cortes.get(corte_id) or {}
            if item["estado"] not in ESTADOS_PENDENTES or meta.get("duracao", 0) <= DURACAO_MAXIMA_SHORT:
                continue
            if meta.get("nao_encurtar"):
                if item["estado"] != "erro":
                    item["estado"], item["erro"] = "erro", "Este corte tem mais de 1 minuto e não pôde ser encurtado."
                    mudou = True
            elif meta.get("status") == "pronto":
                self.motor.pedir_encurtar(corte_id)
        return mudou

    def _reagendar(self, agora: float) -> bool:
        ocupados = Counter(i["quando"] for i in self.itens.values() if i["estado"] not in ESTADOS_PENDENTES)
        pendentes = [self.itens[i] for i in self.ordem if self.itens[i]["estado"] in ESTADOS_PENDENTES]
        mudou = False
        for item, quando in zip(pendentes, self._vagas(agora, ocupados, len(pendentes))):
            if item["quando"] != quando:
                item["quando"] = quando
                mudou = True
        return mudou

    @staticmethod
    def _proximo_minuto(t: float) -> float:
        return float(math.ceil(t / 60) * 60)

    def _vagas_seguidas(self, agora: float, ocupados: Counter):
        """Tudo de uma vez: um vídeo por minuto, para manter a ordem da fila."""
        t = self._proximo_minuto(agora + MARGEM_TUDO)
        while True:
            if t not in ocupados:
                yield t
            t += 60.0

    def _vagas_do_dia(self, agora: float, ocupados: Counter, total: int):
        """Distribui a fila inteira por igual dentro da janela do dia escolhido."""
        hoje = datetime.fromtimestamp(agora).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            dia = max(datetime.strptime(self.config.get("dia_unico") or "", "%Y-%m-%d"), hoje)
        except ValueError:
            dia = hoje
        h_ini, m_ini = (int(v) for v in self.config["janela_inicio"].split(":"))
        h_fim, m_fim = (int(v) for v in self.config["janela_fim"].split(":"))
        minimo = self._proximo_minuto(agora + MARGEM_AGENDA)
        while True:
            fim = dia.replace(hour=h_fim, minute=m_fim).timestamp()
            inicio = max(dia.replace(hour=h_ini, minute=m_ini).timestamp(), minimo)
            if inicio <= fim:
                break
            dia += timedelta(days=1)  # a janela de hoje já passou
        passo = max(60.0, math.floor((fim - inicio) / max(total - 1, 1) / 60) * 60.0)
        t = inicio
        while True:
            while t in ocupados:
                t += 60.0
            yield t
            t += passo

    def _vagas(self, agora: float, ocupados: Counter, total: int):
        # Enquanto o canal está no limite, nada pode ser programado antes de ele liberar.
        agora = max(agora, self.limite_ate)
        modo = self.config.get("modo", "horarios")
        if modo == "agora":
            yield from self._vagas_seguidas(agora, ocupados)
            return
        if modo == "dia":
            yield from self._vagas_do_dia(agora, ocupados, total)
            return
        dia = datetime.fromtimestamp(agora).replace(hour=0, minute=0, second=0, microsecond=0)
        horarios = sorted(self.config["horarios"])
        for _ in range(3660):
            for texto in horarios:
                h, m = (int(v) for v in texto.split(":"))
                t = dia.replace(hour=h, minute=m).timestamp()
                if t >= agora + MARGEM_AGENDA:
                    # Cada horário recebe vários vídeos, descontando os que já foram agendados nele.
                    for _ in range(max(0, int(self.config.get("por_horario", 1)) - ocupados[t])):
                        yield t
            dia += timedelta(days=1)

    def salvar_config(self, dados: dict) -> None:
        refiltrar = False
        with self.trava:
            if "horarios" in dados:
                horarios = sorted(set(dados["horarios"]))
                if not 1 <= len(horarios) <= MAXIMO_HORARIOS or not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h) for h in horarios):
                    raise ValueError(f"Informe de 1 a {MAXIMO_HORARIOS} horários válidos.")
                self.config["horarios"] = horarios
            if "por_horario" in dados:
                try:
                    por_horario = int(dados["por_horario"])
                except (TypeError, ValueError):
                    por_horario = 0
                if not 1 <= por_horario <= MAXIMO_POR_HORARIO:
                    raise ValueError(f"Escolha de 1 a {MAXIMO_POR_HORARIO} vídeos por horário.")
                self.config["por_horario"] = por_horario
            if "modo" in dados:
                if dados["modo"] not in MODOS_AGENDA:
                    raise ValueError("Escolha como os vídeos serão postados.")
                self.config["modo"] = dados["modo"]
            if "dia_unico" in dados:
                try:
                    datetime.strptime(str(dados["dia_unico"]), "%Y-%m-%d")
                except ValueError:
                    raise ValueError("Escolha o dia da postagem.") from None
                self.config["dia_unico"] = str(dados["dia_unico"])
            if "janela_inicio" in dados or "janela_fim" in dados:
                inicio = str(dados.get("janela_inicio", self.config["janela_inicio"]))
                fim = str(dados.get("janela_fim", self.config["janela_fim"]))
                if not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h) for h in (inicio, fim)) or inicio >= fim:
                    raise ValueError("O horário final precisa ser depois do inicial.")
                self.config["janela_inicio"], self.config["janela_fim"] = inicio, fim
            if "potencial_minimo" in dados:
                try:
                    minimo = int(dados["potencial_minimo"])
                except (TypeError, ValueError):
                    minimo = -1
                if minimo not in POTENCIAIS:
                    raise ValueError("Escolha um potencial mínimo da lista.")
                self.config["potencial_minimo"] = minimo
            if "melhores_primeiro" in dados:
                self.config["melhores_primeiro"] = bool(dados["melhores_primeiro"])
            refiltrar = "potencial_minimo" in dados
            if "auditoria" in dados:
                self.config["auditoria"] = bool(dados["auditoria"])
                if not self.config["auditoria"]:
                    self.config["automatico"] = False
            if "automatico" in dados:
                ligar = bool(dados["automatico"])
                if ligar and not self.config["auditoria"]:
                    raise ValueError("Confirme primeiro que o projeto foi aprovado na auditoria do YouTube.")
                if ligar and not self.conta.conectada:
                    raise ValueError("Conecte o canal do YouTube antes de ligar o envio automático.")
                self.config["automatico"] = ligar
                self.pausa_ate = 0.0
            self._reagendar(time.time())
            self._salvar()
        if refiltrar:
            self.sincronizar()

    def editar(self, corte_id: str, dados: dict) -> dict:
        with self.trava:
            item = self.itens[corte_id]
            if item["estado"] not in ESTADOS_PENDENTES:
                raise ValueError("Este vídeo já foi agendado. Edite direto no YouTube Studio.")
            if "titulo" in dados:
                titulo = _limpar(str(dados["titulo"]))
                if not 1 <= len(titulo) <= 100:
                    raise ValueError("O título precisa ter de 1 a 100 caracteres.")
                item["titulo"] = titulo
            if "descricao" in dados:
                item["descricao"] = _limpar(str(dados["descricao"]))[:4900]
            self._salvar()
            return item

    def mover(self, corte_id: str, direcao: int) -> None:
        with self.trava:
            pendentes = [i for i in self.ordem if self.itens[i]["estado"] in ESTADOS_PENDENTES]
            pos = pendentes.index(corte_id)
            alvo = pos + (1 if direcao > 0 else -1)
            if not 0 <= alvo < len(pendentes):
                return
            a, b = self.ordem.index(pendentes[pos]), self.ordem.index(pendentes[alvo])
            self.ordem[a], self.ordem[b] = self.ordem[b], self.ordem[a]
            self.itens[pendentes[pos]]["movido"] = self.itens[pendentes[alvo]]["movido"] = True  # a sua ordem vale mais que o potencial
            self._reagendar(time.time())
            self._salvar()

    def marcar_agendado(self, corte_id: str) -> None:
        with self.trava:
            item = self.itens[corte_id]
            if item["estado"] not in ESTADOS_PENDENTES:
                raise ValueError("Este vídeo já foi agendado.")
            item["estado"], item["erro"], item["marcado"] = "agendado", None, True
            self.motor.cortes[corte_id]["postado"] = True
            self.motor._salvar_corte(self.motor.cortes[corte_id])
            self._reagendar(time.time())
            self._salvar()

    def _devolver(self, corte_id: str) -> bool:
        item = self.itens[corte_id]
        meta = self.motor.cortes.get(corte_id)
        arquivo = Path(self.motor.saida) / corte_id / "corte.mp4"
        if item["estado"] != "agendado" or item["quando"] <= time.time() or not meta or not arquivo.exists():
            return False
        if item.get("canal_envio") and item["canal_envio"] == self._canal_atual():
            return False  # já está neste canal: voltar para a fila criaria um vídeo repetido
        item.pop("marcado", None)
        item.update({"estado": "fila", "quando": 0, "erro": None, "progresso": 0, "liberado": True,
                     "video_antigo": item.get("video_id") or item.get("video_antigo"), "video_id": None})
        meta["postado"] = False
        self.motor._salvar_corte(meta)
        return True

    def voltar_para_fila(self, corte_id: str) -> None:
        """Devolve um Short agendado para a fila, para ser postado no canal conectado agora."""
        with self.trava:
            if not self._devolver(corte_id):
                raise ValueError("Este vídeo já está no canal conectado ou já foi publicado, então não pode voltar para a fila.")
            self._reagendar(time.time())
            self._salvar()

    def voltar_agendados(self) -> dict:
        with self.trava:
            if self.conferido_canal != self._canal_atual():
                raise ValueError("Aguarde a conferência com o canal e tente de novo.")
            total = sum(self._devolver(i) for i in self.ordem if self._devolvivel(self.itens[i]))
            if not total:
                raise ValueError("Não há vídeos agendados para devolver à fila.")
            self._reagendar(time.time())
            self._salvar()
            return {"total": total}

    def _canal_atual(self) -> str | None:
        return (self.conta.canal or {}).get("id")

    def _devolvivel(self, item: dict) -> bool:
        """Só volta em lote o que foi enviado pelo sistema a outro canal."""
        return item["estado"] == "agendado" and bool(item.get("video_id")) and item.get("canal_envio") != self._canal_atual()

    def _repetido(self, item: dict) -> bool:
        return item["estado"] in ESTADOS_PENDENTES and bool(item.get("video_antigo")) and not item.get("liberado")

    def decidir_repetidos(self, acao: str) -> dict:
        if acao not in ("tirar", "manter"):
            raise ValueError("Escolha o que fazer com esses vídeos.")
        with self.trava:
            alvo = [i for i in self.itens.values() if self._repetido(i)]
            for item in alvo:
                if acao == "manter":
                    item["liberado"] = True
                    continue
                item.update(estado="publicado", video_id=item["video_antigo"], marcado=True, erro=None, quando=item["quando"] or time.time())
                meta = self.motor.cortes.get(item["id"])
                if meta:
                    meta["postado"] = True
                    self.motor._salvar_corte(meta)
            self._reagendar(time.time())
            self._salvar()
            return {"total": len(alvo)}

    @staticmethod
    def _titulo_chave(titulo: str) -> str:
        return re.sub(r"\s+", " ", titulo or "").strip().casefold()

    def _ligar_video(self, item: dict, video: dict, canal: str, agora: float) -> bool:
        pendente = item["estado"] in ESTADOS_PENDENTES
        item["canal_envio"] = canal
        item["video_id"] = video["id"]
        if not pendente:
            return False
        futuro = video["publicar_em"] > agora
        item.update(estado="agendado" if futuro else "publicado", quando=video["publicar_em"] if futuro else (video["publicado"] or agora),
                    erro=None, progresso=100)
        meta = self.motor.cortes.get(item["id"])
        if meta:
            meta["postado"] = True
            self.motor._salvar_corte(meta)
        return True

    def conferir_canal(self) -> int:
        """Compara a fila com o canal: o que já está lá não pode ser enviado de novo."""
        canal = self._canal_atual() or (self.conta.buscar_canal() or {}).get("id")
        videos = self.conta.videos_do_canal()
        agora, tirados = time.time(), 0
        with self.trava:
            por_id = {v["id"]: v for v in videos}
            usados: set[str] = set()
            for item in self.itens.values():
                video = por_id.get(item.get("video_id") or item.get("video_antigo"))
                if video and item["estado"] != "enviando":
                    tirados += self._ligar_video(item, video, canal, agora)
                    usados.add(video["id"])
            soltos: dict[str, list[dict]] = {}
            for video in videos:
                if video["id"] not in usados:
                    soltos.setdefault(self._titulo_chave(video["titulo"]), []).append(video)
            # Primeiro os já marcados como postados, para um título repetido não tirar outro clipe da fila.
            ordem = sorted((self.itens[i] for i in self.ordem), key=lambda i: i["estado"] in ESTADOS_PENDENTES)
            for item in ordem:
                if item.get("video_id") or item["estado"] == "enviando":
                    continue
                lista = soltos.get(self._titulo_chave(item["titulo"]))
                if lista:
                    tirados += self._ligar_video(item, lista.pop(0), canal, agora)
            self.conferido_canal, self.conferido_em = canal, agora
            self.proxima_conferencia = agora + INTERVALO_CONFERENCIA
            self.conferencia = {"quando": agora, "tirados": self.conferencia["tirados"] + tirados}
            if self.aviso.startswith("A postagem encontrou um problema"):
                self.aviso = ""
            self._reagendar(agora)
            self._salvar()
        if tirados:
            self.motor.evento("YouTube", "pronto", f"{tirados} Shorts que já estavam no canal saíram da fila")
        return tirados

    def _conferir_se_preciso(self) -> None:
        if not self.conta.conectada or time.time() < self.proxima_conferencia:
            return
        self.proxima_conferencia = time.time() + 300  # nova tentativa se a conferência falhar
        self.conferir_canal()

    def item_completo(self, corte_id: str) -> dict:
        return self.itens[corte_id]

    def tentar_de_novo(self, corte_id: str) -> None:
        with self.trava:
            item = self.itens[corte_id]
            if item["estado"] == "erro":
                item["estado"], item["erro"] = "fila", None
            self.pausa_ate = 0.0
            self._salvar()

    def remover(self, corte_id: str) -> None:
        with self.trava:
            item = self.itens[corte_id]
            if item["estado"] not in ESTADOS_PENDENTES:
                raise ValueError("Este vídeo já foi agendado. Remova direto no YouTube Studio.")
            del self.itens[corte_id]
            self.ordem.remove(corte_id)
            self.motor.cortes[corte_id]["postado"] = True  # não volta sozinho para a fila
            self.motor._salvar_corte(self.motor.cortes[corte_id])
            self._reagendar(time.time())
            self._salvar()

    def apagar(self, ids: list[str]) -> dict:
        """Apaga de vez os Shorts que ainda não foram enviados."""
        if not isinstance(ids, list) or not ids or len(ids) > 500:
            raise ValueError("Escolha os Shorts que serão apagados.")
        apagar = []
        with self.trava:
            for corte_id in dict.fromkeys(str(i) for i in ids):
                item, meta = self.itens.get(corte_id), self.motor.cortes.get(corte_id)
                if not item or not meta or item["estado"] not in ESTADOS_PENDENTES or meta.get("status") not in ("pronto", "erro"):
                    continue
                meta["postado"] = True  # impede que a fila traga o corte de volta antes de ele sumir
                del self.itens[corte_id]
                self.ordem.remove(corte_id)
                self.guardados.pop(corte_id, None)
                apagar.append(corte_id)
            self._reagendar(time.time())
            self._salvar()
        for corte_id in apagar:
            self.motor.excluir_corte(corte_id)
        return {"total": len(apagar), "ignorados": len(ids) - len(apagar)}

    def enviar_teste(self) -> str:
        """Envia o próximo vídeo como privado para confirmar que a conexão funciona."""
        with self.trava:
            alvo = next((self.itens[i] for i in self.ordem if self.itens[i]["estado"] in ESTADOS_PENDENTES), None)
        if not alvo:
            raise ValueError("A fila está vazia. Aguarde um corte ficar pronto.")
        arquivo = Path(self.motor.saida) / alvo["id"] / "corte.mp4"
        return self.conta.enviar(arquivo, f"Teste do clipador: {alvo['titulo']}"[:100], alvo["descricao"], alvo["tags"], None)

    def resumo(self) -> dict:
        with self.trava:
            posicao = {corte_id: n for n, corte_id in enumerate(self.ordem)}
            lista = sorted(self.itens.values(), key=lambda i: (i["quando"], posicao.get(i["id"], 0)))
            ativos = [{k: v for k, v in i.items() if k not in ("descricao", "tags")} for i in lista if i["estado"] != "publicado"]
            for item in ativos:
                meta = self.motor.cortes.get(item["id"]) or {}
                item.update({"canal": meta.get("canal", ""), "duracao": meta.get("duracao", 0), "versao": meta.get("versao", 0), "pasta": meta.get("pasta"),
                             "potencial": (meta.get("potencial") or {}).get("nota")})
            return {
                "config": self.config, "itens": ativos, "por_dia": len(self.config["horarios"]) * int(self.config.get("por_horario", 1)),
                "total_fila": sum(1 for i in lista if i["estado"] in ESTADOS_PENDENTES),
                "agendados": sum(1 for i in lista if i["estado"] == "agendado"),
                "publicados": sum(1 for i in lista if i["estado"] == "publicado"),
                "aviso": self.aviso, "pausa_ate": self.pausa_ate if self.pausa_ate > time.time() else 0,
                "limite_ate": self.limite_ate if self.limite_ate > time.time() else 0,
                "pastas": self._resumo_pastas(lista),
                "repetidos": sum(1 for i in lista if self._repetido(i)),
                "devolviveis": sum(1 for i in lista if self._devolvivel(i)) if self.conferido_canal and self.conferido_canal == self._canal_atual() else 0,
                "conferencia": self.conferencia,
                "abaixo_minimo": sum(1 for m in self.motor.cortes.values() if m.get("status") == "pronto" and not m.get("postado")
                                     and self.config["pastas"].get(m.get("pasta")) and m["id"] not in self.itens and not self._passa(m)),
                "conta": {"tem_cliente": self.conta.tem_cliente, "conectada": self.conta.conectada, "canal": self.conta.canal},
            }

    def _resumo_pastas(self, lista: list[dict]) -> list[dict]:
        fila: Counter = Counter()
        agendados: Counter = Counter()
        for item in lista:
            pasta = (self.motor.cortes.get(item["id"]) or {}).get("pasta")
            if item["estado"] in ESTADOS_PENDENTES:
                fila[pasta] += 1
            elif item["estado"] == "agendado":
                agendados[pasta] += 1
        return [{**p, "ativa": bool(self.config["pastas"].get(p["id"])), "na_fila": fila[p["id"]], "agendados": agendados[p["id"]]}
                for p in self.motor.pastas()]

    def _pode_enviar(self, corte_id: str) -> bool:
        meta = self.motor.cortes.get(corte_id) or {}
        if self._repetido(self.itens[corte_id]):
            return False  # já foi enviado antes: só sai de novo se você liberar
        return meta.get("status") == "pronto" and meta.get("duracao", 0) <= DURACAO_MAXIMA_SHORT

    def _trabalhar(self) -> None:
        while not self.motor.fim.is_set():
            try:
                self.sincronizar()
                self._conferir_se_preciso()
                if self.config["automatico"] and self.conta.conectada and time.time() >= self.pausa_ate:
                    self._enviar_proximo()
            except Exception as e:
                self.aviso = f"A postagem encontrou um problema: {e}"
            self.motor.fim.wait(float(self.motor.espera_postagem))

    def _enviar_proximo(self) -> None:
        if self.conferido_canal != self._canal_atual() or time.time() - self.conferido_em > VALIDADE_CONFERENCIA:
            self.conferir_canal()  # nunca envia sem saber o que já está no canal
        with self.trava:
            agora = time.time()
            self._reagendar(agora)
            item = next((self.itens[i] for i in self.ordem if self.itens[i]["estado"] == "fila" and self._pode_enviar(i)), None)
            if not item:
                return
            item["estado"], item["progresso"] = "enviando", 0
            self._salvar()
        arquivo = Path(self.motor.saida) / item["id"] / "corte.mp4"
        try:
            video = self.conta.enviar(
                arquivo, item["titulo"], item["descricao"], item["tags"], item["quando"],
                lambda f: item.__setitem__("progresso", round(f * 100)),
            )
        except ErroYouTube as e:
            self._tratar_erro(item, e)
            return
        except OSError as e:
            with self.trava:
                item["estado"] = "fila"
                self.aviso = f"Sem conexão com o YouTube. Nova tentativa em instantes. ({type(e).__name__})"
                self.pausa_ate = time.time() + 60
                self._salvar()
            return
        with self.trava:
            item.update({"estado": "agendado", "video_id": video, "erro": None, "progresso": 100, "canal_envio": self._canal_atual()})
            self.aviso = ""
            self.limite_ate = 0.0
            self.motor.cortes[item["id"]]["postado"] = True
            self.motor._salvar_corte(self.motor.cortes[item["id"]])
            self._salvar()
        self.motor.evento(item.get("canal") or "YouTube", "pronto", f"Short agendado: {item['titulo']}")

    def _tratar_erro(self, item: dict, erro: ErroYouTube) -> None:
        with self.trava:
            item["estado"] = "fila"
            if erro.motivo == "uploadLimitExceeded":
                # O limite do canal vale por 24 horas corridas a partir de quando foi atingido.
                agora = time.time()
                if self.limite_ate <= agora:
                    self.limite_ate = agora + JANELA_LIMITE_CANAL
                self.pausa_ate = agora + ESPERA_LIMITE_CANAL
                hora = datetime.fromtimestamp(self.limite_ate).strftime("%d/%m às %H:%M")
                self.aviso = f"O canal atingiu o limite diário de envios. A agenda foi ajustada e o envio volta sozinho por volta de {hora}."
                self._reagendar(agora)
            elif erro.motivo == "rateLimitExceeded":
                self.pausa_ate = time.time() + 900
                self.aviso = "O YouTube pediu uma pausa curta nos envios. Nova tentativa em 15 minutos."
            elif erro.motivo in ("quotaExceeded", "dailyLimitExceeded"):
                self.pausa_ate = _proxima_renovacao()
                self.aviso = "O limite diário de envios do YouTube acabou. O envio continua sozinho quando ele renovar."
            elif erro.motivo == "semConta":
                self.config["automatico"] = False
                self.aviso = str(erro)
            elif erro.motivo == "conexao" or erro.codigo >= 500:
                self.pausa_ate = time.time() + 300
                self.aviso = "O YouTube ficou instável. Nova tentativa em 5 minutos."
            else:
                item["estado"], item["erro"] = "erro", str(erro)[:300]
            self._salvar()


def _proxima_renovacao() -> float:
    """A cota do YouTube renova à meia-noite do horário do Pacífico."""
    agora = datetime.now(timezone.utc)
    alvo = agora.replace(hour=8, minute=10, second=0, microsecond=0)
    if alvo <= agora:
        alvo += timedelta(days=1)
    return alvo.timestamp()
