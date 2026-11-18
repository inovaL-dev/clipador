#!/usr/bin/env python3
"""Cria o programa do Clipador: Clipador.exe, ícone, testes e instalador."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
AMBIENTE = RAIZ / ".venv-exe"
TRABALHO = RAIZ / "build_exe"
DIST = TRABALHO / "programa"
SAIDA = RAIZ / "instalador"
WINDOWS = os.name == "nt"
PYTHON = AMBIENTE / ("Scripts/python.exe" if WINDOWS else "bin/python")
FERRAMENTAS = RAIZ / ".ferramentas" / "inno"
INNO_PACOTE = "https://registry.npmjs.org/innosetup-compiler/-/innosetup-compiler-6.3.1.tgz"
INNO_SHA512 = "Qynw7Xjv7ZN/beBvS7Kt+QL50Q/Zbf7cJDHZmxmwNbxqgZEWCZ+5tggC6naF4ij/9PqRfpvDP1ecZLFwusu6Lw=="
FFMPEG_LINKS = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")


class Parar(Exception):
    pass


def etapa(n: int, texto: str) -> None:
    print(f"\n[{n}/6] {texto}", flush=True)


def rodar(*cmd, **opcoes) -> None:
    if subprocess.run([str(c) for c in cmd], **opcoes).returncode:
        raise Parar("Esta etapa falhou. Veja a mensagem logo acima.")


def preparar_ambiente() -> None:
    marca = AMBIENTE / "instalado-v1.ok"
    pedidos = (RAIZ / "requirements.txt").read_bytes() + (AQUI / "requisitos-exe.txt").read_bytes()
    if marca.exists() and marca.read_bytes() == pedidos:
        print("Componentes já instalados.")
        return
    venv.EnvBuilder(with_pip=True, clear=AMBIENTE.exists()).create(AMBIENTE)
    rodar(PYTHON, "-m", "pip", "install", "--upgrade", "pip")
    rodar(PYTHON, "-m", "pip", "install", "-r", RAIZ / "requirements.txt", "-r", AQUI / "requisitos-exe.txt")
    marca.write_bytes(pedidos)


def achar_ffmpeg() -> Path:
    nome = "ffmpeg.exe" if WINDOWS else "ffmpeg"
    local = RAIZ / "ffmpeg" / "bin"
    if (local / nome).exists() and (local / nome.replace("ffmpeg", "ffprobe")).exists():
        print("Usando o FFmpeg que já está na pasta.")
        return local
    if not WINDOWS:
        achado = shutil.which("ffmpeg")
        if achado and shutil.which("ffprobe"):
            pasta = Path(tempfile.mkdtemp(prefix="ffmpeg_exe_"))
            shutil.copy(achado, pasta); shutil.copy(shutil.which("ffprobe"), pasta)
            return pasta
        raise Parar("Instale o FFmpeg antes de continuar.")
    local.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        arquivo = Path(tmp) / "ffmpeg.zip"
        for link in FFMPEG_LINKS:
            try:
                print(f"Baixando o FFmpeg de {link.split('/')[2]}...", flush=True)
                urllib.request.urlretrieve(link, arquivo)
                with zipfile.ZipFile(arquivo) as z:
                    for item in z.namelist():
                        if Path(item).name in ("ffmpeg.exe", "ffprobe.exe"):
                            (local / Path(item).name).write_bytes(z.read(item))
                if (local / "ffmpeg.exe").exists() and (local / "ffprobe.exe").exists():
                    return local
            except OSError as e:
                print(f"Não consegui baixar: {e}")
    raise Parar("Não consegui baixar o FFmpeg. Confira a internet e abra o criar-exe.bat de novo.")


def empacotar(ffmpeg: Path) -> Path:
    shutil.rmtree(RAIZ / "programa", ignore_errors=True)  # pasta usada pela versão anterior do criador
    shutil.rmtree(TRABALHO, ignore_errors=True)
    rodar(PYTHON, "-m", "PyInstaller", AQUI / "clipador.spec", "--noconfirm", "--clean", "--log-level", "WARN", "--distpath", DIST, "--workpath", TRABALHO / "pacote",
          env={**os.environ, "CLIPADOR_FFMPEG": str(ffmpeg), "PYTHONUTF8": "1"}, cwd=RAIZ)
    return DIST / "Clipador" / ("Clipador.exe" if WINDOWS else "Clipador")


def testar(programa: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        relatorio = Path(tmp) / "diagnostico.json"
        ambiente = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
        subprocess.run([str(programa), "--diagnostico", str(relatorio)], env=ambiente, timeout=300)
        if not relatorio.exists():
            raise Parar("O programa foi criado, mas não abriu no teste. Se o antivírus avisou algo, libere a pasta e tente de novo.")
        itens = json.loads(relatorio.read_text(encoding="utf-8"))
    janela = [k for k, v in itens.items() if v.startswith("FALHOU") and k.startswith("janela")]
    if janela:
        print("Aviso: a janela própria não ficou disponível. O painel vai abrir no navegador.")
    falhas = {k: v for k, v in itens.items() if v.startswith("FALHOU") and k not in janela}
    print(f"{len(itens) - len(falhas)} de {len(itens)} itens conferidos.")
    if falhas:
        for k, v in falhas.items():
            print(f"  {k}: {v}")
        raise Parar("O programa foi criado com partes faltando.")


def ligar_dados() -> None:
    """O programa continua usando os cortes, a fila e o canal que já existem nesta pasta."""
    if not (RAIZ / "dados").is_dir():
        print("Nenhum dado anterior nesta pasta.")
        return
    base = os.environ.get("LOCALAPPDATA")
    base = Path(base) / "Clipador" if base else Path.home() / ".local" / "share" / "Clipador"
    arquivo = base / "pastas.json"
    if arquivo.exists():
        print("O programa já está ligado às suas pastas.")
        return
    base.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps({"dados": str(RAIZ / "dados"), "saida": str(RAIZ / "cortes")}, ensure_ascii=False), encoding="utf-8")
    print(f"Seus cortes e o canal conectado continuam em: {RAIZ}")


def achar_inno() -> Path | None:
    achado = shutil.which("ISCC")
    locais = [achado] if achado else []
    locais.append(FERRAMENTAS / "ISCC.exe")
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA") and Path(os.environ["LOCALAPPDATA"]) / "Programs"):
        if base:
            locais += [Path(base) / "Inno Setup 6" / "ISCC.exe"]
    return next((Path(p) for p in locais if p and Path(p).exists()), None)


def baixar_inno() -> Path:
    """Baixa o compilador só para esta pasta, sem instalar nada no Windows, e confere se o arquivo veio íntegro."""
    print("Baixando o Inno Setup...", flush=True)
    pedido = urllib.request.Request(INNO_PACOTE, headers={"User-Agent": "Clipador"})
    with urllib.request.urlopen(pedido, timeout=180) as r:
        dados = r.read()
    if base64.b64encode(hashlib.sha512(dados).digest()).decode() != INNO_SHA512:
        raise OSError("o arquivo baixado veio diferente do esperado")
    shutil.rmtree(FERRAMENTAS, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as pacote:
        for item in pacote.getmembers():
            partes = Path(item.name).parts
            if item.isfile() and partes[:2] == ("package", "bin") and ".." not in partes:
                alvo = FERRAMENTAS.joinpath(*partes[2:])
                alvo.parent.mkdir(parents=True, exist_ok=True)
                alvo.write_bytes(pacote.extractfile(item).read())
    return FERRAMENTAS / "ISCC.exe"


def instalar_inno() -> Path | None:
    print("O instalador é montado com o Inno Setup, um programa gratuito (licença: https://jrsoftware.org/files/is/license.txt).")
    if not os.environ.get("CI") and input("Baixar o Inno Setup agora? (S/N) [S]: ").strip().lower().startswith("n"):
        return None
    try:
        return baixar_inno()
    except OSError as e:
        print(f"Não consegui baixar: {e}")
    if shutil.which("winget"):
        subprocess.run(["winget", "install", "--id", "JRSoftware.InnoSetup", "-e", "--scope", "user"])
    return achar_inno()


def criar_instalador(versao: str) -> Path | None:
    if not WINDOWS:
        print("O instalador só pode ser criado no Windows.")
        return None
    inno = achar_inno() or instalar_inno()
    if not inno:
        raise Parar("Sem o Inno Setup o instalador não pode ser criado. Instale em https://jrsoftware.org/isdl.php e abra o criar-exe.bat de novo.")
    shutil.rmtree(SAIDA, ignore_errors=True)
    SAIDA.mkdir(parents=True)
    rodar(inno, "/Qp", f"/DVersao={versao}", f"/DOrigem={DIST / 'Clipador'}", f"/DDestino={SAIDA}", AQUI / "instalador.iss")
    return SAIDA / f"Clipador-Instalador-{versao}.exe"


def programa_atual(programa: Path) -> bool:
    """Evita montar tudo de novo quando nada mudou desde a última vez."""
    if not programa.exists():
        return False
    fontes = [RAIZ / "programa.py", RAIZ / "requirements.txt", *[AQUI / n for n in ("clipador.spec", "apoio_streamlink.py", "requisitos-exe.txt", "clipador.ico", "clipador.png")]]
    for pasta in ("nucleo", "web", "fontes", "modelos"):
        fontes += [a for a in (RAIZ / pasta).rglob("*") if a.is_file() and a.suffix != ".pyc"]
    return max(a.stat().st_mtime for a in fontes) <= programa.stat().st_mtime


def main() -> int:
    if not (3, 10) <= sys.version_info[:2] <= (3, 13):
        raise Parar("Use o Python 3.12. Baixe em https://www.python.org/downloads/release/python-3128/")
    versao = re.search(r'VERSAO = "([^"]+)"', (RAIZ / "nucleo" / "versao.py").read_text(encoding="utf-8"))[1]
    print(f"Criando o Clipador {versao}. A primeira vez pode levar de 10 a 20 minutos.")
    programa = DIST / "Clipador" / ("Clipador.exe" if WINDOWS else "Clipador")
    if programa_atual(programa):
        print("\nO programa já está montado. Indo direto para o instalador.")
    else:
        etapa(1, "Instalando os componentes"); preparar_ambiente()
        etapa(2, "Preparando o FFmpeg"); ffmpeg = achar_ffmpeg()
        etapa(3, "Montando o programa"); programa = empacotar(ffmpeg)
    etapa(4, "Testando o programa"); testar(programa)
    etapa(5, "Ligando seus dados"); ligar_dados()
    etapa(6, "Criando o instalador"); instalador = criar_instalador(versao)
    if instalador:
        shutil.rmtree(TRABALHO, ignore_errors=True)
        print(f"\nPronto! Seu instalador está em:\n{instalador}")
        if not os.environ.get("CI"):
            subprocess.run(["explorer", "/select,", str(instalador)])
    else:
        print(f"\nPrograma de teste: {programa}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Parar as e:
        print(f"\nNão foi possível terminar: {e}")
        sys.exit(1)
