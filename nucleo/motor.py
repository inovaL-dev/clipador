"""Coordena canais, gravações, detecção e a fila de edição."""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import tempfile
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from . import camera as cam
from . import contexto as ctx
from . import edicao
from . import estilos as est
from . import timeline as tl
from .aprendizado import Aprendizado
from .biblioteca import Biblioteca, sugerir_sons
from .estudio import Estudio, edicao_inicial
from .chat import Chat
from .deteccao import REACOES, SeletorMomento, classificar_reacao, mensagens_marcantes
from .atualizacao import Atualizacao
from .foco import achar_focos
from .montagem import CENAS_MONTAGEM, Montagens
from .gravadas import Gravadas
from .gravador import Gravador
from .longo import Longos
from .publicacao import Postagem
from .momentos import INTERVALO_MINIMO, LIMITES, PontuadorMomento
from .sentidos import Sentidos
from .plataformas import Canal, Live, criar_canal

JANELA_CHAT = 10
HISTORICO_CORTE = 90
APOS_REACAO = 30  # espera a pessoa terminar o assunto depois da reação
ESPERA_VERIFICAR = 15
FALHAS_PARA_ENCERRAR = 20
TEMPO_RECONEXAO = 600
PAUSA_PASTA = 4 * 3600  # depois disso, uma nova transmissão vira outra pasta
LIMITE_SEM_GRAVAR = 45
INTERVALOS_GARANTIDOS = (0, 3, 5, 10)  # 0 = cortar só por reação
ETAPAS = {
    "capturando": "Guardando o trecho da live",
    "fila": "Na fila de edição",
    "transcrevendo": "Transcrevendo a fala",
    "enquadrando": "Enquadrando a câmera",
    "editando": "Montando o vídeo",
    "pronto": "Pronto para postar",
    "erro": "Não foi possível editar",
}
_TRAVA_ARQUIVOS = threading.Lock()
CONFIG_PADRAO = {
    "sensibilidade": "media", "duracao_min": 25, "duracao_max": 60, "modelo": "small", "idioma": "pt",
    "corte_garantido": 3, "estilo": est.PADRAO, "montagem_auto": True, "montagem_cenas": 4, "foco_auto": True, "shorts_emendados": True,
}
ROTULOS_EXTRAS = {
    "manual": "Manual", "destaque": "Melhor momento", "streamer": "Reação do streamer",
    "admirado": "Streamer admirado", "jogo": "Ação no jogo",
}


class CanalVivo:
    def __init__(self, canal: Canal, camera: dict | None = None):
        self.canal = canal
        self.camera = camera or {"modo": "auto", "rect": None}
        self.programar = False
        self.parar = threading.Event()
        self.pedido = threading.Event()
        self.status = "verificando"
        self.mensagem = "Procurando a live"
        self.titulo = ""
        self.desde: float | None = None
        self.grav: Gravador | None = None
        self.chat: Chat | None = None
        self.pont: PontuadorMomento | None = None
        self.nota: dict = {"nota": 0, "chat": 0, "streamer": 0, "jogo": 0, "causa": "chat"}
        self.seletor: SeletorMomento | None = None
        self.sinal = "chat"
        self.msgs = 0
        self.serie: deque[dict] = deque(maxlen=90)
        self.capturas: list[threading.Thread] = []
        self.thread: threading.Thread | None = None


class Motor:
    def __init__(self, dados: Path, saida: Path, modelo: str | None = None):
        self.dados = Path(dados)
        self.saida = Path(saida)
        self.modelo_forcado = modelo
        self.dados.mkdir(parents=True, exist_ok=True)
        self.saida.mkdir(parents=True, exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="clipador_trabalho_"))
        self.trava = threading.RLock()
        self.canais: dict[str, CanalVivo] = {}
        self.cortes: dict[str, dict] = {}
        self.eventos: deque[dict] = deque(maxlen=80)
        self.fila: queue.Queue = queue.Queue()
        self.fim = threading.Event()
        self.config = {**CONFIG_PADRAO, **self._ler(self.dados / "config.json", {})}
        self.config["estilo"] = est.normalizar(self.config.get("estilo"))
        if self.config["corte_garantido"] not in INTERVALOS_GARANTIDOS:
            self.config["corte_garantido"] = CONFIG_PADRAO["corte_garantido"]
        self.legenda = {"estado": "carregando", "nome": None}
        self._modelo = None
        self.trava_escuta = threading.Lock()
        self._ultimas_pastas: dict[str, tuple[str, float]] = {}
        self._carregar_cortes()
        self._organizar_pastas()
        self.espera_postagem = float(os.environ.get("CLIPADOR_ESPERA_POSTAGEM", "5"))
        self.postagem = Postagem(self)
        self.biblioteca = Biblioteca(self.dados)
        self.estudio = Estudio(self)
        self.aprendizado = Aprendizado(self)
        self.longos = Longos(self)
        self.gravadas = Gravadas(self)
        self.montagens = Montagens(self)
        self.atualizacao = Atualizacao()
        threading.Thread(target=self._editor, daemon=True).start()
        try:
            self.retomar()
        except Exception:
            import traceback
            traceback.print_exc()
        for item in self._ler(self.dados / "canais.json", []):
            try:
                self.adicionar(item["link"], item.get("camera"), salvar=False, programar=bool(item.get("programar")))
            except (ValueError, KeyError):
                pass

    # ------------------------------------------------------------ persistência

    @staticmethod
    def _ler(arquivo: Path, padrao):
        try:
            return json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return padrao

    @staticmethod
    def _gravar(arquivo: Path, dados) -> None:
        with _TRAVA_ARQUIVOS:
            tmp = arquivo.with_suffix(".tmp")
            from .painel_json import para_json
            tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1, default=para_json), encoding="utf-8")
            tmp.replace(arquivo)

    def _salvar_canais(self) -> None:
        with self.trava:
            itens = [{"link": c.canal.link, "camera": c.camera, "programar": c.programar} for c in self.canais.values()]
        self._gravar(self.dados / "canais.json", itens)

    def _carregar_cortes(self) -> None:
        """Lê os cortes salvos. O que estava no meio do caminho volta para a fila e continua de onde parou."""
        self._retomar: list[tuple[str, str]] = []
        for arq in self.saida.glob("*/corte.json"):
            meta = self._ler(arq, None)
            if not meta or "id" not in meta:
                continue
            if meta.get("status") not in ("pronto", "erro"):
                pasta = arq.parent
                bruto = pasta / "bruto.ts"
                if meta.get("montagem"):
                    self._retomar.append(("montagem", meta["id"]))
                elif bruto.exists() and bruto.stat().st_size > 200_000 and (cam.dimensoes(bruto)[2] if bruto.exists() else 0) >= 5:
                    self._retomar.append(("novo", meta["id"]))
                elif (pasta / "fonte.mp4").exists():
                    self._retomar.append(("refazer", meta["id"]))
                else:
                    pronto = (pasta / "corte.mp4").exists()
                    meta["status"], meta["erro"] = ("pronto", None) if pronto else ("erro", "O programa foi fechado antes de gravar este momento.")
                if meta["status"] not in ("pronto", "erro"):
                    meta.update(status="fila", erro=None, retomado=True)
            self.cortes[meta["id"]] = meta

    def retomar(self) -> None:
        """Depois de tudo pronto para trabalhar, devolve à fila o que foi interrompido."""
        for tipo, ident in self._retomar:
            if ident not in self.cortes:
                continue
            if tipo == "montagem":
                self.montagens.fila.put(ident)
            else:
                self.fila.put((tipo, ident))
        if self._retomar:
            self.evento("Clipador", "info", f"Continuando {len(self._retomar)} {'corte' if len(self._retomar) == 1 else 'cortes'} de onde parou")
        self.longos.retomar()
        self.gravadas.retomar()

    def _pasta_para(self, meta: dict) -> str:
        """Cada live ou gravação tem a própria pasta; quedas curtas continuam na mesma."""
        if meta.get("gravada_id"):
            return f"gravada-{meta['gravada_id']}"
        canal = meta.get("canal_id") or meta.get("canal") or "live"
        ultima = self._ultimas_pastas.get(canal)
        pasta = ultima[0] if ultima and meta["criado"] - ultima[1] <= PAUSA_PASTA else f"live-{canal}-{int(meta['criado'])}"
        self._ultimas_pastas[canal] = (pasta, meta["criado"])
        return pasta

    def _organizar_pastas(self) -> None:
        for meta in sorted(self.cortes.values(), key=lambda m: m["criado"]):
            if meta.get("pasta"):
                if not meta.get("gravada_id"):
                    self._ultimas_pastas[meta.get("canal_id") or meta.get("canal") or "live"] = (meta["pasta"], meta["criado"])
                continue
            meta["pasta"] = self._pasta_para(meta)
            try:
                self._salvar_corte(meta)
            except OSError:
                pass

    def pastas(self) -> list[dict]:
        grupos: dict[str, dict] = {}
        with self.trava:
            cortes = sorted(self.cortes.values(), key=lambda m: m["criado"])
        for m in cortes:
            g = grupos.setdefault(m.get("pasta") or "sem-pasta", {
                "id": m.get("pasta") or "sem-pasta", "canal": m.get("canal") or "Live", "titulo": m.get("titulo_live") or "",
                "gravada": bool(m.get("gravada_id")), "desde": m["criado"], "ate": m["criado"], "cortes": 0,
            })
            g["cortes"] += 1
            g["ate"] = m["criado"]
        return sorted(grupos.values(), key=lambda g: g["ate"], reverse=True)

    def _salvar_corte(self, meta: dict) -> None:
        self._gravar(self.saida / meta["id"] / "corte.json", meta)

    def _etapa(self, meta: dict, status: str, erro: str | None = None) -> None:
        with self.trava:
            meta["status"] = status
            meta["erro"] = erro
        self._salvar_corte(meta)

    def evento(self, canal: str, tipo: str, texto: str) -> None:
        with self.trava:
            self.eventos.append({"t": time.time(), "canal": canal, "tipo": tipo, "texto": texto})

    # ------------------------------------------------------------ comandos do painel

    def adicionar(self, link: str, camera: dict | None = None, salvar: bool = True, programar: bool = False) -> str:
        canal = criar_canal(link)
        with self.trava:
            atual = self.canais.get(canal.id)
            if atual and atual.status != "encerrado":
                raise ValueError("Esta live já está sendo acompanhada.")
            cv = CanalVivo(canal, camera or (atual.camera if atual else None))
            cv.programar = programar
            self.canais[canal.id] = cv
        cv.thread = threading.Thread(target=self._acompanhar, args=(cv,), daemon=True)
        cv.thread.start()
        if salvar:
            self._salvar_canais()
        self.evento(canal.nome, "canal", f"Acompanhando {canal.nome} no {canal.nome_plataforma}")
        return canal.id

    def remover(self, canal_id: str) -> None:
        with self.trava:
            cv = self.canais.pop(canal_id, None)
        if not cv:
            raise KeyError(canal_id)
        cv.parar.set()
        self._salvar_canais()
        self.evento(cv.canal.nome, "canal", f"Parou de acompanhar {cv.canal.nome}")

    def cortar_agora(self, canal_id: str) -> None:
        cv = self.canais[canal_id]
        if cv.status != "gravando":
            raise ValueError("Só é possível cortar enquanto a live está sendo gravada.")
        cv.pedido.set()

    def definir_camera(self, canal_id: str, ajuste: dict) -> None:
        cv = self.canais[canal_id]
        cv.camera = _validar_camera(ajuste)
        self._salvar_canais()

    def quadro_canal(self, canal_id: str) -> Path | None:
        cv = self.canais[canal_id]
        if not cv.grav:
            return None
        destino = self.tmp / f"quadro_{canal_id}.jpg"
        return destino if cv.grav.quadro(destino) else None

    def salvar_config(self, novos: dict) -> dict:
        cfg = dict(self.config)
        if novos.get("sensibilidade") in LIMITES:
            cfg["sensibilidade"] = novos["sensibilidade"]
        if novos.get("modelo") in ("base", "small", "medium"):
            cfg["modelo"] = novos["modelo"]
        if isinstance(novos.get("idioma"), str) and re.fullmatch(r"[a-z]{2}", novos["idioma"]):
            cfg["idioma"] = novos["idioma"]
        if "corte_garantido" in novos:
            if int(novos["corte_garantido"]) not in INTERVALOS_GARANTIDOS:
                raise ValueError("Escolha um intervalo válido para os cortes automáticos.")
            cfg["corte_garantido"] = int(novos["corte_garantido"])
        if isinstance(novos.get("estilo"), dict):
            cfg["estilo"] = est.validar(novos["estilo"])
        for chave in ("montagem_auto", "foco_auto", "shorts_emendados"):
            if chave in novos:
                cfg[chave] = bool(novos[chave])
        if "montagem_cenas" in novos:
            if int(novos["montagem_cenas"]) not in CENAS_MONTAGEM:
                raise ValueError("Escolha de 3 a 6 cenas para a montagem.")
            cfg["montagem_cenas"] = int(novos["montagem_cenas"])
        minimo = float(novos.get("duracao_min", cfg["duracao_min"]))
        maximo = float(novos.get("duracao_max", cfg["duracao_max"]))
        if not 10 <= minimo <= maximo <= 180:
            raise ValueError("Use uma duração entre 10 e 180 segundos, com o mínimo menor que o máximo.")
        cfg["duracao_min"], cfg["duracao_max"] = minimo, maximo
        self.config = cfg
        self._gravar(self.dados / "config.json", cfg)
        for cv in list(self.canais.values()):
            if cv.pont:
                cv.pont.limite = LIMITES[cfg["sensibilidade"]]
            if cv.seletor:
                cv.seletor.intervalo = cfg["corte_garantido"] * 60
        return cfg

    def detalhe_corte(self, corte_id: str) -> dict:
        return self.cortes[corte_id]

    def atualizar_corte(self, corte_id: str, dados: dict) -> dict:
        meta = self.cortes[corte_id]
        refazer = bool(dados.get("refazer"))
        if meta.get("projeto_exportado") and (refazer or any(k in dados for k in ("gancho", "grupos", "estilo", "camera"))):
            raise ValueError("Este vídeo foi personalizado no Editor. Abra o Editor para fazer novas mudanças.")
        with self.trava:
            if "postado" in dados:
                meta["postado"] = bool(dados["postado"])
            if isinstance(dados.get("post"), str):
                meta["post"] = dados["post"][:4000]
                (self.saida / corte_id / "post.txt").write_text(meta["post"], encoding="utf-8")
            if isinstance(dados.get("gancho"), str) and dados["gancho"].strip() != meta.get("gancho"):
                meta["gancho"] = dados["gancho"].strip()[:90]
                refazer = True
            if isinstance(dados.get("grupos"), list):
                novos = []
                for atual, item in zip(meta.get("grupos") or [], dados["grupos"]):
                    texto = str((item or {}).get("texto", "")).strip()
                    if texto:
                        novos.append(ctx.retextar(atual, texto))
                if novos != meta.get("grupos"):
                    meta["grupos"] = novos
                    refazer = True
            if "estilo" in dados:
                proprio = {k: v for k, v in (dados["estilo"] or {}).items() if v}
                est.validar(proprio)
                if proprio != (meta.get("estilo") or {}):
                    meta["estilo"] = proprio
                    refazer = True
            if isinstance(dados.get("camera"), dict):
                meta["ajuste_camera"] = _validar_camera(dados["camera"])
                meta["replanejar"] = True
                refazer = True
        if refazer:
            if meta["status"] not in ("pronto", "erro") or not (self.saida / corte_id / "fonte.mp4").exists():
                raise ValueError("Este corte não pode ser refeito agora.")
            self._etapa(meta, "fila")
            self.fila.put(("refazer", corte_id))
        else:
            self._salvar_corte(meta)
        return meta

    def excluir_corte(self, corte_id: str) -> None:
        with self.trava:
            meta = self.cortes[corte_id]
            if meta["status"] not in ("pronto", "erro"):
                raise ValueError("Aguarde o corte terminar de ser editado.")
            del self.cortes[corte_id]
        shutil.rmtree(self.saida / corte_id, ignore_errors=True)

    def estado(self) -> dict:
        with self.trava:
            canais = [self._resumo_canal(c) for c in self.canais.values()]
            cortes = sorted(self.cortes.values(), key=lambda m: m["criado"], reverse=True)
            resumo = [
                {k: v for k, v in m.items() if k not in ("grupos", "palavras")} | {"etapa": ETAPAS.get(m["status"], "")}
                for m in cortes
            ]
            base = {
                "agora": time.time(), "canais": canais, "cortes": resumo,
                "eventos": list(self.eventos)[-40:][::-1], "config": self.config,
                "sistema": {"legenda": self.legenda, "fila": self.fila.qsize()},
            }
        # Fora da trava do motor: a postagem usa as duas travas sempre na mesma ordem.
        # Cada parte é montada à parte: um problema em uma delas não apaga a tela inteira.
        partes = {
            "postagem": (self.postagem.resumo, {"itens": [], "conta": {}, "dias": []}), "longos": (self.longos.resumo, []), "longos_auto": (self.longos.resumo_auto, {"ativo": False, "minutos": 10, "lives": []}),
            "sessoes": (lambda: [{k: v for k, v in s.items() if k != "ids"} for s in self.longos.sessoes()], []),
            "gravadas": (self.gravadas.resumo, []), "atualizacao": (self.atualizacao.resumo, {}),
        }
        saida = dict(base)
        for nome, (fazer, vazio) in partes.items():
            try:
                saida[nome] = fazer()
            except Exception:
                import traceback
                print(f"[estado:{nome}] " + traceback.format_exc(), flush=True)
                saida[nome] = vazio
        return saida

    def _resumo_canal(self, c: CanalVivo) -> dict:
        pont = c.pont
        pos = time.time() - c.grav.t0 if c.grav and c.grav.t0 and c.status == "gravando" else None
        restante = c.seletor.restante(pos) if c.seletor and pos is not None else None
        return {
            "id": c.canal.id, "nome": c.canal.nome, "plataforma": c.canal.plataforma,
            "nome_plataforma": c.canal.nome_plataforma, "link": c.canal.link, "status": c.status,
            "mensagem": c.mensagem, "titulo": c.titulo, "desde": c.desde,
            "gravado": c.grav.gravado() if c.grav and c.status == "gravando" else 0,
            "chat_conectado": bool(c.chat and c.chat.conectado), "sinal": c.sinal, "msgs": c.msgs,
            "nota": c.nota, "limite": pont.limite if pont else 0,
            "aquecendo": bool(pont and not pont.aquecido), "serie": list(c.serie), "proximo_auto": restante,
            "ultimas": c.chat.ultimas(8) if c.chat else [], "camera": c.camera,
            "cortes": sum(1 for m in self.cortes.values() if m["canal_id"] == c.canal.id),
        }

    def encerrar(self) -> None:
        self.fim.set()
        for cv in list(self.canais.values()):
            cv.parar.set()
        for cv in list(self.canais.values()):
            if cv.thread:
                cv.thread.join(15)
        self.fila.put(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------ acompanhamento

    def _acompanhar(self, cv: CanalVivo) -> None:
        visto = False
        falhas = 0
        while not cv.parar.is_set():
            try:
                live = cv.canal.verificar()
            except ValueError as e:
                texto = str(e)
                cv.status, cv.mensagem = "erro", texto[:1].upper() + texto[1:]
                cv.parar.wait(ESPERA_VERIFICAR)
                continue
            except Exception as e:
                cv.status = "erro"
                cv.mensagem = f"Não foi possível verificar a live. Nova tentativa em instantes. ({type(e).__name__})"
                cv.parar.wait(ESPERA_VERIFICAR)
                continue
            if live:
                visto, falhas = True, 0
                self._sessao(cv, live)
                cv.parar.wait(5)
                continue
            # Uma resposta vazia pode ser só instabilidade: a live só acaba depois de várias seguidas.
            falhas += 1
            if cv.canal.encerra_ao_acabar and visto and falhas >= FALHAS_PARA_ENCERRAR:
                cv.status, cv.mensagem = "encerrado", "A transmissão terminou"
                self.evento(cv.canal.nome, "live", f"A transmissão de {cv.canal.nome} terminou")
                return
            cv.status = "aguardando"
            cv.mensagem = cv.canal.motivo or ("Procurando a transmissão de novo" if visto else "Começa a gravar assim que a live abrir")
            cv.parar.wait(ESPERA_VERIFICAR)

    def _reconectar(self, cv: CanalVivo, grav: Gravador) -> bool:
        """Retoma a gravação sem perder o histórico da live."""
        cv.status, cv.mensagem = "reconectando", "A transmissão oscilou. Reconectando"
        self.evento(cv.canal.nome, "live", "A transmissão oscilou. Reconectando")
        limite = time.time() + TEMPO_RECONEXAO
        while time.time() < limite and not cv.parar.is_set():
            try:
                live = cv.canal.verificar()
            except Exception:
                live = None
            if live:
                grav.reiniciar(live.fonte)
                if grav.aguardar_inicio(cv.parar, 60):
                    cv.status, cv.mensagem = "gravando", "Gravando e lendo o chat"
                    self.evento(cv.canal.nome, "live", "Gravação retomada")
                    return True
            cv.parar.wait(5)
        return False

    def _sessao(self, cv: CanalVivo, live: Live) -> None:
        pasta = Path(tempfile.mkdtemp(prefix="sessao_", dir=self.tmp))
        grav = Gravador(live.fonte, pasta)
        chat = Chat(live.chat)
        pont = PontuadorMomento(self.config["sensibilidade"])
        sentidos = Sentidos(self._ouvir, lambda: cv.camera)
        seletor = SeletorMomento(self.config["corte_garantido"] * 60)
        cv.grav, cv.chat, cv.pont, cv.seletor = grav, chat, pont, seletor
        cv.titulo = live.titulo
        cv.serie.clear()
        cv.status, cv.mensagem = "conectando", "Conectando à transmissão"
        chat.iniciar()
        grav.iniciar()
        try:
            if not grav.aguardar_inicio(cv.parar):
                cv.status, cv.mensagem = "erro", "A transmissão não abriu. Nova tentativa em instantes."
                return
            cv.status, cv.mensagem = "gravando", "Gravando e lendo o chat"
            cv.desde = grav.t0
            self.evento(cv.canal.nome, "live", f"{cv.canal.nome} entrou ao vivo")
            chat.pegar()
            proximo = time.time() + JANELA_CHAT
            vistos = 0
            gravado, crescimento = grav.gravado(), time.time()
            while not cv.parar.is_set():
                atual = grav.gravado()
                if atual > gravado:
                    gravado, crescimento = atual, time.time()
                if not grav.vivo() or time.time() - crescimento > LIMITE_SEM_GRAVAR:
                    if not self._reconectar(cv, grav):
                        break
                    gravado, crescimento = grav.gravado(), time.time()
                    proximo = time.time() + JANELA_CHAT
                    chat.pegar()
                    continue
                if cv.pedido.wait(0.25):
                    cv.pedido.clear()
                    agora_manual = time.time() - grav.t0
                    self._novo_corte(cv, grav, live, agora_manual, "Corte manual", "manual", 0, [], 0.0)
                    seletor.marcar_corte(agora_manual)
                if time.time() < proximo:
                    continue
                proximo += JANELA_CHAT
                agora = time.time()
                pos = agora - grav.t0
                msgs = chat.pegar()
                cv.msgs = msgs
                segs = grav.segmentos()
                novos, vistos = segs[vistos:], len(segs)
                chat_ativo = chat.ativo()
                cv.sinal = "audio" if not chat_ativo and pos > 60 else "chat"
                textos = chat.textos_desde(agora - JANELA_CHAT)
                leitura = sentidos.ler([s[0] for s in novos if s[0].exists()]) if novos else {}
                nota = pont.avaliar(msgs, textos, leitura)
                peso = self.aprendizado.peso(_descrever(nota["causa"], msgs, textos)[0])  # o que dá resultado no canal entra mais fácil
                cv.nota = nota
                marcantes = mensagens_marcantes(textos)

                ponto = {"t": agora, "n": msgs, "nota": nota["nota"], "chat": nota["chat"],
                         "streamer": nota["streamer"], "jogo": nota["jogo"], "pico": False, "corte": None}
                cv.serie.append(ponto)
                if pont.aquecido:
                    seletor.registrar(pos, nota["nota"] * peso, {"ponto": ponto, "msgs": msgs, "marcantes": marcantes,
                                                          "forca": nota["nota"], "causa": nota["causa"],
                                                          "textos": textos})
                disparo = None
                livre = not seletor.ultimo_corte or pos - seletor.ultimo_corte >= INTERVALO_MINIMO
                if livre and pont.disparar(nota["nota"] * peso, pos):
                    tipo, motivo = _descrever(nota["causa"], msgs, textos)
                    disparo = (ponto, pos, motivo, tipo, msgs, marcantes, nota["nota"])
                elif melhor := seletor.vencido(pos):
                    minutos = round(seletor.intervalo / 60)
                    tipo = melhor["causa"] if melhor["causa"] != "chat" else "destaque"
                    disparo = (melhor["ponto"], melhor["pos"], f"Melhor momento dos últimos {minutos} minutos",
                               tipo, melhor["msgs"], melhor["marcantes"], melhor["forca"])
                if disparo:
                    alvo, posicao, motivo, tipo, qtd, frases_chat, forca = disparo
                    alvo["pico"] = True
                    alvo["corte"] = self._novo_corte(
                        cv, grav, live, posicao - JANELA_CHAT, motivo, tipo, qtd, frases_chat, forca,
                    )
                    seletor.marcar_corte(pos)
                grav.limpar_antigos()
        finally:
            sentidos.encerrar()
            chat.encerrar()
            grav.encerrar()
            for t in cv.capturas:
                t.join(70)
            cv.capturas.clear()
            cv.grav, cv.chat, cv.seletor = None, None, None
            shutil.rmtree(pasta, ignore_errors=True)
            if not cv.parar.is_set():
                cv.status, cv.mensagem = "verificando", "A transmissão parou. Procurando a live de novo"
                self.evento(cv.canal.nome, "live", f"A transmissão de {cv.canal.nome} parou")

    def _novo_corte(self, cv: CanalVivo, grav: Gravador, live: Live, momento: float, motivo: str, reacao: str,
                    msgs: int, marcantes: list[str], forca: float) -> str:
        carimbo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        corte_id = f"{carimbo}_{cv.canal.id}"
        with self.trava:
            n = 2
            while corte_id in self.cortes:
                corte_id, n = f"{carimbo}_{cv.canal.id}_{n}", n + 1
            rotulo = ROTULOS_EXTRAS.get(reacao) or REACOES[reacao][0]
            meta = {
                "id": corte_id, "canal_id": cv.canal.id, "canal": cv.canal.nome, "plataforma": cv.canal.plataforma,
                "nome_plataforma": cv.canal.nome_plataforma, "ident": cv.canal.ident, "credito": cv.canal.credito,
                "link": cv.canal.link,
                "titulo_live": live.titulo, "criado": time.time(), "status": "capturando", "erro": None,
                "postado": False, "motivo": motivo, "reacao": reacao, "reacao_rotulo": rotulo, "msgs": msgs,
                "forca": forca * self.aprendizado.peso(reacao), "chat_marcante": marcantes, "duracao": 0, "gancho": "", "post": "",
                "layout": None, "ajuste_camera": dict(cv.camera), "grupos": [], "pos_sessao": round(max(0.0, momento)),
            }
            meta["pasta"] = self._pasta_para(meta)
            (self.saida / corte_id).mkdir(parents=True, exist_ok=True)
            self.cortes[corte_id] = meta
        if cv.programar:
            self.postagem.ativar_pasta_nova(meta["pasta"])
        self._salvar_corte(meta)
        self.evento(cv.canal.nome, "corte", f"{motivo}. Cortando agora")
        apos = 0 if reacao == "manual" else APOS_REACAO
        t = threading.Thread(target=self._capturar, args=(cv, grav, meta, momento, apos), daemon=True)
        cv.capturas.append(t)
        t.start()
        return corte_id

    def _capturar(self, cv: CanalVivo, grav: Gravador, meta: dict, momento: float, apos: float) -> None:
        ini, fim = max(0.0, momento - HISTORICO_CORTE), momento + apos
        limite = time.time() + apos + 30
        while time.time() < limite and grav.vivo() and grav.gravado() < fim:
            time.sleep(0.25)
        base = grav.juntar(ini, fim, self.saida / meta["id"] / "bruto.ts")
        if base is None:
            self._etapa(meta, "erro", "O trecho da live não estava disponível.")
            return
        meta["momento_rel"] = max(0.0, momento - base)
        self._etapa(meta, "fila")
        self.fila.put(("novo", meta["id"]))

    def corte_gravado(self, item: dict, video: Path, duracao: float, nota: dict) -> str:
        """Cria um corte a partir de um momento encontrado em uma live que já terminou."""
        momento = max(0.0, nota["pos"] - JANELA_CHAT)
        ini, fim = max(0.0, momento - HISTORICO_CORTE), min(duracao, momento + APOS_REACAO)
        tipo, motivo = _descrever(nota["causa"], nota["msgs"], nota["textos"])
        carimbo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        corte_id = f"{carimbo}_gravada-{item['id']}_{int(momento)}"
        canal = item.get("canal") or "Live gravada"
        meta = {
            "id": corte_id, "canal_id": f"gravada-{item['id']}", "canal": canal, "plataforma": item.get("plataforma") or "video",
            "nome_plataforma": item.get("nome_plataforma") or "Vídeo", "ident": item.get("ident") or item["id"],
            "credito": item.get("credito") or canal, "link": item["link"] if str(item["link"]).startswith("http") else "",
            "titulo_live": item.get("titulo") or "", "criado": time.time(), "status": "capturando", "erro": None, "postado": False,
            "motivo": motivo, "reacao": tipo, "reacao_rotulo": ROTULOS_EXTRAS.get(tipo) or REACOES[tipo][0], "msgs": nota["msgs"],
            "forca": nota["nota"], "chat_marcante": mensagens_marcantes(nota["textos"]), "duracao": 0, "gancho": "", "post": "",
            "layout": None, "ajuste_camera": {"modo": "auto", "rect": None}, "grupos": [], "gravada_id": item["id"], "pos_live": momento,
            "momento_rel": momento - ini,
        }
        meta["pasta"] = self._pasta_para(meta)
        if item.get("programar"):
            self.postagem.ativar_pasta_nova(meta["pasta"])
        pasta = self.saida / corte_id
        pasta.mkdir(parents=True, exist_ok=True)
        with self.trava:
            self.cortes[corte_id] = meta
        self._salvar_corte(meta)
        edicao.executar(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{ini:.3f}", "-i", str(video), "-t", f"{fim - ini:.3f}", "-map", "0:v:0", "-map", "0:a:0?",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-c:a", "aac", "-b:a", "256k", "-f", "mpegts", str(pasta / "bruto.ts")]
        )
        self._etapa(meta, "fila")
        self.fila.put(("novo", corte_id))
        return corte_id

    # ------------------------------------------------------------ edição

    def _ouvir(self, pcm) -> str | None:
        """Escuta a live quando a legenda não está usando o Whisper."""
        if self._modelo is None or not self.trava_escuta.acquire(blocking=False):
            return None
        try:
            return edicao.ouvir_trecho(self._modelo, pcm, self.config["idioma"])
        finally:
            self.trava_escuta.release()

    def _modelo_whisper(self):
        nome = self.modelo_forcado or self.config["modelo"]
        if self._modelo is not None and self.legenda["nome"] == nome:
            return self._modelo
        self.legenda = {"estado": "carregando", "nome": nome}
        try:
            from faster_whisper import WhisperModel

            self._modelo = WhisperModel(nome, device="cpu", compute_type="int8", num_workers=1, cpu_threads=max(1, min(8, (os.cpu_count() or 4) - 2)))  # deixa núcleos livres para a janela e as gravações
            self.legenda = {"estado": "pronto", "nome": nome}
        except Exception as e:
            self._modelo = None
            self.legenda = {"estado": "indisponivel", "nome": nome, "erro": str(e)[:160]}
        return self._modelo

    def _editor(self) -> None:
        self._modelo_whisper()
        while True:
            item = self.fila.get()
            if item is None:
                return
            tipo, corte_id = item
            if tipo == "legendar":
                self.estudio.executar_legenda(corte_id)
                continue
            if tipo == "aprender":
                self.aprendizado.executar()
                continue
            meta = self.cortes.get(corte_id)
            if not meta:
                continue
            try:
                if tipo == "novo":
                    self._processar(meta)
                elif tipo == "encurtar":
                    self._encurtar(meta)
                else:
                    self._refazer(meta)
                self._etapa(meta, "pronto")
                self.evento(meta["canal"], "pronto", f"Corte pronto: {meta['gancho']}")
                if tipo == "novo":
                    self.montagens.corte_pronto(meta)
            except Exception as e:
                self._etapa(meta, "erro", str(e)[:300])
                self.evento(meta["canal"], "erro", "Um corte não pôde ser editado")

    def _processar(self, meta: dict) -> None:
        pasta = self.saida / meta["id"]
        bruto = pasta / "bruto.ts"
        self._etapa(meta, "transcrevendo")
        inicio_etapa = time.time()
        modelo = self._modelo_whisper()
        palavras = edicao.transcrever(modelo, bruto, self.config["idioma"]) if modelo else []
        meta["tempo_transcricao"] = round(time.time() - inicio_etapa, 1)
        total = cam.dimensoes(bruto)[2] or meta["momento_rel"] + APOS_REACAO
        momento = min(meta["momento_rel"], total)
        ini, fim = ctx.escolher_janela(
            palavras, momento, total, self.config["duracao_min"], min(59.0, self.config["duracao_max"]) if self.config["duracao_max"] <= 60 else self.config["duracao_max"],
        )  # Shorts acima de 1 minuto podem ser bloqueados por direitos autorais
        duracao = fim - ini
        fonte = pasta / "fonte.mp4"
        edicao.extrair_trecho(bruto, ini, duracao, fonte)
        trecho = [
            {"p": p["p"], "ini": round(max(0.0, p["ini"] - ini), 3), "fim": round(min(duracao, p["fim"] - ini), 3)}
            for p in palavras if p["fim"] > ini + 0.05 and p["ini"] < fim - 0.05
        ]
        titulo = meta.get("titulo_live") or ""
        meta["duracao"] = round(duracao, 2)
        # O chat reage alguns segundos depois do que aconteceu na tela.
        meta["momento_fonte"] = round(min(max(0.0, momento - ini - 4), max(0.0, duracao - 1)), 2)
        meta["gancho"] = ctx.criar_gancho(trecho, momento - ini, titulo, meta["reacao"])
        meta["post"] = ctx.criar_post(
            meta["gancho"], meta["canal"], meta["credito"], titulo, meta["plataforma"], meta["ident"],
        )
        meta["grupos"] = ctx.agrupar_legenda(trecho)
        meta["duracao_fonte"] = round(duracao, 3)
        meta["nucleo"] = ctx.nucleo_da_acao(meta["grupos"], meta["momento_fonte"], duracao)
        meta["curto"] = meta["nucleo"][1] - meta["nucleo"][0] <= 13 and duracao >= (meta["nucleo"][1] - meta["nucleo"][0]) * 1.8  # o resto seria só enchimento
        modelo = self.aprendizado.escolher_modelo(meta)
        perfil_modelo = self.aprendizado.perfil(modelo) if modelo else None
        if modelo:
            meta["modelo"] = modelo
            meta["estilo"] = {**self.aprendizado.estilo_do_modelo(modelo), **(meta.get("estilo") or {})}
        if est.normalizar(self.config["estilo"])["sons_auto"]:
            sons = sugerir_sons(meta["grupos"], duracao, meta["momento_fonte"], meta.get("reacao"))
            if perfil_modelo and perfil_modelo.get("sfx_cortes") is not None and perfil_modelo["sfx_cortes"] < .2:
                sons = sons[:1]  # este modelo quase não usa efeitos sonoros
            meta["edicao"] = edicao_inicial(duracao, sons)
        meta["replanejar"] = True
        edicao.executar(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{min(momento - ini, duracao - 0.5):.2f}", "-i", str(fonte),
             "-frames:v", "1", "-q:v", "3", str(pasta / "quadro.jpg")]
        )
        (pasta / "post.txt").write_text(meta["post"], encoding="utf-8")
        inicio_etapa = time.time()
        self._refazer(meta)
        meta["tempo_edicao"] = round(time.time() - inicio_etapa, 1)
        meta["pronto_em"] = round(time.time() - meta["criado"], 1)
        bruto.unlink(missing_ok=True)

    def pedir_encurtar(self, corte_id: str) -> None:
        meta = self.cortes[corte_id]
        if meta["status"] == "pronto" and not meta.get("projeto_exportado"):
            self._etapa(meta, "fila")
            self.fila.put(("encurtar", corte_id))

    def _encurtar(self, meta: dict, alvo: float = 59.0) -> None:
        """Mantém o final, onde está a reação, e começa em um bloco inteiro de fala."""
        pasta = self.saida / meta["id"]
        fonte = pasta / "fonte.mp4"
        if meta.get("edicao"):
            cortes = tl.encurtar_cortes(meta["edicao"]["cortes"], alvo)
            inicio = next((float(g["ini"]) for g in meta.get("grupos") or [] if float(g["ini"]) >= cortes[0][0]), cortes[0][0])  # começa em uma fala inteira
            cortes[0][0] = inicio if inicio < cortes[0][1] - 1 else cortes[0][0]
            meta["edicao"]["cortes"] = cortes
            meta["nao_encurtar"] = True
            self._refazer(meta)
            return
        duracao = float(meta["duracao"])
        minimo = max(0.0, duracao - alvo)
        grupos = meta.get("grupos") or []
        inicio = next((float(g["ini"]) for g in grupos if float(g["ini"]) >= minimo), minimo)
        if duracao - inicio < 20:
            inicio = minimo
        try:
            if not fonte.exists():
                raise FileNotFoundError("fonte")
            novo = pasta / "fonte_curta.mp4"
            edicao.extrair_trecho(fonte, inicio, duracao - inicio, novo)
            novo.replace(fonte)
        except Exception:
            meta["nao_encurtar"] = True
            return
        ajustados = []
        for g in grupos:
            palavras = [
                {"p": p["p"], "ini": round(float(p["ini"]) - inicio, 3), "fim": round(float(p["fim"]) - inicio, 3)}
                for p in g["palavras"] if float(p["ini"]) >= inicio
            ]
            if palavras:
                ajustados.append({"ini": palavras[0]["ini"], "fim": palavras[-1]["fim"], "palavras": palavras})
        meta["grupos"], meta["duracao"] = ajustados, round(duracao - inicio, 2)
        meta.pop("focos", None)  # os tempos mudaram junto com o início do vídeo
        if meta.get("momento_fonte") is not None:
            meta["momento_fonte"] = round(max(0.0, float(meta["momento_fonte"]) - inicio), 2)
        self._refazer(meta)

    def _refazer(self, meta: dict) -> None:
        pasta = self.saida / meta["id"]
        fonte = pasta / "fonte.mp4"
        if meta.get("replanejar") or not meta.get("plano"):
            self._etapa(meta, "enquadrando")
            try:
                meta["plano"] = self.aprendizado.ajustar_plano(cam.planejar(fonte, meta.get("ajuste_camera")), fonte, meta.get("modelo"))
            except Exception:
                meta["plano"] = {"layout": "inteiro", "origem": "auto"}
            meta["layout"] = meta["plano"]["layout"]
            meta["replanejar"] = False
        self._etapa(meta, "editando")
        if "focos" not in meta:
            try:
                meta["focos"] = achar_focos(fonte, meta.get("grupos") or [], meta["plano"], float(meta.get("duracao_fonte") or meta["duracao"]), meta.get("momento_fonte")) if self.config.get("foco_auto", True) else []
            except Exception:
                meta["focos"] = []
            if meta["focos"] and meta.get("edicao"):
                meta["edicao"]["sons"] = [*meta["edicao"]["sons"], *[{"som": "zoom_in", "t": f["t"], "volume": .36} for f in meta["focos"]]]
        focos = meta["focos"]
        titulo = meta.get("titulo_live") or ""
        contexto = ctx._encurtar(titulo, 46) if titulo else f"{meta['canal']} ao vivo no {meta['nome_plataforma']}"
        video, grupos, duracao, momento, ajuste = fonte, meta["grupos"], meta["duracao"], meta.get("momento_fonte"), None
        ed = meta.get("edicao")
        try:
            if ed:
                total = float(meta.get("duracao_fonte") or cam.dimensoes(fonte)[2] or meta["duracao"])
                meta["duracao_fonte"] = total
                duracao = tl.duracao_total(ed["cortes"])
                video = tl.montar_fonte(fonte, ed["cortes"], pasta / "montagem.mp4", total)
                grupos = tl.mapear_grupos(meta["grupos"], ed["cortes"])
                momento = None if momento is None else tl.saida_de(float(momento), ed["cortes"])
                focos = [{**f, "t": round(tl.saida_de(f["t"], ed["cortes"]), 3)} for f in focos if any(a <= f["t"] and f["t"] + f["dur"] <= b for a, b in ed["cortes"])]
                tl.criar_trilha(ed["sons"], ed["cortes"], duracao, self.biblioteca, pasta / "sons.wav")
                ajuste = {"filtro": ed.get("filtro"), "intensidade": ed.get("intensidade", 100), "volume": ed.get("volume", 100), "trilha": pasta / "sons.wav"}
                meta["duracao"] = round(duracao, 2)
            edicao.renderizar(
                video, pasta, meta["plano"], grupos, meta["gancho"], contexto, meta["credito"], duracao,
                momento, est.normalizar(meta.get("estilo"), self.config["estilo"]), ajuste, focos,
            )
        finally:
            for temporario in ("montagem.mp4", "sons.wav"):
                (pasta / temporario).unlink(missing_ok=True)
        meta["versao"] = int(meta.get("versao", 0)) + 1


def _descrever(causa: str, msgs: int, textos: list[str]) -> tuple[str, str]:
    if causa == "streamer":
        return "streamer", "O streamer reagiu forte"
    if causa == "admirado":
        return "admirado", "O streamer ficou admirado"
    if causa == "jogo":
        return "jogo", "Muita ação no jogo"
    tipo = classificar_reacao(textos)["tipo"] if textos else "hype"
    return tipo, f"O chat reagiu com {msgs} mensagens em {JANELA_CHAT} segundos"


def _validar_camera(ajuste: dict) -> dict:
    modo = ajuste.get("modo")
    if modo not in ("auto", "dividido", "tela_cheia", "inteiro"):
        raise ValueError("Enquadramento inválido.")
    rect = ajuste.get("rect")
    if rect is not None:
        if not (isinstance(rect, list) and len(rect) == 4):
            raise ValueError("Área da câmera inválida.")
        x, y, w, h = (float(v) for v in rect)
        if not (0 <= x < 1 and 0 <= y < 1 and 0.04 <= w <= 1 and 0.04 <= h <= 1 and x + w <= 1.001 and y + h <= 1.001):
            raise ValueError("Área da câmera inválida.")
        rect = [x, y, min(w, 1 - x), min(h, 1 - y)]
    return {"modo": modo, "rect": rect}
