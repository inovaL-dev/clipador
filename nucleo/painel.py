"""Servidor local do painel: páginas, API e entrega dos vídeos."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from . import audio_fx, capas, estilos, ferramentas, filtros, texto
from .versao import VERSAO
from .biblioteca import CATEGORIAS, LIMITE_ENVIO
from .longo import posicoes_padrao, previa_estilo
from .motor import Motor
from .youtube import ErroYouTube

WEB = Path(__file__).resolve().parent.parent / "web"
ARQUIVOS_CORTE = {"corte.mp4", "capa.jpg", "quadro.jpg", "legenda.srt", "post.txt"}
ID_VALIDO = re.compile(r"^[\w-]+$")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("text/javascript", ".js")



from .painel_json import para_json  # noqa: E402

class Painel(BaseHTTPRequestHandler):
    server_version = "Clipador"
    protocol_version = "HTTP/1.1"
    motor: Motor
    janela_propria = False  # o login do Google não abre dentro da janela do programa
    ao_encerrar = None
    ao_mostrar = None
    ultimo_sinal = 0.0
    tela_visivel = False
    info_programa = None
    definir_programa = None

    def log_message(self, *args):
        pass

    # ------------------------------------------------------------ respostas

    def _json(self, dados, codigo=200):
        corpo = json.dumps(dados, ensure_ascii=False, default=para_json).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _erro(self, mensagem, codigo=400):
        self._json({"erro": mensagem}, codigo)

    def _arquivo(self, arquivo: Path, baixar_como: str | None = None, cache="no-cache"):
        if not arquivo.is_file():
            return self._erro("Arquivo não encontrado.", 404)
        tamanho = arquivo.stat().st_size
        ini, fim, codigo = 0, tamanho - 1, 200
        faixa = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if faixa and tamanho and (faixa[1] or faixa[2]):
            if faixa[1]:
                ini = int(faixa[1])
                fim = min(int(faixa[2]), tamanho - 1) if faixa[2] else tamanho - 1
            else:
                ini = max(0, tamanho - int(faixa[2]))
            if ini > fim:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{tamanho}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            codigo = 206
        self.send_response(codigo)
        self.send_header("Content-Type", mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - ini + 1))
        self.send_header("Cache-Control", cache)
        if codigo == 206:
            self.send_header("Content-Range", f"bytes {ini}-{fim}/{tamanho}")
        if baixar_como:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(baixar_como)}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(arquivo, "rb") as f:
            f.seek(ini)
            restante = fim - ini + 1
            try:
                while restante > 0:
                    bloco = f.read(min(256 * 1024, restante))
                    if not bloco:
                        break
                    self.wfile.write(bloco)
                    restante -= len(bloco)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True

    # ------------------------------------------------------------ segurança

    def _origem_local(self) -> bool:
        """Só aceita pedidos feitos pelo próprio painel, nunca por outros sites abertos no navegador."""
        host = self.headers.get("Host", "")
        if not re.fullmatch(r"(127\.0\.0\.1|localhost)(:\d+)?", host):
            return False
        origem = self.headers.get("Origin")
        return origem is None or origem in (f"http://{host}",)

    def _corpo(self) -> dict:
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > 60_000_000:
            raise ValueError("Pedido grande demais.")
        if not tamanho:
            return {}
        dados = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("Pedido inválido.")
        return dados

    # ------------------------------------------------------------ rotas

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._origem_local():
            return self._erro("Acesso permitido apenas neste computador.", 403)
        partes = urlsplit(self.path)
        caminho = partes.path
        if caminho == "/":
            return self._arquivo(WEB / "index.html")
        if caminho == "/oauth/retorno":
            return self._retorno_oauth(parse_qs(partes.query))
        if caminho == "/api/estado":
            try:
                return self._json(self.motor.estado())
            except Exception:
                import traceback
                print("[estado] " + traceback.format_exc(), flush=True)
                return self._erro("O programa não conseguiu montar a tela. O motivo foi anotado no registro.", 500)
        if m := re.fullmatch(r"/web/([\w.-]+(?:/[\w.-]+)?)", caminho):
            alvo = (WEB / m[1]).resolve()
            if WEB.resolve() in alvo.parents:
                return self._arquivo(alvo, cache="max-age=3600" if "fontes" in m[1] else "no-cache")
            return self._erro("Arquivo não encontrado.", 404)
        if m := re.fullmatch(r"/api/canais/([\w-]+)/quadro\.jpg", caminho):
            try:
                quadro = self.motor.quadro_canal(m[1])
            except KeyError:
                return self._erro("Canal não encontrado.", 404)
            return self._arquivo(quadro) if quadro else self._erro("A imagem aparece quando a live começar.", 404)
        if m := re.fullmatch(r"/api/cortes/([\w-]+)", caminho):
            meta = self.motor.cortes.get(m[1])
            return self._json(meta) if meta else self._erro("Corte não encontrado.", 404)
        if m := re.fullmatch(r"/cortes/([\w-]+)/([\w.]+)", caminho):
            if m[2] not in ARQUIVOS_CORTE or m[1] not in self.motor.cortes:
                return self._erro("Arquivo não encontrado.", 404)
            baixar = None
            if "baixar" in parse_qs(partes.query):
                meta = self.motor.cortes[m[1]]
                nome = re.sub(r"[^\w -]", "", meta.get("gancho") or "corte").strip()[:60] or "corte"
                baixar = f"{nome}{Path(m[2]).suffix}"
            return self._arquivo(self.motor.saida / m[1] / m[2], baixar)
        if caminho == "/api/aprendizado":
            return self._json(self.motor.aprendizado.resumo())
        if caminho == "/api/programa":
            info = type(self).info_programa() if type(self).info_programa else {}
            return self._json({"versao": VERSAO, "pode_encerrar": bool(self.ao_encerrar) and not self.janela_propria and not info.get("disponivel"), **info})
        if caminho == "/api/sons":
            consulta = parse_qs(partes.query)
            return self._json({"sons": self.motor.biblioteca.listar(consulta.get("q", [""])[0], consulta.get("categoria", [""])[0]), "categorias": ["Meus sons", *CATEGORIAS]})
        if m := re.fullmatch(r"/sons/([\w-]+)\.wav", caminho):
            try:
                return self._arquivo(self.motor.biblioteca.caminho(m[1]), cache="max-age=86400")
            except KeyError:
                return self._erro("Som não encontrado.", 404)
        if caminho == "/api/filtros":
            return self._json(filtros.lista())
        if m := re.fullmatch(r"/fontes/([\w .-]+\.(?:ttf|otf))", caminho):
            alvo = self.motor.estudio.arquivo_fonte(m[1])
            return self._arquivo(alvo, cache="max-age=86400") if alvo else self._erro("Fonte não encontrada.", 404)
        if caminho == "/estudio/midia":
            c = parse_qs(partes.query)
            return self._pedido_get(lambda: self._arquivo(self.motor.estudio.arquivo_midia(c.get("raiz", [""])[0], c.get("rel", [""])[0])))
        if caminho == "/api/estudio/onda":
            c = parse_qs(partes.query)
            return self._pedido_get(lambda: self._json(self.motor.estudio.onda(c.get("raiz", [""])[0], c.get("rel", [""])[0])))
        if caminho == "/api/estudio/fontes":
            return self._json(texto.catalogo())
        if caminho == "/api/posts":
            return self._json(self.motor.posts.listar(parse_qs(partes.query).get("pasta", [""])[0]))
        if m := re.fullmatch(r"/api/posts/([\w-]+)/([\w-]+)", caminho):
            n = parse_qs(partes.query).get("n", ["2"])[0]
            return self._pedido_get(lambda: self._json(self.motor.posts.detalhes(m[1], m[2], int(n) if n.isdigit() else 2)))
        if m := re.fullmatch(r"/posts/([\w-]+)/(p[0-9a-f]{10}(?:_mini)?)\.jpg", caminho):
            alvo = self.motor.posts.imagem(m[1], m[2])
            return self._arquivo(alvo, cache="max-age=86400") if alvo else self._erro("Imagem não encontrada.", 404)
        if caminho == "/api/estudio/efeitos-audio":
            return self._json(audio_fx.lista())
        if caminho == "/api/estudio/idiomas":
            return self._json([{"id": k, "nome": v} for k, v in ferramentas.IDIOMAS.items()])
        if caminho == "/api/estudio/tira":
            c = parse_qs(partes.query)
            return self._pedido_get(lambda: self._json(self.motor.estudio.tira(c.get("raiz", [""])[0], c.get("rel", [""])[0])))
        if caminho == "/api/estudio/tira.jpg":
            alvo = self.motor.estudio.arquivo_tira(parse_qs(partes.query).get("k", [""])[0])
            return self._arquivo(alvo, cache="max-age=86400") if alvo else self._erro("Miniaturas não encontradas.", 404)
        if caminho == "/api/estudio/presets":
            return self._json(self.motor.estudio.presets())
        if caminho == "/api/estudio/modelos-capa":
            return self._json(self.motor.estudio.modelos.listar())
        if m := re.fullmatch(r"/api/estudio/(corte|longo)/([\w-]+)(?:/(capa|exportar|trabalho/legendas|trabalho/cena))?", caminho):
            e = self.motor.estudio
            acoes = {None: lambda: e.abrir(m[1], m[2]), "capa": lambda: e.abrir_capa(m[1], m[2]), "exportar": lambda: e.estado_exportacao(m[1], m[2]),
                     "trabalho/legendas": lambda: e.estado_trabalho(m[1], m[2], "legendas"), "trabalho/cena": lambda: e.estado_trabalho(m[1], m[2], "cena")}
            return self._pedido_get(lambda: self._json(acoes[m[3]]()))
        if caminho == "/api/estilo/posicoes":
            return self._json(posicoes_padrao(self._corte_previa()))
        if m := re.fullmatch(r"/api/postagem/itens/([\w-]+)", caminho):
            item = self.motor.postagem.itens.get(m[1])
            return self._json(item) if item else self._erro("Item não encontrado.", 404)
        if caminho == "/api/estilo/amostras":
            from . import projeto as pj
            cor = (parse_qs(partes.query).get("cor") or ["amarelo"])[0]
            cor = cor if cor in estilos.CORES else "amarelo"
            base = estilos.normalizar({**self.motor.config["estilo"], "cor": cor})
            leg = {g: pj.estilo_legenda({**base, "legenda": g}, 1080, 1920) for g in estilos.LEGENDAS}
            tit = {g: {**pj.estilo_titulo({**base, "gancho": g}, 54), "rot": estilos.TITULOS_EXTRA.get(g, (0,) * 9)[8] or (-2 if g == "branco" else 0)} for g in estilos.GANCHOS if g != "nenhum"}
            return self._json({"legendas": leg, "titulos": tit})
        if caminho == "/api/estudio/modelos-titulo":
            from . import projeto as pj
            cor = (parse_qs(partes.query).get("cor") or ["amarelo"])[0]
            saida = []
            for g in estilos.GANCHOS:
                if g == "nenhum":
                    continue
                est = estilos.normalizar({**self.motor.config["estilo"], "gancho": g, "cor": cor if cor in estilos.CORES else "amarelo"})
                giro = estilos.TITULOS_EXTRA.get(g, (0,) * 9)[8] or (-2 if g == "branco" else 0)
                saida.append({"id": g, "estilo": pj._item_texto("texto", 0, 1, "", 0, 0, pj.estilo_titulo(est, 54))["estilo"], "rot": giro})
            return self._json(saida)
        if caminho == "/api/estilo/previa.jpg":
            return self._previa(parse_qs(partes.query))
        if m := re.fullmatch(r"/longos/([\w-]+)/(video\.mp4|capa\.jpg)", caminho):
            item = self.motor.longos.itens.get(m[1])
            if not item:
                return self._erro("Arquivo não encontrado.", 404)
            baixar = None
            if "baixar" in parse_qs(partes.query):
                nome = re.sub(r"[^\w -]", "", item.get("titulo") or "video").strip()[:70] or "video"
                baixar = f"{nome}{Path(m[2]).suffix}"
            return self._arquivo(self.motor.longos.pasta / m[1] / m[2], baixar)
        return self._erro("Página não encontrada.", 404)

    def _pedido_get(self, funcao):
        try:
            return funcao()
        except KeyError:
            return self._erro("Vídeo não encontrado.", 404)
        except (ValueError, RuntimeError, OSError) as e:
            return self._erro(str(e)[:240])

    def _binario(self, funcao):
        if not self._origem_local():
            return self._erro("Acesso permitido apenas neste computador.", 403)
        try:
            dados = funcao(self._corpo())
        except KeyError:
            return self._erro("Item não encontrado.", 404)
        except (ValueError, TypeError, RuntimeError, OSError) as e:
            return self._erro(str(e)[:240] or "Pedido inválido.")
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _baixar(self, funcao, tipo: str):
        """Responde com um arquivo gerado na hora (zip, wav)."""
        if not self._origem_local():
            return self._erro("Acesso permitido apenas neste computador.", 403)
        try:
            resultado = funcao(self._corpo())
        except KeyError:
            return self._erro("Item não encontrado.", 404)
        except (ValueError, TypeError, RuntimeError, OSError) as e:
            return self._erro(str(e)[:240] or "Pedido inválido.")
        dados, nome = resultado if isinstance(resultado, tuple) else (resultado, None)
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        if nome:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(nome)}")
        self.end_headers()
        self.wfile.write(dados)

    def _arte_post(self, d: dict):
        import io as _io
        img = self.motor.posts.arte(str(d.get("corte", "")), str(d.get("frase", "")), d)
        buf = _io.BytesIO()
        if d.get("previa"):  # prévia rápida enquanto a pessoa edita
            img.thumbnail((540, 960))
            img.save(buf, "JPEG", quality=86)
            return buf.getvalue()
        img.save(buf, "PNG", optimize=True)
        nome = re.sub(r"[^\w -]", "", str(d.get("nome") or "post")).strip()[:50] or "post"
        return buf.getvalue(), f"{nome}.png"

    def _receber_lut(self):
        if not self._origem_local():
            return self._erro("Acesso permitido apenas neste computador.", 403)
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > 40_000_000:
            self.close_connection = True
            return self._erro("A LUT precisa ter no máximo 40 MB.", 413)
        nome = parse_qs(urlsplit(self.path).query).get("nome", ["lut.cube"])[0]
        try:
            return self._json(self.motor.estudio.enviar_lut(nome, self.rfile.read(tamanho)))
        except ValueError as e:
            return self._erro(str(e))

    def _receber_estudio(self, caminho: str):
        if not self._origem_local():
            return self._erro("Acesso permitido apenas neste computador.", 403)
        tamanho = int(self.headers.get("Content-Length") or 0)
        nome = parse_qs(urlsplit(self.path).query).get("nome", ["arquivo"])[0]
        try:
            if caminho.endswith("fontes"):
                return self._json(self.motor.estudio.enviar_fonte(nome, self.rfile.read(min(tamanho, 30_000_000))))
            return self._json(self.motor.estudio.enviar_midia(nome, self.rfile, tamanho))
        except ValueError as e:
            self.close_connection = True
            return self._erro(str(e))

    def _receber_video(self):
        if not self._origem_local():
            return self._erro("Acesso permitido apenas neste computador.", 403)
        tamanho = int(self.headers.get("Content-Length") or 0)
        nome = parse_qs(urlsplit(self.path).query).get("nome", ["video"])[0]
        try:
            return self._json(self.motor.gravadas.receber_envio(nome, self.rfile, tamanho))
        except (ValueError, OSError) as e:
            self.close_connection = True
            return self._erro(str(e)[:240] or "Não foi possível receber o vídeo.")

    def _receber_som(self):
        if not self._origem_local():
            return self._erro("Acesso permitido apenas neste computador.", 403)
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > LIMITE_ENVIO:
            self.close_connection = True
            return self._erro("O som precisa ter no máximo 120 MB.", 413)
        nome = parse_qs(urlsplit(self.path).query).get("nome", ["Meu som"])[0]
        try:
            return self._json(self.motor.biblioteca.enviar(nome, self.rfile.read(tamanho)))
        except ValueError as e:
            return self._erro(str(e))

    def _corte_previa(self) -> dict | None:
        cortes = [c for c in list(self.motor.cortes.values()) if c.get("status") == "pronto" and c.get("plano")]
        return max(cortes, key=lambda c: c["criado"], default=None)

    def _previa(self, consulta: dict):
        dados = {k: v[0] for k, v in consulta.items() if k in estilos.PADRAO}
        formato = "h" if consulta.get("formato", ["v"])[0] == "h" else "v"
        try:
            est = estilos.validar(dados)
            corte = self._corte_previa()
            chave = hashlib.sha1(json.dumps([est, formato, corte and corte["id"]], sort_keys=True).encode()).hexdigest()[:16]
            destino = self.motor.tmp / f"previa_{chave}.jpg"
            if not destino.exists():
                previa_estilo(est, formato, corte, self.motor.saida, destino)
            return self._arquivo(destino)
        except (ValueError, RuntimeError, OSError) as e:
            return self._erro(str(e)[:200])

    def _retorno_oauth(self, consulta: dict):
        destino = "/?aba=postagem"
        try:
            if "error" in consulta:
                raise ValueError("A conexão com o YouTube foi cancelada.")
            self.motor.postagem.conta.concluir_login(consulta.get("code", [""])[0], consulta.get("state", [""])[0])
            self.motor.postagem.aviso = ""
        except Exception as e:
            self.motor.postagem.aviso = str(e)
        if self.janela_propria:
            pagina = ("<!doctype html><html lang=pt-BR><meta charset=utf-8><title>Clipador</title><body style=\"margin:0;height:100vh;display:grid;place-content:center;"
                      "background:#0f1b20;color:#eef4f2;font:18px 'Segoe UI',sans-serif\">Pronto. Pode fechar esta aba e voltar para o Clipador.</body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(pagina)))
            self.end_headers()
            self.wfile.write(pagina)
            return
        self.send_response(303)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _retorno(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/oauth/retorno"

    def _conectar(self, dados: dict) -> dict:
        conta = self.motor.postagem.conta
        if dados.get("cliente"):
            conta.salvar_cliente(str(dados["cliente"]))
        url = conta.iniciar_login(self._retorno())
        if self.janela_propria:
            webbrowser.open(url)
            return {"url": url, "aberto": True}
        return {"url": url}

    def _acao(self, funcao):
        if not self._origem_local():
            return self._erro("Acesso permitido apenas neste computador.", 403)
        try:
            resposta = funcao(self._corpo())
            return self._json(resposta if resposta is not None else {"ok": True})
        except KeyError:
            return self._erro("Item não encontrado.", 404)
        except ErroYouTube as e:
            return self._erro(str(e))
        except (ValueError, TypeError) as e:
            return self._erro(str(e) or "Pedido inválido.")
        except Exception as e:
            return self._erro(f"Falha inesperada: {e}", 500)

    def do_POST(self):
        caminho = urlsplit(self.path).path
        if caminho == "/api/programa/erro":
            corpo = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 8000))
            try:
                d = json.loads(corpo or b"{}")
                print(f"[tela] {str(d.get('msg'))[:300]}\n{str(d.get('pilha'))[:1500]}", flush=True)
            except ValueError:
                pass
            return self._json({"ok": True})
        if caminho == "/api/programa/sinal":
            corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))  # a conexão continua aberta para o próximo pedido
            try:
                Painel.tela_visivel = bool(json.loads(corpo or b"{}").get("visivel"))
            except ValueError:
                Painel.tela_visivel = False
            Painel.ultimo_sinal = time.time()
            return self._json({"ok": True})
        if caminho == "/api/programa/mostrar" and type(self).ao_mostrar:
            return self._acao(lambda d: type(self).ao_mostrar())
        if caminho == "/api/programa" and type(self).definir_programa:
            return self._acao(lambda d: type(self).definir_programa(d))
        if caminho == "/api/encerrar" and self.ao_encerrar:
            return self._acao(lambda d: threading.Timer(0.3, type(self).ao_encerrar).start())
        if caminho == "/api/sons":
            return self._receber_som()
        if caminho == "/api/aprendizado/referencia":
            if not self._origem_local():
                return self._erro("Acesso permitido apenas neste computador.", 403)
            try:
                return self._json(self.motor.aprendizado.receber(parse_qs(urlsplit(self.path).query).get("nome", ["video.mp4"])[0], self.rfile, int(self.headers.get("Content-Length") or 0)))
            except ValueError as e:
                self.close_connection = True
                return self._erro(str(e))
        if caminho == "/api/aprendizado":
            return self._acao(lambda d: self.motor.aprendizado.definir(d))
        if m := re.fullmatch(r"/api/aprendizado/modelos/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.aprendizado.definir_modelo(m[1], d))
        if caminho == "/api/aprendizado/esquecer":
            return self._acao(lambda d: self.motor.aprendizado.esquecer())
        if caminho == "/api/montagens/estilo":
            return self._acao(lambda d: self.motor.montagens.pedir_estilo(d))
        if caminho == "/api/montagens":
            return self._acao(lambda d: self.motor.montagens.pedir(str(d.get("pasta") or ""), int(d.get("cenas", 4)), bool(d.get("emendado"))))
        if caminho == "/api/atualizacao/verificar":
            return self._acao(lambda d: self.motor.atualizacao.verificar())
        if caminho == "/api/atualizacao/abrir":
            return self._acao(lambda d: self.motor.atualizacao.abrir())
        if caminho == "/api/gravadas/envio":
            return self._receber_video()
        if caminho == "/api/gravadas/envio/conferir":
            return self._acao(lambda d: self.motor.gravadas.conferir_envio(d.get("nome", ""), d.get("tamanho", 0)))
        if caminho in ("/api/estudio/midia", "/api/estudio/fontes"):
            return self._receber_estudio(caminho)
        if caminho == "/api/estudio/luts":
            return self._receber_lut()
        if caminho == "/api/posts/gerar":
            return self._acao(lambda d: self.motor.posts.gerar(str(d.get("corte", "")), bool(d.get("refazer"))) and self.motor.posts.listar(str(d.get("pasta") or "")))
        if caminho == "/api/posts/minha":
            return self._acao(lambda d: self.motor.posts.minha_frase(str(d.get("corte", "")), str(d.get("texto", ""))))
        if caminho == "/api/posts/salvar":
            return self._acao(lambda d: self.motor.posts.salvar(str(d.get("corte", "")), str(d.get("frase", "")), d))
        if caminho == "/api/posts/previa":
            return self._baixar(lambda d: self._arte_post({**d, "previa": True}), "image/jpeg")
        if caminho == "/api/posts/arte":
            return self._baixar(lambda d: self._arte_post(d), "image/png")
        if caminho == "/api/posts/pacote":
            return self._baixar(lambda d: self.motor.posts.pacote(d.get("itens") or []), "application/zip")
        e = self.motor.estudio
        if caminho == "/api/estudio/congelar":
            return self._acao(lambda d: e.congelar(d["raiz"], d["rel"], float(d.get("t", 0))))
        if caminho == "/api/estudio/batidas":
            return self._acao(lambda d: e.batidas(d))
        if caminho == "/api/estudio/ouvir":
            return self._baixar(lambda d: e.ouvir(d), "audio/wav")
        if m := re.fullmatch(r"/api/estudio/(corte|longo)/([\w-]+)/xml", caminho):
            return self._baixar(lambda d: e.exportar_xml(m[1], m[2], d["projeto"]), "application/zip")
        if caminho == "/api/estudio/presets":
            return self._acao(lambda d: e.salvar_preset(d.get("nome", ""), d.get("global") or {}))
        if caminho == "/api/estudio/modelos-capa":
            return self._acao(lambda d: e.modelos.salvar(d.get("nome", ""), d["capa"]))
        if caminho == "/api/estudio/modelos-capa/aplicar":
            return self._acao(lambda d: capas.aplicar_modelo(d["modelo"], d["capa"]))
        if caminho == "/api/estudio/capa/quadro":
            return self._binario(lambda d: e.quadro_capa(d["capa"], float(d.get("escala", 1))))
        if re.fullmatch(r"/api/estudio/(corte|longo)/([\w-]+)/previa", caminho):
            return self._acao(lambda d: e.previa(d["projeto"], d.get("ini", 0), d.get("fim", 1), d.get("fps", 12), d.get("altura", 720)))
        if m := re.fullmatch(r"/api/estudio/(corte|longo)/([\w-]+)/quadro", caminho):
            return self._binario(lambda d: e.quadro(d["projeto"], float(d.get("t", 0)), int(d.get("altura", 960))))
        if m := re.fullmatch(r"/api/estudio/(corte|longo)/([\w-]+)/([\w/-]+)", caminho):
            t, i = m[1], m[2]
            acoes = {"salvar": lambda d: e.salvar(t, i, d["projeto"]), "restaurar": lambda d: e.restaurar_ia(t, i), "exportar": lambda d: e.pedir_exportacao(t, i, d["projeto"], d.get("altura", 1080)),
                     "exportar/cancelar": lambda d: e.cancelar_exportacao(t, i), "analisar": lambda d: {"sugestoes": e.analisar(d["projeto"])}, "aplicar": lambda d: e.aplicar_sugestoes(d["projeto"], d.get("sugestoes") or []),
                     "sugerir-sons": lambda d: {"sons": e.sugerir_sons(d["projeto"])}, "legendas": lambda d: e.pedir_trabalho(t, i, "legendas", {"projeto": d["projeto"]}),
                     "cena": lambda d: e.pedir_trabalho(t, i, "cena", {"projeto": d["projeto"], "cena": d.get("cena")}), "capa": lambda d: e.salvar_capa(t, i, d["capa"]),
                     "capa/exportar": lambda d: e.exportar_capa(t, i, d["capa"], d.get("largura", 1280)),
                     "traduzir": lambda d: e.traduzir(d["projeto"], d.get("idioma", "en")),
                     "rostos": lambda d: e.rostos(d["projeto"], d.get("item", ""), d.get("t", 0), d.get("modo", "um"))}
            if m[3] in acoes:
                return self._acao(acoes[m[3]])
        if caminho == "/api/canais":
            return self._acao(lambda d: {"id": self.motor.adicionar(str(d.get("link", "")), programar=bool(d.get("programar")))})
        postagem = self.motor.postagem
        if caminho == "/api/postagem/config":
            return self._acao(lambda d: postagem.salvar_config(d))
        if caminho == "/api/postagem/apagar":
            return self._acao(lambda d: postagem.apagar(d.get("ids")))
        if caminho == "/api/postagem/repetidos":
            return self._acao(lambda d: postagem.decidir_repetidos(str(d.get("acao", ""))))
        if caminho == "/api/postagem/pastas":
            return self._acao(lambda d: postagem.definir_pasta(str(d.get("pasta", "")), bool(d.get("ativa"))))
        if caminho == "/api/postagem/conta":
            return self._acao(self._conectar)
        if caminho == "/api/postagem/teste":
            return self._acao(lambda d: {"video": postagem.enviar_teste()})
        if caminho == "/api/postagem/agendados/voltar":
            return self._acao(lambda d: postagem.voltar_agendados())
        if m := re.fullmatch(r"/api/postagem/itens/([\w-]+)/(subir|descer|agendado|tentar|remover|voltar)", caminho):
            acoes = {"subir": lambda: postagem.mover(m[1], -1), "descer": lambda: postagem.mover(m[1], 1),
                     "agendado": lambda: postagem.marcar_agendado(m[1]), "tentar": lambda: postagem.tentar_de_novo(m[1]),
                     "remover": lambda: postagem.remover(m[1]), "voltar": lambda: postagem.voltar_para_fila(m[1])}
            return self._acao(lambda d: acoes[m[2]]())
        if caminho == "/api/config":
            return self._acao(lambda d: self.motor.salvar_config(d))
        if caminho == "/api/longos/auto":
            return self._acao(lambda d: self.motor.longos.configurar_auto(d))
        if caminho == "/api/longos":
            return self._acao(lambda d: self.motor.longos.criar(str(d.get("sessao", "")), int(d.get("minutos", 10))))
        if m := re.fullmatch(r"/api/longos/([\w-]+)/enviar", caminho):
            return self._acao(lambda d: self.motor.longos.enviar(m[1], float(d["quando"]) if d.get("quando") else None))
        if caminho == "/api/gravadas":
            return self._acao(lambda d: self.motor.gravadas.adicionar(d))
        if m := re.fullmatch(r"/api/gravadas/([\w-]+)/cancelar", caminho):
            return self._acao(lambda d: self.motor.gravadas.cancelar(m[1]))
        if m := re.fullmatch(r"/api/canais/([\w-]+)/cortar", caminho):
            return self._acao(lambda d: self.motor.cortar_agora(m[1]))
        if m := re.fullmatch(r"/api/canais/([\w-]+)/camera", caminho):
            return self._acao(lambda d: self.motor.definir_camera(m[1], d))
        return self._erro("Página não encontrada.", 404)

    def do_PATCH(self):
        if m := re.fullmatch(r"/api/cortes/([\w-]+)", urlsplit(self.path).path):
            return self._acao(lambda d: self.motor.atualizar_corte(m[1], d))
        if m := re.fullmatch(r"/api/postagem/itens/([\w-]+)", urlsplit(self.path).path):
            return self._acao(lambda d: self.motor.postagem.editar(m[1], d))
        if m := re.fullmatch(r"/api/longos/([\w-]+)", urlsplit(self.path).path):
            return self._acao(lambda d: self.motor.longos.editar(m[1], d))
        return self._erro("Página não encontrada.", 404)

    def do_DELETE(self):
        caminho = urlsplit(self.path).path
        if caminho == "/api/postagem/conta":
            return self._acao(lambda d: self.motor.postagem.conta.desconectar())
        if m := re.fullmatch(r"/api/canais/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.remover(m[1]))
        if m := re.fullmatch(r"/api/sons/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.biblioteca.remover(m[1]))
        if m := re.fullmatch(r"/api/aprendizado/modelos/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.aprendizado.remover_modelo(m[1]))
        if m := re.fullmatch(r"/api/aprendizado/referencias/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.aprendizado.remover(m[1]))
        if m := re.fullmatch(r"/api/estudio/presets/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.estudio.apagar_preset(m[1]))
        if m := re.fullmatch(r"/api/estudio/modelos-capa/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.estudio.modelos.apagar(m[1]))
        if m := re.fullmatch(r"/api/longos/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.longos.excluir(m[1]))
        if m := re.fullmatch(r"/api/gravadas/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.gravadas.remover(m[1]))
        if m := re.fullmatch(r"/api/cortes/([\w-]+)", caminho):
            return self._acao(lambda d: self.motor.excluir_corte(m[1]))
        return self._erro("Página não encontrada.", 404)


class Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """Fechar a aba durante um vídeo é normal e não deve aparecer como erro."""
        import sys

        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


def iniciar_servidor(motor: Motor, porta: int) -> tuple[ThreadingHTTPServer, int]:
    Painel.motor = motor
    for tentativa in range(porta, porta + 20):
        try:
            return Servidor(("127.0.0.1", tentativa), Painel), tentativa
        except OSError:
            continue
    raise OSError("Nenhuma porta disponível para abrir o painel.")
