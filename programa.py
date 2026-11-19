#!/usr/bin/env python3
"""Abre o Clipador como um programa, com janela própria e sem precisar do Python instalado."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

NOME = "Clipador"
EMPACOTADO = bool(getattr(sys, "frozen", False))
RAIZ = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
TELA_INICIAL = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Clipador</title><style>
html,body{height:100%;margin:0}body{display:grid;place-content:center;justify-items:center;gap:26px;background:radial-gradient(640px 380px at 50% 45%,#16292f,#0a1316 72%);color:#eef4f2;font:700 28px "Segoe UI",sans-serif;letter-spacing:-.02em}
.l{position:relative;display:flex;gap:4px;width:380px;height:34px}.l i{background:#24404a;border-radius:4px;animation:c 1.5s ease-in-out infinite}.l b{position:absolute;top:-10px;bottom:-10px;left:0;width:2px;background:#f2b544;box-shadow:0 0 18px 2px #f2b54499;animation:a 1.5s cubic-bezier(.5,0,.5,1) infinite}
.m{display:flex;align-items:center;gap:10px}small{margin-top:-14px;color:#a6babc;font:400 15px "Segoe UI",sans-serif;letter-spacing:0}@keyframes a{to{left:100%}}@keyframes c{35%{background:#5ad1b3}70%{background:#24404a}}
</style><body><div class="l"><i style="flex:3;animation-delay:0.00s"></i><i style="flex:5;animation-delay:0.11s"></i><i style="flex:2;animation-delay:0.22s"></i><i style="flex:6;animation-delay:0.33s"></i><i style="flex:3;animation-delay:0.44s"></i><i style="flex:4;animation-delay:0.55s"></i><i style="flex:2;animation-delay:0.66s"></i><i style="flex:5;animation-delay:0.77s"></i><b></b></div><div class="m"><svg width="32" height="32" viewBox="0 0 24 24" fill="#f2b544"><path d="M5 3h14l-7 8z"/><rect x="10.75" y="9" width="2.5" height="13" rx="1.25"/></svg>Clipador</div><small>Preparando o estúdio…</small></body></html>"""


def pasta_do_programa() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / NOME if base else Path.home() / ".local" / "share" / NOME


def pastas_de_trabalho(base: Path) -> tuple[Path, Path]:
    """Usa as pastas ligadas na criação do programa ou as pastas padrão do usuário."""
    dados, saida = base / "dados", Path.home() / "Videos" / NOME
    try:
        escolhidas = json.loads((base / "pastas.json").read_text(encoding="utf-8"))
        dados, saida = Path(escolhidas["dados"]), Path(escolhidas["saida"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dados, saida


def preparar_registro(base: Path) -> None:
    """Sem console, as mensagens de erro ficam guardadas em um arquivo."""
    base.mkdir(parents=True, exist_ok=True)
    registro = base / "registro.txt"
    try:
        if registro.exists() and registro.stat().st_size > 2_000_000:
            registro.replace(base / "registro-anterior.txt")
    except OSError:
        pass
    arquivo = open(registro, "a", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = sys.stderr = arquivo
    print(f"\n--- {time.strftime('%d/%m/%Y %H:%M:%S')} ---")


def preparar_ambiente() -> None:
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    pastas = [RAIZ / "ffmpeg", Path(__file__).resolve().parent / "ffmpeg" / "bin"]
    if EMPACOTADO:
        pastas.insert(0, Path(sys.executable).resolve().parent)  # traz o streamlink que vem junto
    os.environ["PATH"] = os.pathsep.join([*(str(p) for p in pastas if p.exists()), os.environ.get("PATH", "")])


def mostrar_erro(texto: str) -> None:
    print(texto)
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, texto, NOME, 0x10)


def identificar_no_windows() -> None:
    """Agrupa a janela com o ícone certo na barra de tarefas e avisa o instalador que o programa está aberto."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Clipador.Programa")
        ctypes.windll.kernel32.CreateMutexW(None, False, "ClipadorProgramaAberto")
    except Exception:
        traceback.print_exc()


def barra_escura() -> None:
    """Deixa a barra de título da janela escura, combinando com o programa."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
        user32.FindWindowW.restype = wintypes.HWND
        for _ in range(40):
            janela = user32.FindWindowW(None, NOME)
            if janela:
                for atributo, valor in ((20, 1), (19, 1), (35, 0x0018150B)):  # modo escuro e cor da barra
                    v = ctypes.c_int(valor)
                    dwm.DwmSetWindowAttribute(wintypes.HWND(janela), atributo, ctypes.byref(v), ctypes.sizeof(v))
                return
            time.sleep(.25)
    except Exception:
        traceback.print_exc()


def trazer_para_frente(porta: int | None) -> None:
    if porta:
        try:
            pedido = urllib.request.Request(f"http://127.0.0.1:{porta}/api/programa/mostrar", data=b"{}", method="POST",
                                            headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{porta}"})
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(pedido, timeout=4).read()
            return
        except OSError:
            pass
    if os.name == "nt":
        import ctypes

        janela = ctypes.windll.user32.FindWindowW(None, NOME)
        if janela:
            ctypes.windll.user32.ShowWindow(janela, 9)
            ctypes.windll.user32.SetForegroundWindow(janela)
            return
    if porta:
        webbrowser.open(f"http://127.0.0.1:{porta}")


class Preferencias:
    """Guarda as opções do programa. No Windows, o instalador também escreve aqui."""
    CHAVE = r"Software\Clipador"
    RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self, base: Path):
        self.arquivo = base / "preferencias.json"

    def segundo_plano(self) -> bool:
        if os.name == "nt":
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.CHAVE) as k:
                    return bool(winreg.QueryValueEx(k, "SegundoPlano")[0])
            except OSError:
                return True
        try:
            return bool(json.loads(self.arquivo.read_text(encoding="utf-8")).get("segundo_plano", True))
        except (OSError, ValueError):
            return True

    def definir_segundo_plano(self, ativo: bool) -> None:
        if os.name == "nt":
            import winreg

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.CHAVE) as k:
                winreg.SetValueEx(k, "SegundoPlano", 0, winreg.REG_DWORD, int(ativo))
        else:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.write_text(json.dumps({"segundo_plano": ativo}), encoding="utf-8")

    def com_windows(self) -> bool:
        if os.name != "nt":
            return False
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN) as k:
                winreg.QueryValueEx(k, NOME)
                return True
        except OSError:
            return False

    def definir_com_windows(self, ativo: bool) -> None:
        if os.name != "nt" or not EMPACOTADO:
            return
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.RUN) as k:
            if ativo:
                winreg.SetValueEx(k, NOME, 0, winreg.REG_SZ, f'"{Path(sys.executable).resolve()}" --segundo-plano')
            else:
                try:
                    winreg.DeleteValue(k, NOME)
                except OSError:
                    pass


def criar_bandeja(prefs: Preferencias, mostrar, sair, mudou):
    """Ícone perto do relógio, para o Clipador seguir trabalhando com a janela fechada."""
    try:
        import pystray
        from PIL import Image

        imagem = Image.open(RAIZ / "recursos" / "clipador.png" if (RAIZ / "recursos").exists() else RAIZ / "empacotar" / "clipador.png")

        def trocar_fundo(icone, item) -> None:
            prefs.definir_segundo_plano(not prefs.segundo_plano()); mudou()

        def trocar_windows(icone, item) -> None:
            prefs.definir_com_windows(not prefs.com_windows())

        menu = pystray.Menu(pystray.MenuItem("Abrir o Clipador", lambda: mostrar(), default=True), pystray.Menu.SEPARATOR,
                            pystray.MenuItem("Continuar em segundo plano ao fechar", trocar_fundo, checked=lambda _: prefs.segundo_plano()),
                            pystray.MenuItem("Abrir junto com o Windows", trocar_windows, checked=lambda _: prefs.com_windows(), visible=os.name == "nt" and EMPACOTADO),
                            pystray.Menu.SEPARATOR, pystray.MenuItem("Fechar o Clipador", lambda: sair()))
        icone = pystray.Icon(NOME, imagem, NOME, menu)
        icone.run_detached()
        return icone
    except Exception:
        traceback.print_exc()
        return None


def diagnostico(destino: Path) -> int:
    """Confere se tudo veio junto. O criador do .exe usa isto antes de entregar o programa."""
    resultado: dict[str, str] = {}

    def conferir(nome: str, funcao) -> None:
        try:
            resultado[nome] = str(funcao() or "ok")
        except BaseException as e:
            resultado[nome] = f"FALHOU: {type(e).__name__}: {e}"

    def rodar(*cmd: str) -> str:
        opcoes = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **opcoes)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip()[-200:])
        return (r.stdout.strip().splitlines() or ["ok"])[0][:70]

    def modelo_rosto() -> str:
        import onnxruntime as ort

        ort.set_default_logger_severity(3)
        return ort.InferenceSession(str(RAIZ / "modelos" / "centerface.onnx"), providers=["CPUExecutionProvider"]).get_providers()[0]

    def texto_utf8() -> None:
        if not sys.flags.utf8_mode:
            raise RuntimeError("modo UTF-8 desligado")

    conferir("modo utf-8", texto_utf8)
    for pasta in ("web/index.html", "web/estudio.js", "web/acabamento.js", "fontes/Anton.ttf", "recursos/clipador.png", "fontes/Poppins-Bold.ttf", "modelos/centerface.onnx", "modelos/expressao.onnx"):
        conferir(pasta, lambda p=pasta: (RAIZ / p).stat().st_size)
    conferir("ffmpeg", lambda: rodar("ffmpeg", "-version"))
    conferir("ffprobe", lambda: rodar("ffprobe", "-version"))
    conferir("streamlink", lambda: rodar("streamlink", "--version"))
    for site in ("https://www.twitch.tv/canal", "https://kick.com/canal", "https://www.youtube.com/@canal/live"):
        conferir(f"streamlink {site.split('/')[2]}", lambda s=site: rodar("streamlink", "--can-handle-url", s))
    for modulo in ("numpy", "cv2", "av", "ctranslate2", "faster_whisper", "tokenizers", "curl_cffi", "websockets", "yt_dlp", "PIL", "nucleo.motor", "nucleo.painel", "nucleo.estudio"):
        conferir(modulo, lambda m=modulo: __import__(m) and None)
    conferir("detector de rosto", modelo_rosto)
    conferir("extratores de vídeo", lambda: __import__("yt_dlp.extractor", fromlist=["gen_extractor_classes"]) and len(list(__import__("yt_dlp.extractor", fromlist=["gen_extractor_classes"]).gen_extractor_classes())))
    if os.name == "nt":
        conferir("janela própria", lambda: __import__("webview") and None)
        conferir("janela própria (.NET)", lambda: __import__("clr") and None)
        conferir("janela: ícone perto do relógio", lambda: __import__("pystray") and None)
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if any(v.startswith("FALHOU") for v in resultado.values()) else 0


def vigiar_janela(sinal, recarregar, oculta, parar: threading.Event, limite: float = 180.0, pausa: float = 5.0, visivel=lambda: True) -> None:
    """Se a tela parar de responder estando à vista, abre o painel de novo sem interromper as gravações.

    Uma tela em segundo plano ou minimizada avisa que saiu de vista e nunca é recarregada."""
    tentativas, desde = 0, time.time()
    while not parar.wait(pausa):
        ultimo = sinal()
        if not ultimo or oculta() or not visivel():
            desde = time.time()
            continue
        if ultimo > desde:
            desde, tentativas = ultimo, 0
        if time.time() - desde >= limite and tentativas < 3:
            tentativas += 1
            desde = time.time()
            try:
                recarregar()
            except Exception:
                traceback.print_exc()


def main() -> int:
    if sys.stdout is None:  # programas sem console não têm saída de texto
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if len(sys.argv) >= 4 and sys.argv[1] == "--medir-referencia":
        preparar_ambiente()
        from nucleo.medir_referencia import principal

        return principal(*sys.argv[2:6])
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("links", nargs="*")
    ap.add_argument("--porta", type=int, default=8420)
    ap.add_argument("--dados")
    ap.add_argument("--saida")
    ap.add_argument("--modelo")
    ap.add_argument("--sem-janela", action="store_true")
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--segundo-plano", action="store_true")
    ap.add_argument("--diagnostico")
    args, _ = ap.parse_known_args()

    preparar_ambiente()
    if args.diagnostico:
        return diagnostico(Path(args.diagnostico))
    base = pasta_do_programa()
    if EMPACOTADO:
        preparar_registro(base)
    identificar_no_windows()
    padrao_dados, padrao_saida = pastas_de_trabalho(base)
    dados, saida = Path(args.dados or padrao_dados), Path(args.saida or padrao_saida)

    from nucleo.instancia import Trava

    trava = Trava(dados)
    if not trava.pegar():
        if not args.segundo_plano:
            trazer_para_frente(trava.porta_aberta())
        return 0

    estado: dict = {"oculta": args.segundo_plano, "motor": None, "servidor": None, "janela": None, "bandeja": None, "endereco": None, "saindo": False}
    parar = threading.Event()
    trava_inicio = threading.Lock()
    prefs = Preferencias(base)

    def encerrar_pedido() -> None:
        estado["saindo"] = True
        parar.set()
        if estado["bandeja"]:
            estado["bandeja"].stop()
        if estado["janela"]:
            estado["janela"].confirm_close = False
            estado["janela"].destroy()

    def mostrar() -> None:
        if estado["janela"]:
            estado["oculta"] = False
            estado["janela"].show(); estado["janela"].restore()
        elif estado["endereco"]:
            webbrowser.open(estado["endereco"])

    def ajustar_fechamento() -> None:
        if estado["janela"]:
            estado["janela"].confirm_close = not (estado["bandeja"] and prefs.segundo_plano())

    def ao_fechar():
        if estado["saindo"] or not estado["bandeja"] or not prefs.segundo_plano():
            return True
        estado["oculta"] = True
        threading.Thread(target=estado["janela"].hide, daemon=True).start()
        try:
            estado["bandeja"].notify("O Clipador continua funcionando. Para fechar de vez, use o ícone perto do relógio.", NOME)
        except Exception:
            pass
        return False

    def info_programa() -> dict:
        return {"disponivel": bool(estado["bandeja"]), "segundo_plano": prefs.segundo_plano(), "com_windows": prefs.com_windows(), "pode_iniciar_windows": os.name == "nt" and EMPACOTADO}

    def definir_programa(d: dict) -> dict:
        if "segundo_plano" in d:
            prefs.definir_segundo_plano(bool(d["segundo_plano"])); ajustar_fechamento()
        if "com_windows" in d:
            prefs.definir_com_windows(bool(d["com_windows"]))
        return info_programa()

    estado["bandeja"] = None if args.sem_janela and not args.segundo_plano else criar_bandeja(prefs, mostrar, encerrar_pedido, ajustar_fechamento)

    def iniciar() -> None:
        with trava_inicio:
            if estado["motor"]:
                return
            try:
                from nucleo.motor import Motor
                from nucleo.painel import Painel, iniciar_servidor

                Painel.ao_encerrar = encerrar_pedido
                Painel.ao_mostrar = mostrar
                Painel.info_programa = info_programa
                Painel.definir_programa = definir_programa
                Painel.janela_propria = estado["janela"] is not None
                motor = Motor(dados, saida, args.modelo)
                for link in args.links:
                    try:
                        motor.adicionar(link)
                    except ValueError as e:
                        print(e)
                servidor, porta = iniciar_servidor(motor, args.porta)
                estado.update(motor=motor, servidor=servidor)
                threading.Thread(target=servidor.serve_forever, daemon=True).start()
                trava.guardar_porta(porta)
                endereco = estado["endereco"] = f"http://127.0.0.1:{porta}"
                print(f"Painel aberto em {endereco}", flush=True)
                if estado["janela"]:
                    threading.Thread(target=barra_escura, daemon=True).start()
                    estado["janela"].load_url(f"{endereco}/?janela=1")
                    threading.Thread(target=vigiar_janela, args=(lambda: Painel.ultimo_sinal, lambda: estado["janela"].load_url(f"{endereco}/?janela=1"), lambda: estado["oculta"], parar, 180.0, 5.0, lambda: Painel.tela_visivel), daemon=True).start()
                elif not args.sem_navegador and not args.segundo_plano:
                    webbrowser.open(endereco)
            except Exception:
                traceback.print_exc()
                mostrar_erro(f"O Clipador não conseguiu abrir.\n\nDetalhes em: {base / 'registro.txt'}")
                os._exit(1)

    abriu_janela = False
    if not args.sem_janela:
        try:
            import webview

            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
            estado["janela"] = webview.create_window(NOME, html=TELA_INICIAL, width=1440, height=900, min_size=(1000, 660),
                                                     confirm_close=True, background_color="#0F1B20", text_select=True, hidden=args.segundo_plano)
            estado["janela"].events.closing += ao_fechar
            ajustar_fechamento()
            webview.start(iniciar, gui="edgechromium" if os.name == "nt" else None, private_mode=False, storage_path=str(base / "janela"),
                          localization={"global.quitConfirmation": "Fechar o Clipador? As lives que estão sendo gravadas vão parar."})
            abriu_janela = True
        except Exception:
            traceback.print_exc()  # sem o componente da janela, o painel abre no navegador
            estado["janela"] = None

    if not abriu_janela:
        import signal

        signal.signal(signal.SIGINT, lambda *_: parar.set())
        signal.signal(signal.SIGTERM, lambda *_: parar.set())
        iniciar()
        while not parar.wait(0.5):
            pass

    threading.Timer(25, lambda: os._exit(0)).start()  # uma gravação presa não pode segurar o programa aberto
    if estado["servidor"]:
        estado["servidor"].shutdown()
    if estado["motor"]:
        estado["motor"].encerrar()
    os._exit(0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
