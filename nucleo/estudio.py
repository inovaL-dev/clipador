"""Serviços do estúdio: projetos, prévia exata, exportação, capas, assistente e legendas."""
from __future__ import annotations

import base64
import copy
import json
import queue
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

import cv2

from . import assistente, capas, compositor as comp
from . import camera as cam
from . import contexto as ctx
from . import edicao, efeitos
from . import longo as lg
from . import projeto as pj
from . import texto
from . import timeline as tl
from .biblioteca import sugerir_sons

IMAGENS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEOS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIOS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
RESOLUCOES = (720, 1080, 1440, 2160)


def edicao_inicial(duracao: float, sons: list[dict] | None = None) -> dict:
    return {"cortes": [[0.0, round(duracao, 3)]], "sons": sons or [], "filtro": None, "intensidade": 100, "volume": 100}


class Estudio:
    def __init__(self, motor):
        self.motor = motor
        self.midias = comp.Midias(motor.saida, motor.dados, motor.biblioteca)
        self.pasta_midia = motor.dados / "midia"; self.pasta_midia.mkdir(parents=True, exist_ok=True)
        self.pasta_fontes = motor.dados / "fontes"; self.pasta_fontes.mkdir(parents=True, exist_ok=True)
        texto.usar_pasta_extra(self.pasta_fontes)
        self.modelos = capas.Modelos(motor.dados)
        self.arq_presets = motor.dados / "presets_estudio.json"
        self.trabalhos: dict[str, dict] = {}
        self.exportacoes: dict[str, dict] = {}
        self.fila_export: queue.Queue = queue.Queue()
        self.trava = threading.RLock()
        threading.Thread(target=self._exportador, daemon=True).start()

    # ------------------------------------------------------------ projetos

    def pasta(self, tipo: str, ident: str) -> Path:
        if tipo == "corte":
            if ident not in self.motor.cortes:
                raise KeyError(ident)
            return self.motor.saida / ident
        if ident not in self.motor.longos.itens:
            raise KeyError(ident)
        return self.motor.longos.pasta / ident

    def abrir(self, tipo: str, ident: str) -> dict:
        pasta = self.pasta(tipo, ident)
        with self.trava:
            proj = pj.carregar(pasta)
            if proj is None:
                proj = self._importar(tipo, ident)
                (pasta / "projeto_ia.json").write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
                pj.salvar(pasta, proj)
        return {"projeto": proj, "exportacao": self.exportacoes.get(f"{tipo}:{ident}")}

    def _importar(self, tipo: str, ident: str) -> dict:
        if tipo == "corte":
            meta = self.motor.cortes[ident]
            if meta["status"] not in ("pronto", "erro") or not (self.motor.saida / ident / "fonte.mp4").exists():
                raise ValueError("Este vídeo ainda não pode ser aberto no editor.")
            return pj.importar_corte(meta, self.motor)
        item = self.motor.longos.itens[ident]
        if item["status"] != "pronto":
            raise ValueError("Aguarde este vídeo terminar de ser editado.")
        return pj.importar_longo(item, self.motor)

    def salvar(self, tipo: str, ident: str, proj: dict) -> dict:
        pj.salvar(self.pasta(tipo, ident), pj.validar(proj))
        return {"modificado": proj["modificado"]}

    def restaurar_ia(self, tipo: str, ident: str) -> dict:
        pasta = self.pasta(tipo, ident)
        proj = json.loads((pasta / "projeto_ia.json").read_text(encoding="utf-8"))
        pj.salvar(pasta, proj)
        return {"projeto": proj}

    def arquivo_midia(self, raiz: str, rel: str) -> Path:
        return self.midias.caminho({"raiz": raiz, "rel": rel})

    def onda(self, raiz: str, rel: str) -> list[float]:
        arq = self.arquivo_midia(raiz, rel)
        destino = self.motor.tmp / f"onda_{uuid.uuid5(uuid.NAMESPACE_URL, f'{arq}:{arq.stat().st_mtime_ns}').hex}.json"
        if destino.exists():
            return json.loads(destino.read_text(encoding="utf-8"))
        picos = tl.picos_do_audio(efeitos.ler_pcm(arq, taxa=8000), 4000)
        destino.write_text(json.dumps(picos), encoding="utf-8")
        return picos

    def quadro(self, proj: dict, t: float, altura: int = 720) -> bytes:
        pj.validar(proj)
        menor = min(proj["largura"], proj["altura"])
        c = comp.Compositor({**proj, "duracao": comp.duracao_projeto(proj)}, self.midias, min(1.0, altura / max(proj["largura"], proj["altura"])), solto=True)
        ok, jpg = cv2.imencode(".jpg", c.quadro(max(0.0, float(t))), [cv2.IMWRITE_JPEG_QUALITY, 94])
        return jpg.tobytes()

    def previa(self, proj: dict, ini: float, fim: float, fps: int = 12, altura: int = 720) -> dict:
        """Renderiza um trecho curto sem salvar nada, para ver o resultado antes de aplicar."""
        pj.validar(proj)
        self._pedido_previa = pedido = getattr(self, "_pedido_previa", 0) + 1
        fps = max(4, min(24, int(fps)))
        ini = max(0.0, float(ini))
        total = max(1, min(40, round((max(ini, float(fim)) - ini) * fps)))
        escala = min(1.0, max(240, min(720, int(altura))) / max(proj["largura"], proj["altura"]))
        c = comp.Compositor({**proj, "duracao": comp.duracao_projeto(proj)}, self.midias, escala)
        quadros = []
        try:
            for n in range(total):
                if pedido != self._pedido_previa:
                    return {"cancelada": True, "quadros": [], "fps": fps}
                ok, jpg = cv2.imencode(".jpg", c.quadro(ini + n / fps), [cv2.IMWRITE_JPEG_QUALITY, 82])
                if ok:
                    quadros.append(base64.b64encode(jpg.tobytes()).decode("ascii"))
        finally:
            c.fechar()
        return {"quadros": quadros, "fps": fps}

    def enviar_midia(self, nome: str, corpo, tamanho: int) -> dict:
        ext = Path(nome).suffix.lower()
        tipo = "imagem" if ext in IMAGENS else "video" if ext in VIDEOS else "audio" if ext in AUDIOS else None
        if not tipo:
            raise ValueError("Use imagem (JPG, PNG, WEBP), vídeo (MP4, MOV, MKV, WEBM) ou áudio (MP3, WAV, OGG, M4A).")
        mid = f"u{uuid.uuid4().hex[:12]}"
        destino = self.pasta_midia / f"{mid}{ext}"
        with open(destino, "wb") as f:
            restante = tamanho
            while restante > 0:
                bloco = corpo.read(min(restante, 1024 * 1024))
                if not bloco:
                    break
                f.write(bloco); restante -= len(bloco)
        d = {"id": mid, "tipo": tipo, "raiz": "dados", "rel": f"midia/{destino.name}", "nome": Path(nome).stem[:60]}
        try:
            if tipo == "imagem":
                im = cv2.imread(str(destino), cv2.IMREAD_UNCHANGED)
                if im is None:
                    raise ValueError
                d.update(lar=im.shape[1], alt=im.shape[0])
            elif tipo == "video":
                d["lar"], d["alt"], d["dur"] = cam.dimensoes(destino)
            else:
                d["dur"] = len(efeitos.ler_pcm(destino, taxa=8000)) / 8000
            if tipo != "imagem" and not d.get("dur"):
                raise ValueError
        except (ValueError, IndexError, OSError):
            destino.unlink(missing_ok=True)
            raise ValueError("Não consegui ler este arquivo.") from None
        return d

    def enviar_fonte(self, nome: str, conteudo: bytes) -> list[dict]:
        ext = Path(nome).suffix.lower()
        limpo = re.sub(r"[^\w -]", "", Path(nome).stem)[:50].strip() or "Minha fonte"
        if ext not in (".ttf", ".otf"):
            raise ValueError("Use uma fonte TTF ou OTF.")
        destino = self.pasta_fontes / f"{limpo}{ext}"
        destino.write_bytes(conteudo)
        try:
            texto.ImageFont.truetype(str(destino), 20)
        except OSError:
            destino.unlink(missing_ok=True)
            raise ValueError("Não consegui ler esta fonte.") from None
        return texto.catalogo()

    def arquivo_fonte(self, nome: str) -> Path | None:
        for pasta in (self.pasta_fontes, texto.PASTA_FONTES):
            alvo = (pasta / nome).resolve()
            if alvo.parent == pasta.resolve() and alvo.exists():
                return alvo
        return None

    # ------------------------------------------------------------ presets do projeto

    def presets(self) -> list[dict]:
        try:
            return json.loads(self.arq_presets.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def salvar_preset(self, nome: str, conteudo: dict) -> list[dict]:
        nome = str(nome).strip()[:50]
        if not nome:
            raise ValueError("Dê um nome ao preset.")
        lista = [p for p in self.presets() if p["nome"] != nome] + [{"id": pj.novo_id("p"), "nome": nome, "global": conteudo}]
        self.arq_presets.write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
        return lista

    def apagar_preset(self, ident: str) -> list[dict]:
        lista = [p for p in self.presets() if p["id"] != ident]
        self.arq_presets.write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
        return lista

    # ------------------------------------------------------------ capas

    def abrir_capa(self, tipo: str, ident: str) -> dict:
        pasta = self.pasta(tipo, ident)
        arq = pasta / "capa.json"
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8"))
        capa = capas.criar_corte(self.motor.cortes[ident], self.motor) if tipo == "corte" else capas.criar_longo(self.motor.longos.itens[ident], self.motor)
        arq.write_text(json.dumps(capa, ensure_ascii=False), encoding="utf-8")
        (pasta / "capa_ia.json").write_text(json.dumps(capa, ensure_ascii=False), encoding="utf-8")
        return capa

    def salvar_capa(self, tipo: str, ident: str, capa: dict) -> dict:
        if not isinstance(capa.get("camadas"), list):
            raise ValueError("Capa inválida.")
        (self.pasta(tipo, ident) / "capa.json").write_text(json.dumps(capa, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}

    def quadro_capa(self, capa: dict, escala: float = 1.0) -> bytes:
        ok, jpg = cv2.imencode(".jpg", capas.renderizar(capa, self.midias, min(2.0, escala)), [cv2.IMWRITE_JPEG_QUALITY, 90])
        return jpg.tobytes()

    def exportar_capa(self, tipo: str, ident: str, capa: dict, largura: int) -> dict:
        self.salvar_capa(tipo, ident, capa)
        escala = max(640, min(3840, int(largura))) / capa["largura"]
        q = capas.renderizar(capa, self.midias, escala)
        pasta = self.pasta(tipo, ident)
        cv2.imwrite(str(pasta / "capa_nova.jpg"), q, [cv2.IMWRITE_JPEG_QUALITY, 96])
        (pasta / "capa_nova.jpg").replace(pasta / "capa.jpg")
        cv2.imwrite(str(pasta / "capa.png"), q)
        alvo = self.motor.cortes.get(ident) if tipo == "corte" else self.motor.longos.itens.get(ident)
        alvo["versao"] = int(alvo.get("versao", 0)) + 1
        self.motor._salvar_corte(alvo) if tipo == "corte" else self.motor.longos._salvar(alvo)
        return {"largura": q.shape[1], "altura": q.shape[0], "url": f"/{'cortes' if tipo == 'corte' else 'longos'}/{ident}/capa.jpg?baixar=1"}

    # ------------------------------------------------------------ assistente

    def analisar(self, proj: dict) -> list[dict]:
        return assistente.analisar(pj.validar(proj), self.midias)

    def aplicar_sugestoes(self, proj: dict, sugestoes: list[dict]) -> dict:
        return {"projeto": assistente.aplicar(pj.validar(proj), sugestoes)}

    def sugerir_sons(self, proj: dict) -> list[dict]:
        leg = [i for f in proj["faixas"] if f["tipo"] == "legenda" for i in f["itens"]]
        grupos = [{"ini": i["ini"], "fim": i["ini"] + i["dur"], "palavras": [{"p": p["p"], "ini": i["ini"] + p["ini"], "fim": i["ini"] + p["fim"]} for p in i.get("palavras") or []]} for i in leg]
        clarao = next((i for f in proj["faixas"] for i in f["itens"] if i.get("efeito") == "clarao"), None)
        return sugerir_sons(grupos, comp.duracao_projeto(proj), clarao["ini"] if clarao else None, None)

    def pedir_trabalho(self, tipo: str, ident: str, nome: str, dados: dict) -> dict:
        chave = f"{nome}|{tipo}|{ident}"
        self.trabalhos[chave] = {"estado": "fila", "dados": dados}
        self.motor.fila.put(("legendar", chave))
        return {"estado": "fila"}

    def estado_trabalho(self, tipo: str, ident: str, nome: str) -> dict:
        t = self.trabalhos.get(f"{nome}|{tipo}|{ident}") or {"estado": "parado"}
        return {k: v for k, v in t.items() if k != "dados"}

    def executar_legenda(self, chave: str) -> None:
        nome, tipo, ident = chave.split("|", 2)
        dados = self.trabalhos[chave].get("dados") or {}
        self.trabalhos[chave] = {"estado": "ouvindo"}
        try:
            modelo = self.motor._modelo_whisper()
            if modelo is None:
                raise ValueError("O gerador de legendas ainda não está disponível.")
            proj = pj.validar(dados["projeto"])
            resultado = self._refazer_cena(proj, dados["cena"], modelo) if nome == "cena" else self._gerar_legendas(proj, modelo)
            self.trabalhos[chave] = {"estado": "pronto", "projeto": resultado}
        except Exception as e:
            self.trabalhos[chave] = {"estado": "erro", "erro": str(e)[:240]}

    def _transcrever(self, proj: dict, modelo) -> list[dict]:
        with tempfile.TemporaryDirectory(prefix="clipador_leg_") as tmp:
            fala, _ = comp.mixar({**proj, "faixas": [f for f in proj["faixas"] if f["tipo"] == "video"]}, self.midias, Path(tmp), comp.duracao_projeto(proj))
            return edicao.transcrever(modelo, fala, self.motor.config["idioma"])

    def _gerar_legendas(self, proj: dict, modelo) -> dict:
        palavras = self._transcrever(proj, modelo)
        total = comp.duracao_projeto(proj)
        faixa = next((f for f in proj["faixas"] if f["tipo"] == "legenda"), None)
        if faixa is None:
            faixa = pj._faixa("legenda", "Legendas"); proj["faixas"].append(faixa)
        faixa["itens"] = pj.legendas_de(ctx.agrupar_legenda(palavras), 0, total)
        return proj

    def _refazer_cena(self, proj: dict, cena: str, modelo) -> dict:
        """Refaz zooms e legendas só desta cena. O resto do projeto não é tocado."""
        videos = [i for f in proj["faixas"] if f["tipo"] == "video" for i in f["itens"] if i.get("cena") == cena and i["tipo"] == "video" and not i.get("ajustes", {}).get("desfoque")]
        if not videos:
            raise ValueError("Selecione uma cena que tenha vídeo.")
        ini, fim = min(i["ini"] for i in videos), max(i["ini"] + i["dur"] for i in videos)
        dur = fim - ini
        principal = next((i for i in videos if not i.get("mudo")), videos[0])
        fonte = self.midias.caminho(proj["midias"][principal["midia"]])
        picos = efeitos.batidas(fonte, principal.get("entrada", 0.0), dur)
        momento = max(picos, key=lambda p: p[1])[0] if picos else dur * .6
        quadros = max(1, round(dur * 30))
        if proj["altura"] > proj["largura"]:
            layout = "dividido" if len(videos) > 1 else "inteiro"
            movs = edicao._agenda_short(layout, quadros, dur, momento, picos)
        else:
            movs = [lg.agendar(dur, momento, picos, {"layout": "inteiro"})["mov"]]
        for n, item in enumerate(videos):
            mov = movs[min(n, len(movs) - 1)]
            item["kf"] = pj._chaves(mov); item["t"].update(pj._base(mov))
        with tempfile.TemporaryDirectory(prefix="clipador_cena_") as tmp:
            amostra = Path(tmp) / "cena.wav"
            edicao.executar(["ffmpeg", "-v", "error", "-y", "-ss", f"{principal.get('entrada', 0.0):.3f}", "-t", f"{dur * principal.get('velocidade', 1):.3f}", "-i", str(fonte), "-vn", "-ac", "1", "-ar", "16000", str(amostra)])
            palavras = edicao.transcrever(modelo, amostra, self.motor.config["idioma"])
        for f in proj["faixas"]:
            if f["tipo"] == "legenda":
                f["itens"] = [i for i in f["itens"] if not (i.get("cena") == cena or ini <= i["ini"] < fim)]
                f["itens"] = sorted(f["itens"] + pj.legendas_de(ctx.agrupar_legenda(palavras), ini, dur, cena), key=lambda i: i["ini"])
                break
        return proj

    # ------------------------------------------------------------ exportação

    def pedir_exportacao(self, tipo: str, ident: str, proj: dict, altura: int) -> dict:
        if int(altura) not in RESOLUCOES:
            raise ValueError("Escolha uma resolução válida.")
        chave = f"{tipo}:{ident}"
        atual = self.exportacoes.get(chave)
        if atual and atual["estado"] in ("fila", "gerando"):
            raise ValueError("Este vídeo já está sendo exportado.")
        self.salvar(tipo, ident, proj)
        self.exportacoes[chave] = {"estado": "fila", "progresso": 0, "etapa": "Na fila", "cancelar": False}
        self.fila_export.put((tipo, ident, copy.deepcopy(proj), int(altura)))
        return self.estado_exportacao(tipo, ident)

    def estado_exportacao(self, tipo: str, ident: str) -> dict:
        return {k: v for k, v in (self.exportacoes.get(f"{tipo}:{ident}") or {"estado": "parado"}).items() if k != "cancelar"}

    def cancelar_exportacao(self, tipo: str, ident: str) -> dict:
        if f"{tipo}:{ident}" in self.exportacoes:
            self.exportacoes[f"{tipo}:{ident}"]["cancelar"] = True
        return {"ok": True}

    def _exportador(self) -> None:
        while not self.motor.fim.is_set():
            try:
                tipo, ident, proj, altura = self.fila_export.get(timeout=1)
            except queue.Empty:
                continue
            ex = self.exportacoes[f"{tipo}:{ident}"]
            try:
                pasta = self.pasta(tipo, ident)
                destino = pasta / "exportando.mp4"
                ex.update(estado="gerando")
                comp.exportar(proj, self.midias, destino, altura, lambda p, etapa: ex.update(progresso=round(p * 100), etapa=etapa), lambda: ex["cancelar"])
                self._concluir(tipo, ident, proj, destino, pasta)
                ex.update(estado="pronto", progresso=100, etapa="Vídeo exportado")
                self.motor.evento(self.motor.cortes[ident]["canal"] if tipo == "corte" else self.motor.longos.itens[ident]["canal"], "pronto", "Vídeo do editor exportado")
            except InterruptedError:
                (self.pasta(tipo, ident) / "exportando.mp4").unlink(missing_ok=True)
                ex.update(estado="cancelado", etapa="Exportação cancelada")
            except Exception as e:
                ex.update(estado="erro", erro=str(e)[:300], etapa="A exportação falhou")

    def _concluir(self, tipo: str, ident: str, proj: dict, destino: Path, pasta: Path) -> None:
        try:
            self.motor.aprendizado.registrar_edicao(proj, json.loads((pasta / "projeto_ia.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        total = comp.duracao_projeto(proj)
        grupos = [{"ini": i["ini"], "fim": i["ini"] + i["dur"], "palavras": [{"p": p["p"], "ini": i["ini"] + p["ini"], "fim": i["ini"] + p["fim"]} for p in (i.get("palavras") or [{"p": i["texto"], "ini": 0, "fim": i["dur"]}])]}
                  for f in proj["faixas"] if f["tipo"] == "legenda" and not f.get("oculta") for i in sorted(f["itens"], key=lambda x: x["ini"])]
        if tipo == "corte":
            original = pasta / "corte_ia.mp4"
            if not original.exists() and (pasta / "corte.mp4").exists():
                shutil.copy(pasta / "corte.mp4", original)
            destino.replace(pasta / "corte.mp4")
            (pasta / "legenda.srt").write_text(edicao.gerar_srt(grupos), encoding="utf-8")
            meta = self.motor.cortes[ident]
            meta.update(duracao=round(total, 2), projeto_exportado=True, nao_encurtar=True, versao=int(meta.get("versao", 0)) + 1)
            gancho = next((i["texto"] for f in proj["faixas"] for i in f["itens"] if i.get("papel") == "gancho"), None)
            if gancho:
                meta["gancho"] = gancho
            if not (pasta / "capa.json").exists():
                edicao.executar(["ffmpeg", "-v", "error", "-y", "-ss", f"{min(2.0, total / 2):.2f}", "-i", str(pasta / "corte.mp4"), "-frames:v", "1", "-q:v", "2", str(pasta / "capa.jpg")])
            self.motor._salvar_corte(meta)
            return
        item = self.motor.longos.itens[ident]
        base = pasta / "base.mp4"
        if not base.exists():
            shutil.copy(pasta / "video.mp4", base)
        lg._substituir(destino, pasta / "video.mp4")
        marcas = sorted((i["ini"], i["texto"].title()) for f in proj["faixas"] for i in f["itens"] if i.get("papel") == "capitulo")
        capitulos = lg.capitulos_editados([{"t": 0.0, "titulo": "Introdução"}, *[{"t": t, "titulo": n} for t, n in marcas]], [[0.0, total]], total)
        item.update(duracao=round(total, 2), capitulos=capitulos or item.get("capitulos") or [], descricao=lg._descricao_com_capitulos(item.get("descricao") or "", capitulos) if capitulos else item.get("descricao"),
                    versao=int(item.get("versao", 0)) + 1, projeto_exportado=True, aviso=None)
        self.motor.longos._salvar(item)
