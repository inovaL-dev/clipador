"""Junta os melhores momentos de uma live em um único Short, com trocas rápidas de cena."""
from __future__ import annotations

import copy
import json
import os
import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from . import compositor as comp
from . import contexto as ctx
from . import edicao, estilos
from . import projeto as pj

CENAS_MONTAGEM = (3, 4, 5, 6)
LIMITE = 58.0
# Cada transição entra com um som que combina com o movimento dela.
TROCAS = (("chicote", "whoosh_rapido", .62), ("glitch", "glitch", .46), ("impulso", "zoom_in", .55), ("queda", "swipe", .66),
          ("clarao_rapido", "boom_grave", .5), ("giro", "whoosh_rapido", .6), ("rgb", "transicao_digital", .48), ("desfoque_rapido", "swipe", .6))
FAMILIAS = {"chicote": ("chicote", "queda", "giro"), "clarao": ("clarao_rapido", "impulso"), "suave": ("desfoque_rapido", "impulso"), "corte": ("impulso", "glitch", "rgb")}
TITULOS = ("Os {n} melhores momentos da live", "{n} momentos que você precisa ver", "O melhor da live em {n} cenas")


def janela(meta: dict, alvo: float) -> tuple[float, float]:
    """Escolhe o trecho da ação sem começar nem terminar no meio de uma frase."""
    total = float(meta.get("duracao_fonte") or meta.get("duracao") or 0)
    momento = float(meta["momento_fonte"]) if meta.get("momento_fonte") is not None else total * .62
    momento = min(max(0.0, momento), total)
    ini = max(0.0, momento - alvo * .42)
    fim = min(total, ini + alvo)
    ini = max(0.0, fim - alvo)
    grupos = [g["palavras"] for g in meta.get("grupos") or [] if g.get("palavras")]
    inicios = [float(p[0]["ini"]) for p in grupos if ini - 2.2 <= float(p[0]["ini"]) <= min(ini + 1.6, momento - .6)]
    fins = [float(p[-1]["fim"]) for p in grupos if max(fim - 2.2, momento + 1.2) <= float(p[-1]["fim"]) <= fim + 2.5]
    if inicios:
        ini = max(0.0, min(inicios, key=lambda t: abs(t - ini)) - .08)
    if fins:
        fim = min(total, min(fins, key=lambda t: abs(t - fim)) + .22)
    return round(ini, 3), round(max(ini + 2.0, fim), 3)


def escolher(cortes: list[dict], n: int) -> list[dict]:
    """Prefere os momentos mais fortes, variando o tipo de reação."""
    restantes, saida, vistos = sorted(cortes, key=lambda m: (float(m.get("forca") or 0), m["criado"]), reverse=True), [], {}
    while restantes and len(saida) < n:
        m = max(restantes, key=lambda x: float(x.get("forca") or 0) - 18 * vistos.get(x.get("reacao"), 0))
        restantes.remove(m); saida.append(m); vistos[m.get("reacao")] = vistos.get(m.get("reacao"), 0) + 1
    return saida


def ordenar(cenas: list[dict]) -> list[dict]:
    """Abre com o momento mais forte e fecha com o segundo mais forte."""
    if len(cenas) < 3:
        return cenas
    forca = sorted(cenas, key=lambda m: float(m.get("forca") or 0), reverse=True)
    meio = sorted(forca[2:], key=lambda m: float(m.get("pos_live") if m.get("pos_live") is not None else m["criado"]))
    return [forca[0], *meio, forca[1]]


def sequencia_trocas(perfil: dict | None) -> list[tuple]:
    """Usa primeiro as transições mais comuns nos vídeos de exemplo."""
    preferidas = [t for f in (perfil or {}).get("transicoes") or [] for t in FAMILIAS.get(f, ())]
    ordem = list(dict.fromkeys([*preferidas, *(t[0] for t in TROCAS)]))
    return [next(t for t in TROCAS if t[0] == nome) for nome in ordem]


def _ligar(origem: Path, destino: Path) -> None:
    try:
        os.link(origem, destino)  # não ocupa espaço de novo e continua valendo se o corte original for apagado
    except OSError:
        shutil.copy2(origem, destino)


def aplicar_receita(final: dict, receita: dict, raiox: dict | None, visual: dict, total: float, textos: dict, efx: dict, leg: dict, audio: dict, biblioteca) -> None:
    """Coloca abertura, tarjas, marca e chamada final por cima das cenas."""
    cor = "#" + estilos.CORES[visual.get("cor") or "amarelo"]
    tarja = lambda tam, fundo="#FFFFFF", texto="#101010": {"fonte": "Poppins-Bold", "tamanho": tam, "cor": texto, "maiusculas": True, "alinhamento": "centro", "ancora": "topo", "largura": 900, "fundo": True, "fundo_cor": fundo,
                                                          "fundo_opac": 100, "fundo_raio": 6, "fundo_pad": round(tam * .3), "entrada": "zoom", "saida": "fade", "tempo_anim": .22}
    cena = final["cenas"][0]["id"]
    abertura = pj._item_texto("texto", 0, min(2.8, total), receita["gancho"], 540, 610, tarja(62), "Abertura", papel="gancho", cena=cena)
    abertura["t"]["rot"] = -2.5
    textos["itens"].append(abertura)
    tem_final = bool(receita["marca"] or receita["chamada"]) and total >= 9
    fim_partes = total - 2.4 if tem_final else total
    y = round(((raiox or {}).get("faixa") or {}).get("y", .13) * 1920)
    y = max(190, min(y, 420))
    partes = receita["partes"]
    if partes and fim_partes > 3.2:
        passo = (fim_partes - 2.8) / len(partes)
        for k, texto in enumerate(partes):
            textos["itens"].append(pj._item_texto("texto", round(2.8 + k * passo, 3), round(passo, 3), texto, 540, y, tarja(40), f"Tarja {k + 1}"))
    if receita["marca"]:
        textos["itens"].append(pj._item_texto("texto", 0, round(fim_partes, 3), receita["marca"], 850, y + 110, {"fonte": "Poppins-Bold", "tamanho": 26, "cor": "#FFFFFF", "opacidade": 85, "contorno": 3, "largura": 400, "alinhamento": "centro"}, "Marca"))
    if not tem_final:
        efx["itens"].append(pj._efeito(max(0.0, total - .25), min(.25, total), "escurecer", "Escurecer no final"))
        return
    inicio = round(total - 2.4, 3)
    efx["itens"].append(pj._efeito(inicio, 2.4, "cortina", "Fundo da chamada final", .78))
    for item in list(leg["itens"]):
        if item["ini"] >= inicio:
            leg["itens"].remove(item)
        elif item["ini"] + item["dur"] > inicio:
            item["dur"] = round(inicio - item["ini"], 3)
            item["palavras"] = [p for p in item.get("palavras") or [] if p["ini"] < item["dur"]] or item.get("palavras")
    if receita["chamada"]:
        textos["itens"].append(pj._item_texto("texto", inicio + .1, 2.3, receita["chamada"], 540, 770, tarja(52, cor), "Chamada final"))
    if receita["marca"]:
        textos["itens"].append(pj._item_texto("texto", inicio + .25, 2.15, receita["marca"], 540, 1090, {"fonte": "Poppins-Bold", "tamanho": 44, "cor": "#FFFFFF", "alinhamento": "centro", "largura": 900, "entrada": "fade", "tempo_anim": .2}, "Marca no final"))
    if biblioteca.existe("boom_grave"):
        audio["itens"].append(pj._som(final["midias"], "boom_grave", biblioteca.nome("boom_grave"), max(0.0, inicio - .05), .5, biblioteca, cena))


class Montagens:
    def __init__(self, motor):
        self.motor = motor
        self.inicio = time.time()
        self.fila: queue.Queue = queue.Queue()
        self.trava = threading.RLock()
        threading.Thread(target=self._trabalhar, daemon=True).start()

    def candidatos(self, pasta: str, novos: bool = False) -> list[dict]:
        with self.motor.trava:
            lista = list(self.motor.cortes.values())
        return [m for m in lista if m.get("pasta") == pasta and m.get("status") == "pronto" and not m.get("montagem") and float(m.get("duracao_fonte") or m.get("duracao") or 0) >= 8
                and (self.motor.saida / m["id"] / "fonte.mp4").exists() and (not novos or (not m.get("montado") and m["criado"] >= self.inicio))]

    def pedir(self, pasta: str, cenas: int, emendado: bool = False) -> dict:
        if int(cenas) not in CENAS_MONTAGEM:
            raise ValueError("Escolha de 3 a 6 cenas para a montagem.")
        todos = self.candidatos(pasta)
        livres = [m for m in todos if not m.get("montado")]
        base = livres if len(livres) >= int(cenas) else todos
        if len(base) < int(cenas):
            raise ValueError(f"Esta pasta precisa de pelo menos {cenas} cortes prontos.")
        if emendado:  # os melhores momentos, na ordem em que aconteceram, só com o trecho da ação
            fila = sorted(escolher(base, int(cenas)), key=lambda m: float(m.get("pos_live") if m.get("pos_live") is not None else m["criado"]))
            return self._criar(pasta, fila, emendado=True)
        return self._criar(pasta, ordenar(escolher(base, int(cenas))))

    def pedir_estilo(self, dados: dict) -> dict:
        """Monta um vídeo novo com o estilo salvo, o texto e a marca da pessoa."""
        limpar = lambda v, n: " ".join(str(v or "").split())[:n]
        modelo, pasta = str(dados.get("modelo") or ""), str(dados.get("pasta") or "")
        perfil = self.motor.aprendizado.perfil(modelo, sem_filtro=True)
        if not perfil:
            raise ValueError("Este estilo não existe mais. Escolha outro.")
        gancho = limpar(dados.get("gancho"), 90)
        if not gancho:
            raise ValueError("Escreva a frase de abertura do vídeo.")
        todos = self.candidatos(pasta)
        if len(todos) < 2:
            raise ValueError("Esta pasta precisa de pelo menos 2 cortes prontos.")
        total = min(LIMITE, max(15.0, float(perfil.get("duracao") or 30)))
        n = int(min(8, len(todos), max(2, round(total / min(12.0, max(3.0, float(perfil.get("cena_s") or 5)))))))
        receita = {"gancho": gancho, "partes": [limpar(l, 48) for l in str(dados.get("partes") or "").splitlines() if l.strip()][:8],
                   "marca": limpar(dados.get("marca"), 40), "chamada": limpar(dados.get("chamada"), 70), "total": total}
        self.motor.aprendizado.guardar_marca(receita["marca"], receita["chamada"])
        return self._criar(pasta, ordenar(escolher(todos, n)), receita, modelo)

    def corte_pronto(self, meta: dict) -> None:
        """Quando juntar momentos novos suficientes, cria a montagem sozinho."""
        if meta.get("montagem"):
            return
        with self.trava:
            cenas = int(self.motor.config.get("montagem_cenas", 3))
            if self.motor.config.get("shorts_emendados", False) and meta.get("curto"):
                curtos = sorted((m for m in self.candidatos(meta.get("pasta"), novos=True) if m.get("curto") and m.get("nucleo")),
                                key=lambda m: float(m.get("pos_live") if m.get("pos_live") is not None else m["criado"]))
                if len(curtos) >= cenas:
                    self._criar(meta.get("pasta"), curtos[:cenas], emendado=True)  # na ordem em que aconteceram
                    return
            if not self.motor.config.get("montagem_auto", True):
                return
            novos = self.candidatos(meta.get("pasta"), novos=True)
            if len(novos) >= cenas:
                self._criar(meta.get("pasta"), ordenar(escolher(novos, cenas)))

    def _criar(self, pasta: str, origens: list[dict], receita: dict | None = None, modelo: str | None = None, emendado: bool = False) -> dict:
        p = origens[0]
        ident = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_montagem_{int(time.time() * 1000) % 100000}"
        n = len(origens)
        gancho = receita["gancho"] if receita else TITULOS[int(time.time()) % len(TITULOS)].format(n=n)
        meta = {"id": ident, "montagem": True, "origens": [m["id"] for m in origens], "pasta": pasta, "canal_id": p.get("canal_id"), "canal": p.get("canal"), "plataforma": p.get("plataforma"),
                "nome_plataforma": p.get("nome_plataforma"), "ident": p.get("ident"), "credito": p.get("credito"), "link": p.get("link") or "", "titulo_live": p.get("titulo_live") or "",
                "criado": time.time(), "status": "fila", "erro": None, "postado": False, "motivo": f"Montagem com {n} momentos", "reacao": "montagem", "reacao_rotulo": "Montagem", "msgs": 0,
                "forca": max(float(m.get("forca") or 0) for m in origens), "chat_marcante": [], "duracao": 0, "gancho": gancho, "post": "", "layout": p.get("layout"), "grupos": [],
                "ajuste_camera": {"modo": "auto", "rect": None}, "projeto_exportado": True, "nao_encurtar": True, "focos": []}
        if receita:
            meta.update(receita=receita, modelo=modelo, motivo="Vídeo novo no estilo salvo", reacao_rotulo="Estilo salvo")
        if emendado:
            forte = max(origens, key=lambda m: float(m.get("forca") or 0))
            meta.update(emendado=True, gancho=forte.get("gancho") or gancho, motivo=f"Short com {n} cenas emendadas", reacao="emendado", reacao_rotulo="Cenas emendadas")
        (self.motor.saida / ident).mkdir(parents=True, exist_ok=True)
        with self.motor.trava:
            self.motor.cortes[ident] = meta
            for m in origens if not receita else ():
                m["montado"] = ident
                self.motor._salvar_corte(m)
        self.motor._salvar_corte(meta)
        self.fila.put(ident)
        return {"id": ident}

    def _trabalhar(self) -> None:
        while not self.motor.fim.is_set():
            try:
                ident = self.fila.get(timeout=1)
            except queue.Empty:
                continue
            meta = self.motor.cortes.get(ident)
            if not meta:
                continue
            limite = time.time() + 600
            while self.motor.fila.qsize() and time.time() < limite and not self.motor.fim.is_set():
                time.sleep(1)  # os cortes da live têm prioridade
            try:
                self.motor._etapa(meta, "editando")
                self._produzir(meta)
                self.motor._etapa(meta, "pronto")
                self.motor.evento(meta["canal"], "pronto", f"Montagem pronta: {meta['gancho']}")
            except Exception as e:
                for oid in meta["origens"]:
                    origem = self.motor.cortes.get(oid)
                    if origem and origem.get("montado") == ident:
                        origem.pop("montado", None); self.motor._salvar_corte(origem)
                self.motor._etapa(meta, "erro", str(e)[:300])
                self.motor.evento(meta["canal"], "erro", "Uma montagem não pôde ser criada")

    def construir(self, meta: dict) -> dict:
        """Monta um projeto comum do editor, então tudo continua ajustável depois."""
        motor, pasta = self.motor, self.motor.saida / meta["id"]
        origens = [motor.cortes[i] for i in meta["origens"] if i in motor.cortes]
        if len(origens) < 2:
            raise ValueError("Os cortes usados nesta montagem foram apagados.")
        meta["modelo"] = meta.get("modelo") or motor.aprendizado.escolher_modelo(meta)
        perfil = motor.aprendizado.perfil(meta["modelo"]) if meta["modelo"] else None
        receita = meta.get("receita")
        alvo = float(min(12.0, max(3.0, receita["total"] / len(origens)))) if receita else float(min(12.0, max(5.5, min((perfil or {}).get("cena_s") or 10.0, LIMITE / len(origens)))))
        visual = {"legenda": "palavra", **motor.aprendizado.estilo_do_modelo(meta["modelo"])} if receita else {}
        trocas = sequencia_trocas(perfil)
        volume_som = .55 if perfil and (perfil.get("sfx_cortes") or 1) < .2 else 1.0
        est = estilos.normalizar(origens[0].get("estilo"), motor.config["estilo"])
        final = pj._vazio("corte", meta["id"], meta["gancho"], 1080, 1920, est)
        base, foco_f, topo = pj._faixa("video", "Cenas"), pj._faixa("video", "Foco"), pj._faixa("video", "Câmera")
        efx, textos, leg, audio = pj._faixa("efeito", "Efeitos"), pj._faixa("texto", "Textos"), pj._faixa("legenda", "Legendas"), pj._faixa("audio", "Efeitos sonoros")
        destino = {"efeito": efx, "texto": textos, "legenda": leg, "audio": audio}
        pos, titulo = 0.0, None
        for k, origem in enumerate(origens):
            cena_meta = {**origem, "estilo": {**(origem.get("estilo") or {}), **visual}, "edicao": {**(origem.get("edicao") or {}), "cortes": None}}
            p = pj.importar_corte(cena_meta, motor)
            if not k:
                final["global"] = copy.deepcopy(p["global"])
            titulo = titulo or next((copy.deepcopy(i) for f in p["faixas"] for i in f["itens"] if i.get("papel") == "gancho"), None)
            total = comp.duracao_projeto(p)
            # Cada cena conta a sua história: a preparação, o acontecimento e o desfecho, sem frase pela metade.
            momento_cena = float(origem["momento_fonte"]) if origem.get("momento_fonte") is not None else total * .62
            teto_cena = max(10.0, min(22.0, (LIMITE - pos) / max(1, len(origens) - k)))
            ini, fim = ctx.trecho_de_cena(origem.get("grupos") or [], momento_cena, total, min(9.0, teto_cena - 1), teto_cena) if origem.get("grupos") else janela(origem, alvo)
            fim = min(fim, total, ini + max(2.5, LIMITE - pos))
            pj.remover_intervalos(p, [(fim, max(total, fim) + 1), (0, ini)] if ini > 0 else [(fim, max(total, fim) + 1)])
            dur = round(fim - ini, 3)
            arquivo = f"cena_{k}.mp4"
            _ligar(motor.saida / origem["id"] / "fonte.mp4", pasta / arquivo)
            nomes = {}
            for mid, m in p["midias"].items():
                novo = mid if mid.startswith("som:") else f"cena{k}_{mid}"
                nomes[mid] = novo
                final["midias"][novo] = {**m, "id": novo, "rel": f"{meta['id']}/{arquivo}"} if not mid.startswith("som:") else m
            cena = pj.novo_id("c")
            final["cenas"].append({"id": cena, "nome": f"Cena {k + 1}"})
            videos = [f for f in p["faixas"] if f["tipo"] == "video" and f["nome"] != "Foco"]
            for f in p["faixas"]:
                alvo_f = foco_f if f["nome"] == "Foco" else (topo if f is videos[-1] and len(videos) > 1 else base) if f["tipo"] == "video" else destino[f["tipo"]]
                for item in f["itens"]:
                    if item.get("efeito") in ("progresso", "escurecer"):
                        continue
                    if item.get("papel") == "gancho":
                        continue
                    if item["ini"] >= dur - .05:
                        continue
                    item["dur"] = round(min(item["dur"], dur - item["ini"]), 3)
                    item["ini"] = round(item["ini"] + pos, 3)
                    item["cena"] = cena
                    if item.get("midia") in nomes:
                        item["midia"] = nomes[item["midia"]]
                    alvo_f["itens"].append(item)
            if k:
                nome, som, volume = trocas[(k - 1) % len(trocas)]
                for f in (base, topo):
                    for item in f["itens"]:
                        if abs(item["ini"] - pos) < .02:
                            item["transicao"] = {"tipo": nome, "dur": .36}
                            if meta.get("emendado") and f is base and not (item.get("kf") or {}).get("zoom"):
                                item.setdefault("kf", {})["zoom"] = [{"t": 0.0, "v": 1.18, "e": "suave"}, {"t": .5, "v": 1.0, "e": "linear"}]  # zoom de impacto na troca
                if motor.biblioteca.existe(som):
                    audio["itens"].append(pj._som(final["midias"], som, motor.biblioteca.nome(som), max(0.0, pos - .1), volume * volume_som, motor.biblioteca, cena))
            pos = round(pos + dur, 3)
            if pos >= LIMITE - 2:
                break
        if receita:
            aplicar_receita(final, receita, motor.aprendizado.raiox_do_modelo(meta["modelo"]), visual, pos, textos, efx, leg, audio, motor.biblioteca)
        elif titulo:
            textos["itens"].append({**titulo, "ini": 0.0, "dur": min(2.6, pos), "texto": meta["gancho"], "cena": final["cenas"][0]["id"]})
        if est.get("barra_progresso"):
            efx["itens"].append(pj._efeito(0, pos, "progresso", "Barra de progresso", cor="#" + estilos.CORES[est["cor"]]))
        if not receita:
            efx["itens"].append(pj._efeito(max(0.0, pos - .25), min(.25, pos), "escurecer", "Escurecer no final"))
        final["faixas"] = [f for f in (base, foco_f, topo, efx, textos, leg, audio) if f["itens"]]
        return pj.validar(final)

    def _produzir(self, meta: dict) -> None:
        motor, pasta = self.motor, self.motor.saida / meta["id"]
        proj = self.construir(meta)
        (pasta / "projeto_ia.json").write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
        pj.salvar(pasta, proj)
        temp = pasta / "exportando.mp4"
        comp.exportar(proj, motor.estudio.midias, temp, 1080, lambda *_: None, lambda: motor.fim.is_set())
        temp.replace(pasta / "corte.mp4")
        total = comp.duracao_projeto(proj)
        grupos = [{"ini": i["ini"], "fim": i["ini"] + i["dur"], "palavras": [{"p": p["p"], "ini": i["ini"] + p["ini"], "fim": i["ini"] + p["fim"]} for p in i.get("palavras") or [{"p": i["texto"], "ini": 0, "fim": i["dur"]}]]}
                  for f in proj["faixas"] if f["tipo"] == "legenda" for i in sorted(f["itens"], key=lambda x: x["ini"])]
        (pasta / "legenda.srt").write_text(edicao.gerar_srt(grupos), encoding="utf-8")
        edicao.executar(["ffmpeg", "-v", "error", "-y", "-ss", f"{min(1.2, total / 2):.2f}", "-i", str(pasta / "corte.mp4"), "-frames:v", "1", "-q:v", "2", str(pasta / "capa.jpg")])
        meta["post"] = ctx.criar_post(meta["gancho"], meta["canal"], meta["credito"], meta["titulo_live"], meta["plataforma"], meta["ident"])
        (pasta / "post.txt").write_text(meta["post"], encoding="utf-8")
        meta.update(duracao=round(total, 2), grupos=grupos, versao=1, cenas=len(proj["cenas"]))
