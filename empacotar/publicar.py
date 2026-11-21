"""Publica o projeto em um repositório privado do GitHub e pede a criação do instalador."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FERRAMENTAS = RAIZ / ".ferramentas" / "github"
REPOSITORIO = os.environ.get("CLIPADOR_REPO", "clipador")
DESCRICAO = "Cortes de lives prontos enquanto a transmissão acontece: Shorts, vídeos longos, editor completo e agenda para o YouTube."
TOPICOS = ("clips", "live-streaming", "video-editor", "youtube-shorts", "whisper", "ffmpeg", "kick", "twitch", "python", "windows")
PROIBIDOS = re.compile(r"(^|/)(dados|cortes)/|youtube_(cliente|token)\.json$|client_secret[^/]*\.json$|credenciais[^/]*\.json$|(^|/)\.env", re.I)
SEGREDOS = re.compile(rb"GOCSPX-[\w-]{10,}|ya29\.[\w-]{20,}|AIza[\w-]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


class Parar(Exception):
    pass


def baixar_json(url: str) -> dict:
    pedido = urllib.request.Request(url, headers={"User-Agent": "Clipador", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(pedido, timeout=40) as r:
        return json.load(r)


def baixar_ferramenta(repo: str, padrao: str, pasta: Path) -> None:
    """Baixa a versão oficial e confere a assinatura publicada pelo GitHub."""
    versao = baixar_json(f"https://api.github.com/repos/{repo}/releases/latest")
    item = next((a for a in versao["assets"] if re.fullmatch(padrao, a["name"])), None)
    if not item:
        raise Parar(f"Não encontrei o download de {repo}.")
    print(f"Baixando {item['name']}")
    with tempfile.TemporaryDirectory() as tmp:
        arquivo = Path(tmp) / item["name"]
        urllib.request.urlretrieve(item["browser_download_url"], arquivo)
        esperado = str(item.get("digest") or "").removeprefix("sha256:")
        if not esperado:
            raise Parar(f"O download de {repo} veio sem assinatura. Tente de novo mais tarde.")
        if hashlib.sha256(arquivo.read_bytes()).hexdigest() != esperado:
            raise Parar(f"O arquivo de {repo} veio diferente do oficial.")
        shutil.rmtree(pasta, ignore_errors=True)
        with zipfile.ZipFile(arquivo) as z:
            z.extractall(pasta)


def achar_git() -> str:
    achado = shutil.which("git")
    if achado:
        return achado
    local = FERRAMENTAS / "git" / "cmd" / "git.exe"
    if not local.exists():
        baixar_ferramenta("git-for-windows/git", r"MinGit-[\d.]+-64-bit\.zip", FERRAMENTAS / "git")
    return str(local)


def achar_gh() -> str:
    achado = shutil.which("gh")
    if achado:
        return achado
    local = FERRAMENTAS / "gh" / "bin" / "gh.exe"
    if not local.exists():
        baixar_ferramenta("cli/cli", r"gh_[\d.]+_windows_amd64\.zip", FERRAMENTAS / "gh")
    return str(local)


def rodar(*cmd: str, ok: bool = True, capturar: bool = True, pasta: Path = RAIZ) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=pasta, text=True, encoding="utf-8", errors="replace", capture_output=capturar)
    if ok and r.returncode:
        detalhe = (r.stderr or r.stdout or "").strip()[-500:]
        raise Parar(f"O comando {Path(cmd[0]).stem} {cmd[1]} falhou.\n{detalhe}")
    return r


def conferir_arquivos(git: str) -> None:
    nomes = rodar(git, "ls-files", "--cached", "--others", "--exclude-standard").stdout.splitlines()
    ruins = [n for n in nomes if PROIBIDOS.search(n)]
    for nome in nomes:
        caminho = RAIZ / nome
        if caminho.is_file() and caminho.stat().st_size < 3_000_000 and SEGREDOS.search(caminho.read_bytes()):
            ruins.append(nome)
    if ruins:
        raise Parar("Parei para proteger suas contas. Estes arquivos têm dados pessoais ou chaves:\n  " + "\n  ".join(sorted(set(ruins))))


def ler_novidades() -> list[dict]:
    return json.loads((RAIZ / "novidades.json").read_text(encoding="utf-8"))


def numero(versao: str) -> tuple[int, ...]:
    return tuple(int(p) for p in versao.split("."))


def preparar_lancamento(atual: str) -> str:
    """Pergunta o número e as novidades e atualiza os arquivos da versão."""
    partes = [int(p) for p in atual.split(".")]
    partes[-1] += 1
    sugestao = ".".join(map(str, partes))
    nova = input(f"Versão atual: {atual}\nNúmero da nova versão [{sugestao}]: ").strip() or sugestao
    if not re.fullmatch(r"\d+\.\d+\.\d+", nova) or numero(nova) <= numero(atual):
        raise Parar(f"Use um número maior que {atual}, como {sugestao}.")
    print("\nO que mudou? Escreva uma novidade por linha. Deixe a linha vazia para terminar.")
    notas = []
    while len(notas) < 8:
        linha = input(f"{len(notas) + 1}. ").strip()
        if not linha:
            break
        notas.append(linha[:200])
    if not notas:
        raise Parar("Escreva pelo menos uma novidade para avisar seus usuários.")
    lista = [v for v in ler_novidades() if v["versao"] != nova]
    lista.insert(0, {"versao": nova, "data": time.strftime("%Y-%m-%d"), "notas": notas})
    (RAIZ / "novidades.json").write_text(json.dumps(lista, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trocas = ((RAIZ / "nucleo" / "versao.py", r'VERSAO = "[^"]+"', f'VERSAO = "{nova}"'),
              (RAIZ / "empacotar" / "instalador.iss", r'#define Versao "[^"]+"', f'#define Versao "{nova}"'),
              (RAIZ / "README.md", r"vers%C3%A3o-[\d.]+-", f"vers%C3%A3o-{nova}-"))
    for arquivo, padrao, novo in trocas:
        dados = arquivo.read_bytes().decode("utf-8")
        arquivo.write_bytes(re.sub(padrao, novo, dados, count=1).encode("utf-8"))
    return nova


def aguardar_instalador(gh: str, alvo: str, marca: str) -> bool:
    """Os usuários só recebem o aviso depois que o instalador estiver pronto para baixar."""
    pausa = float(os.environ.get("CLIPADOR_ESPERA", 30))
    print("Aguardando o GitHub terminar o instalador. Deixe esta janela aberta, leva de 15 a 30 minutos.")
    for _ in range(120):
        if not rodar(gh, "release", "view", marca, "--repo", alvo, "--json", "tagName", ok=False).returncode:
            return True
        r = rodar(gh, "run", "list", "--repo", alvo, "--workflow", "instalador.yml", "--branch", marca, "--limit", "1", "--json", "status,conclusion", ok=False)
        execucoes = json.loads(r.stdout or "[]") if not r.returncode else []
        if execucoes and execucoes[0].get("status") == "completed" and execucoes[0].get("conclusion") != "success":
            print(f"O GitHub não conseguiu criar o instalador. Veja em https://github.com/{alvo}/actions")
            return False
        time.sleep(pausa)
    print("O instalador ainda não ficou pronto. Abra este arquivo de novo mais tarde para avisar os usuários.")
    return False


def ultima_liberada(gh: str, alvo: str) -> list[dict]:
    """Histórico só com as versões que já têm instalador."""
    lista = sorted(ler_novidades(), key=lambda v: numero(v["versao"]), reverse=True)
    for n, v in enumerate(lista):
        if not rodar(gh, "release", "view", f"v{v['versao']}", "--repo", alvo, "--json", "tagName", ok=False).returncode:
            return lista[n:]
    return []


def marcar_publicacao(pasta: Path, publicacao: dict) -> None:
    """Dá um código a cada publicação para os navegadores trocarem a cópia antiga sozinhos."""
    resumo = hashlib.sha256(json.dumps(publicacao, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    for arquivo in sorted(p for p in (RAIZ / "site").rglob("*") if p.is_file()):
        resumo.update(arquivo.name.encode("utf-8") + arquivo.read_bytes())
    codigo = resumo.hexdigest()[:12]
    pagina = (pasta / "index.html").read_text(encoding="utf-8").replace('const atual = "dev"', f'const atual = "{codigo}"', 1)
    pagina = pagina.replace('href="estilo.css"', f'href="estilo.css?v={codigo}"').replace('src="site.js"', f'src="site.js?v={codigo}"')
    if publicacao:
        pagina = re.sub(r"(<(?:b|span) data-versao>)[^<]*", rf"\g<1>{publicacao['versao']}", pagina)
        (pasta / "versao.json").write_text(json.dumps({**publicacao, "site": codigo}, ensure_ascii=False, indent=2), encoding="utf-8")
    (pasta / "index.html").write_text(pagina, encoding="utf-8")


def publicar_site(git: str, gh: str, conta: dict) -> str:
    """Envia só a pasta site para o repositório público que vira o endereço do projeto."""
    dono = conta["login"]
    alvo = f"{dono}/{dono}.github.io"
    if rodar(gh, "repo", "view", alvo, "--json", "name", ok=False).returncode:
        rodar(gh, "repo", "create", alvo, "--public", "--description", "Site do Clipador: cortes prontos enquanto a live acontece.")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        copia = Path(tmp) / "site"
        rodar(git, "clone", "-q", f"https://github.com/{alvo}.git", str(copia))
        for item in copia.iterdir():
            if item.name != ".git":
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        shutil.copytree(RAIZ / "site", copia, dirs_exist_ok=True)
        (copia / ".nojekyll").write_text("", encoding="utf-8")
        historico = ultima_liberada(gh, f"{dono}/{REPOSITORIO}")
        publicacao = {}
        if historico:
            baixar = f"https://github.com/{dono}/{REPOSITORIO}/releases/latest/download/Clipador-Instalador.exe"
            publicacao = {**historico[0], "baixar": baixar, "historico": historico}
        marcar_publicacao(copia, publicacao)
        rodar(git, "checkout", "-q", "-B", "main", pasta=copia)
        rodar(git, "config", "user.name", conta.get("name") or dono, pasta=copia)
        rodar(git, "config", "user.email", f"{conta['id']}+{dono}@users.noreply.github.com", pasta=copia)
        rodar(git, "add", "-A", pasta=copia)
        if rodar(git, "status", "--porcelain", pasta=copia).stdout.strip():
            rodar(git, "commit", "-q", "-m", "Atualiza o site do Clipador", pasta=copia)
            rodar(git, "push", "-q", "-u", "origin", "main", pasta=copia)
    rodar(gh, "api", "-X", "POST", f"repos/{alvo}/pages", "-f", "source[branch]=main", "-f", "source[path]=/", ok=False)
    return f"https://{dono.lower()}.github.io"


def _salvar_versao(git: str, versao: str) -> None:
    rodar(git, "add", "-A")
    conferir_arquivos(git)
    if rodar(git, "status", "--porcelain").stdout.strip():
        rodar(git, "commit", "-q", "-m", f"Clipador {versao}")


def enviar(git: str, versao: str) -> None:
    """Envia a pasta para o ramo main do GitHub, seja qual for o nome do ramo no computador
    (pastas antigas podem estar em "master") e mesmo que o GitHub já tenha um histórico diferente."""
    _salvar_versao(git, versao)
    if rodar(git, "rev-parse", "--verify", "HEAD", ok=False).returncode:
        raise Parar("Não encontrei nenhum arquivo para enviar nesta pasta.")
    rodar(git, "branch", "-M", "main")
    envio = rodar(git, "push", "-u", "origin", "HEAD:main", ok=False)
    if not envio.returncode:
        return
    erro = (envio.stderr or "") + (envio.stdout or "")
    if not re.search(r"rejected|non-fast-forward|fetch first|stale info", erro, re.I):
        raise Parar(f"O comando git push falhou.\n{erro.strip()[-500:]}")
    # O GitHub tem um histórico que esta pasta não conhece (pasta nova, outro computador).
    # Os arquivos desta pasta continuam valendo: a nova versão entra por cima do que já está lá.
    print("O GitHub já tinha uma versão anterior. Juntando com esta pasta.")
    rodar(git, "fetch", "-q", "origin", "main")
    rodar(git, "reset", "-q", "--soft", "FETCH_HEAD")
    _salvar_versao(git, versao)
    rodar(git, "push", "-u", "origin", "HEAD:main")


def main() -> int:
    versao = re.search(r'VERSAO = "([^"]+)"', (RAIZ / "nucleo" / "versao.py").read_text(encoding="utf-8"))[1]
    if "--lancar" in sys.argv:
        versao = preparar_lancamento(versao)
    print(f"Publicando o Clipador {versao} em um repositório privado.\n")
    git, gh = achar_git(), achar_gh()
    os.environ["PATH"] = str(Path(git).parent) + os.pathsep + os.environ["PATH"]

    if rodar(gh, "auth", "status", ok=False).returncode:
        print("O navegador vai abrir para você entrar na sua conta do GitHub.")
        rodar(gh, "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web", "--scopes", "repo,workflow", capturar=False)
    rodar(gh, "auth", "setup-git")
    conta = json.loads(rodar(gh, "api", "user").stdout)
    dono = conta["login"]
    alvo = f"{dono}/{REPOSITORIO}"

    if not (RAIZ / ".git").exists():
        rodar(git, "init", "-b", "main")
    rodar(git, "config", "user.name", conta.get("name") or dono)
    rodar(git, "config", "user.email", f"{conta['id']}+{dono}@users.noreply.github.com")
    conferir_arquivos(git)

    atual = rodar(gh, "repo", "view", alvo, "--json", "visibility", ok=False)
    if atual.returncode:
        print(f"Criando {alvo} como privado")
        rodar(gh, "repo", "create", alvo, "--private", "--description", DESCRICAO, "--disable-wiki")
    elif json.loads(atual.stdout)["visibility"] != "PRIVATE":
        raise Parar(f"O repositório {alvo} já existe e não é privado. Nada foi enviado.")

    endereco = f"https://github.com/{alvo}.git"
    if rodar(git, "remote", "get-url", "origin", ok=False).returncode:
        rodar(git, "remote", "add", "origin", endereco)
    else:
        rodar(git, "remote", "set-url", "origin", endereco)
    # Uma pasta extraída de novo continua a partir do que já está no GitHub.
    if rodar(git, "rev-parse", "--verify", "HEAD", ok=False).returncode and not rodar(git, "fetch", "-q", "origin", "main", ok=False).returncode:
        rodar(git, "reset", "-q", "--mixed", "FETCH_HEAD")
    print("Enviando os arquivos")
    enviar(git, versao)

    topicos = [x for t in TOPICOS for x in ("--add-topic", t)]
    rodar(gh, "repo", "edit", alvo, "--description", DESCRICAO, "--enable-issues", "--enable-wiki=false", "--enable-projects=false", "--delete-branch-on-merge", *topicos)

    marca = f"v{versao}"
    if rodar(git, "ls-remote", "--tags", "origin", marca).stdout.strip():
        print(f"\nA versão {versao} já tem instalador. Para gerar outro, aumente o número em nucleo/versao.py.")
    else:
        rodar(git, "tag", "-f", marca)
        rodar(git, "push", "origin", marca)
        print("\nO GitHub começou a criar o instalador.")
    aguardar_instalador(gh, alvo, marca)
    print("Publicando o site")
    site = publicar_site(git, gh, conta)
    print(f"\nPronto!\nRepositório privado: https://github.com/{alvo}\nSite público: {site} (pode levar alguns minutos para abrir)")
    webbrowser.open(site)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Parar as e:
        print(f"\nNão foi possível terminar: {e}")
        sys.exit(1)
