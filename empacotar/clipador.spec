# Receita do programa. Use o criar-exe.bat em vez de rodar este arquivo direto.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

AQUI = Path(SPECPATH)
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ))
from nucleo.versao import VERSAO

datas = [(str(RAIZ / p), p) for p in ("web", "fontes", "modelos")] + [(str(AQUI / "clipador.png"), "recursos")]
binaries, hidden = [], ["nucleo.motor", "nucleo.painel"]
for pacote in ("faster_whisper", "ctranslate2", "tokenizers", "onnxruntime", "av", "curl_cffi", "yt_dlp", "streamlink", "streamlink_cli", "websockets", "certifi", "webview", "clr_loader", "pythonnet", "pystray"):
    try:
        d, b, h = collect_all(pacote)
        datas += d; binaries += b; hidden += h
    except Exception as erro:
        print(f"Aviso: {pacote}: {erro}")

pasta_ffmpeg = Path(os.environ["CLIPADOR_FFMPEG"])
binaries += [(str(p), "ffmpeg") for p in pasta_ffmpeg.iterdir() if p.stem in ("ffmpeg", "ffprobe") and p.suffix in ("", ".exe")]
fora = ["tkinter", "matplotlib", "pytest", "IPython", "PyQt5", "PyQt6", "PySide2", "PySide6", "torch", "tensorflow", "pandas", "scipy.spatial.tests"]

principal = Analysis([str(RAIZ / "programa.py")], pathex=[str(RAIZ)], binaries=binaries, datas=datas, hiddenimports=hidden, excludes=fora)
pacote_principal = PYZ(principal.pure)

apoio = Analysis([str(AQUI / "apoio_streamlink.py")], pathex=[str(RAIZ)], datas=collect_all("streamlink")[0], hiddenimports=collect_all("streamlink")[2], excludes=fora)
pacote_apoio = PYZ(apoio.pure)

versao_windows = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo

    numeros = tuple(int(n) for n in VERSAO.split(".")) + (0,)
    versao_windows = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numeros, prodvers=numeros, mask=0x3F, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("041604B0", [
            StringStruct("CompanyName", "Clipador"), StringStruct("FileDescription", "Clipador"), StringStruct("FileVersion", VERSAO),
            StringStruct("InternalName", "Clipador"), StringStruct("LegalCopyright", "Clipador"), StringStruct("OriginalFilename", "Clipador.exe"),
            StringStruct("ProductName", "Clipador"), StringStruct("ProductVersion", VERSAO)])]), VarFileInfo([VarStruct("Translation", [0x0416, 1200])])],
    )

programa = EXE(pacote_principal, principal.scripts, [("X utf8", None, "OPTION")], exclude_binaries=True, name="Clipador", console=False, upx=False,
               icon=str(AQUI / "clipador.ico"), version=versao_windows)
gravador = EXE(pacote_apoio, apoio.scripts, [("X utf8", None, "OPTION")], exclude_binaries=True, name="streamlink", console=True, upx=False, icon=str(AQUI / "clipador.ico"))
COLLECT(programa, gravador, principal.binaries, principal.datas, apoio.binaries, apoio.datas, name="Clipador", upx=False)
