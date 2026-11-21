"use strict";
/* Assistir a edição: o Clipador mostra, passo a passo, o que está fazendo no corte.
   Ao vivo: cada frase ouvida, o começo e o fim escolhidos, o rosto achado, os zooms, as trocas de câmera,
   as legendas e os sons entrando na timeline, e o vídeo sendo montado quadro a quadro.
   Depois de pronto: o mesmo registro volta a tocar junto com o vídeo final. */
(() => {
  const PASSOS = [["capturando", "Guardar"], ["transcrevendo", "Ouvir"], ["enquadrando", "Enquadrar"], ["editando", "Montar"], ["pronto", "Pronto"]];
  const NOMES_LEG = Object.fromEntries([...MODELOS_LEGENDA, ...MODELOS_LEGENDA_EDITOR].map(([v, n]) => [v, n]));
  const ICONES = { etapa: "◆", passo: "›", fala: "“", decisao: "✓", item: "+" };
  let id = null, vigia = null, ultimo = null, mostrados = new Set(), filaLog = [], filaItens = [], soltando = null, base = null, modo = "vivo";

  const dlg = el("dialog", { class: "bastidores", id: "bastidores", "aria-labelledby": "bs-titulo" });
  dlg.innerHTML = `
    <header class="bs-topo">
      <div><h2 id="bs-titulo">Assistindo a edição</h2><p id="bs-gancho"></p></div>
      <ol class="bs-passos" id="bs-passos"></ol>
      <button class="botao" type="button" id="bs-fechar">Fechar</button>
    </header>
    <div class="bs-corpo">
      <div class="bs-monitor" id="bs-monitor" data-forma="largo">
        <img id="bs-img" alt="">
        <video id="bs-video" playsinline muted hidden></video>
        <svg class="bs-marcas" id="bs-marcas" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"></svg>
        <span class="bs-rec" id="bs-rec" hidden><i></i>Gravando</span>
        <span class="bs-varredura" id="bs-varredura" hidden></span>
        <span class="bs-tit" id="bs-tit" hidden></span>
        <span class="bs-leg" id="bs-leg" hidden></span>
        <span class="bs-selo" id="bs-selo"></span>
      </div>
      <section class="bs-diario" aria-label="O que o Clipador está fazendo">
        <h3>Diário da edição</h3>
        <ol id="bs-log" aria-live="polite"></ol>
        <div class="bs-fim" id="bs-fim" hidden>
          <button class="botao principal" type="button" id="bs-abrir">Abrir o corte</button>
          <button class="botao" type="button" id="bs-rever">Ver de novo</button>
        </div>
      </section>
    </div>
    <div class="bs-timeline" id="bs-timeline">
      <div class="bs-regua" id="bs-regua"></div>
      <div class="bs-faixas" id="bs-faixas"></div>
      <i class="bs-agulha" id="bs-agulha"></i>
    </div>`;
  document.body.append(dlg);
  const q = (s) => dlg.querySelector(s);
  q("#bs-fechar").addEventListener("click", () => dlg.close());
  dlg.addEventListener("close", parar);
  q("#bs-abrir").addEventListener("click", () => { const c = id; dlg.close(); abrirEditor(c); });
  q("#bs-rever").addEventListener("click", () => reproduzir());

  const FAIXAS = { gravacao: "Gravação", fala: "Fala", video: "Vídeo", camera: "Câmera", zoom: "Zoom", titulo: "Título", legenda: "Legenda", sons: "Sons" };
  function montarFaixas(lista) {
    q("#bs-faixas").replaceChildren(...lista.map((k) => el("div", { class: "bs-faixa", dados: { faixa: k } }, el("b", {}, FAIXAS[k]), el("div", { class: "bs-trilho" }))));
  }
  const trilho = (k) => q(`.bs-faixa[data-faixa="${k}"] .bs-trilho`);
  const pos = (t) => `${Math.max(0, Math.min(100, (t - base.ini) / Math.max(.1, base.fim - base.ini) * 100))}%`;
  const larg = (a, b) => `${Math.max(.4, (b - a) / Math.max(.1, base.fim - base.ini) * 100)}%`;
  function regua() {
    const dur = base.fim - base.ini, passo = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((p) => dur / p <= 8) || 900, marcas = [];
    for (let t = Math.ceil(base.ini / passo) * passo; t <= base.fim; t += passo) marcas.push(el("span", { style: `left:${pos(t)}` }, relogio(t - (base.zero || 0))));
    q("#bs-regua").replaceChildren(...marcas);
  }
  function bloco(k, a, b, texto, classe = "", atraso = 0) {
    const n = el("span", { class: `bs-item ${classe}`, style: `left:${pos(a)};width:${larg(a, b)};animation-delay:${atraso}ms`, title: texto || "" }, texto || "");
    trilho(k)?.append(n); return n;
  }
  function ponto(k, t, texto, classe = "") {
    const n = el("span", { class: `bs-ponto ${classe}`, style: `left:${pos(t)}`, title: texto || "" });
    trilho(k)?.append(n); return n;
  }
  function escrever(tipo, texto, quando) {
    const li = el("li", { dados: { tipo } }, el("i", { "aria-hidden": "true" }, ICONES[tipo] || "›"), el("span", {}, texto), quando != null ? el("time", {}, `${quando.toFixed(0)}s`) : null);
    q("#bs-log").append(li); q("#bs-log").scrollTop = q("#bs-log").scrollHeight;
  }
  /* Os itens da timeline e as linhas do diário entram um de cada vez, como se alguém estivesse editando. */
  function soltar() {
    if (soltando) return;
    soltando = setInterval(() => {
      const f = filaItens.shift() || null, l = f ? null : filaLog.shift();
      if (f) { f(); return; }
      if (l) { escrever(...l); return; }
      clearInterval(soltando); soltando = null;
    }, 140);
  }
  function passos(status) {
    const i = PASSOS.findIndex(([k]) => k === status), atual = status === "fila" ? 0 : i;
    q("#bs-passos").replaceChildren(...PASSOS.map(([, n], k) => el("li", { dados: { estado: status === "erro" ? (k < 4 ? "feito" : "") : k < atual ? "feito" : k === atual ? "atual" : "" } }, n)));
  }
  function forma(f) { q("#bs-monitor").dataset.forma = f; }
  function marcas(plano) {
    const svg = q("#bs-marcas"); svg.replaceChildren();
    if (!plano) return;
    const ns = "http://www.w3.org/2000/svg", r = (box, cls) => { if (!box) return; const e = document.createElementNS(ns, "rect"); e.setAttribute("x", box[0] * 100); e.setAttribute("y", box[1] * 100); e.setAttribute("width", box[2] * 100); e.setAttribute("height", box[3] * 100); e.setAttribute("class", cls); svg.append(e); };
    r(plano.moldura, "bs-moldura"); r(plano.rosto, "bs-rosto");
  }

  function fase(b) {
    if (b.trilhas) return "corte";
    return "bruto";
  }
  function prepararBruto(b) {
    const total = b.bruto || b.gravando?.[1] || 60;
    base = { ini: 0, fim: total, zero: 0, fase: "bruto" };
    montarFaixas(["gravacao", "fala"]); regua(); forma("largo");
  }
  function prepararCorte(t) {
    base = { ini: 0, fim: t.duracao + (t.outro || 0), zero: 0, fase: "corte" };
    montarFaixas(["video", "camera", "zoom", "titulo", "legenda", "sons"]); regua();
    filaItens.push(() => bloco("video", 0, t.duracao, "Corte", "bs-video"));
    if (t.outro) filaItens.push(() => bloco("video", t.duracao, t.duracao + t.outro, "Final com o seu @", "bs-outro"));
    filaLog.push(["passo", `Montando a timeline: ${relogio(t.duracao)} de vídeo`]);
    for (const c of t.cameras) {
      filaItens.push(() => bloco("camera", c.ini, c.fim, c.tipo === "rosto" ? "Rosto" : "Jogo", `bs-cam-${c.tipo}`));
      filaLog.push(["item", `${c.tipo === "rosto" ? "Rosto de perto" : "Jogo na tela toda"} em ${relogio(c.ini)}`]);
    }
    for (const z of t.zooms) filaItens.push(() => ponto("zoom", z, `Zoom em ${relogio(z)}`, "bs-zoom"));
    if (t.zooms.length) filaLog.push(["item", `${t.zooms.length} zooms nos picos de voz e de ação`]);
    for (const f of t.focos) { filaItens.push(() => bloco("zoom", f.t, f.t + f.dur, "Foco", "bs-foco")); filaLog.push(["item", `Aproximando o que apareceu na tela em ${relogio(f.t)}`]); }
    if (t.titulo) { filaItens.push(() => bloco("titulo", 0, t.titulo.fim, t.titulo.texto, "bs-tit-item")); filaLog.push(["item", `Título nos primeiros ${t.titulo.fim} segundos`]); }
    filaLog.push(["item", `${t.legendas.length} legendas no modelo ${NOMES_LEG[t.legenda_modelo] || t.legenda_modelo}`]);
    t.legendas.forEach((l) => filaItens.push(() => bloco("legenda", l.ini, l.fim, l.texto, "bs-leg-item")));
    for (const s of t.sons) { filaItens.push(() => ponto("sons", s.t, s.nome, "bs-som")); filaLog.push(["item", `${s.nome} em ${relogio(s.t)}`]); }
    filaLog.push(["passo", "Gerando o vídeo quadro a quadro"]);
    forma("alto"); soltar();
  }
  function textoEm(lista, t) { return (lista || []).find((l) => l.ini <= t && t < l.fim)?.texto || ""; }

  function desenhar(b) {
    q("#bs-gancho").textContent = b.gancho || "Procurando o melhor do momento";
    passos(b.status);
    for (const l of (b.log || []).slice(mostrados.size)) { mostrados.add(mostrados.size); filaLog.push([l.tipo, l.texto, l.t]); }
    soltar();
    const f = fase(b);
    if (!base || base.fase !== f) { if (f === "corte") prepararCorte(b.trilhas); else prepararBruto(b); }
    if (f === "bruto") {
      if (b.bruto && base.fim !== b.bruto) { base.fim = b.bruto; regua(); }
      const g = b.gravando; const tr = trilho("gravacao");
      if (tr) {
        tr.replaceChildren(el("span", { class: "bs-item bs-grav", style: `left:0;width:${larg(0, g && b.status === "capturando" ? g[0] : base.fim)};animation:none` }, b.status === "capturando" ? "Gravando" : "Trecho guardado"));
        if (b.momento_bruto != null) tr.append(el("span", { class: "bs-momento", style: `left:${pos(b.momento_bruto)}` }, "Momento"));
        if (b.janela) tr.append(el("span", { class: "bs-janela", style: `left:${pos(b.janela[0])};width:${larg(b.janela[0], b.janela[1])}` }));
      }
      const tf = trilho("fala");
      if (tf && tf.childElementCount !== (b.fala || []).length) {
        tf.replaceChildren(...(b.fala || []).map((p) => el("span", { class: "bs-palavra", style: `left:${pos(p.ini)};width:${larg(p.ini, p.fim)}`, title: p.p })));
      }
      q("#bs-agulha").style.left = `calc(var(--rotulo) + (100% - var(--rotulo) - 2.5rem) * ${(b.status === "capturando" && g ? g[0] : b.ouvido || 0) / Math.max(1, base.fim)})`;
      q("#bs-rec").hidden = b.status !== "capturando";
      q("#bs-varredura").hidden = b.status !== "transcrevendo";
      const recentes = (b.fala || []).slice(-6).map((p) => p.p).join(" ");
      q("#bs-leg").hidden = !recentes || b.status === "capturando"; q("#bs-leg").textContent = recentes;
      q("#bs-tit").hidden = true;
      marcas(b.status === "enquadrando" || b.plano ? b.plano : null);
      q("#bs-selo").textContent = b.status === "capturando" && g ? `${relogio(g[0])} de ${relogio(g[1])}` : b.status === "transcrevendo" ? `${(b.fala || []).length} palavras ouvidas` : b.etapa_nome;
    } else {
      const r = b.render || [0, 1], frac = r[0] / Math.max(1, r[1]), t = frac * (base.fim - base.ini);
      q("#bs-agulha").style.left = `calc(var(--rotulo) + (100% - var(--rotulo) - 2.5rem) * ${frac})`;
      q("#bs-rec").hidden = true; q("#bs-varredura").hidden = true; marcas(null);
      const leg = textoEm(b.trilhas.legendas, t); q("#bs-leg").hidden = !leg; q("#bs-leg").textContent = leg;
      const tit = b.trilhas.titulo && t < b.trilhas.titulo.fim ? b.trilhas.titulo.texto : ""; q("#bs-tit").hidden = !tit; q("#bs-tit").textContent = tit;
      q("#bs-selo").textContent = b.status === "pronto" ? "Pronto" : `Montando ${Math.round(frac * 100)}%`;
      $$(".bs-item, .bs-ponto", dlg).forEach((n) => { const x = parseFloat(n.style.left); n.classList.toggle("passou", x <= frac * 100); });
    }
    if (b.v !== ultimo?.v || !q("#bs-img").src) q("#bs-img").src = `/cortes/${id}/bastidores.jpg?v=${b.v || 0}`;
    const fim = b.status === "pronto" || b.status === "erro";
    q("#bs-fim").hidden = b.status !== "pronto";
    if (b.status === "erro") escrever("etapa", "Não foi possível terminar este corte.");
    ultimo = b;
    if (fim) { clearInterval(vigia); vigia = null; if (b.status === "pronto") setTimeout(() => { if (dlg.open && modo === "vivo") reproduzir(); }, 1800); }
  }

  async function puxar() {
    try { desenhar(await api("GET", `/api/cortes/${id}/bastidores`)); } catch { /* tenta de novo no próximo */ }
  }
  function limpar() {
    parar(); mostrados = new Set(); filaLog = []; filaItens = []; base = null; ultimo = null;
    q("#bs-log").replaceChildren(); q("#bs-faixas").replaceChildren(); q("#bs-regua").replaceChildren(); marcas(null);
    const v = q("#bs-video"); v.pause(); v.hidden = true; v.removeAttribute("src"); q("#bs-img").hidden = false;
  }
  function parar() { clearInterval(vigia); vigia = null; clearInterval(soltando); soltando = null; cancelAnimationFrame(parar.quadro); q("#bs-video").pause(); }

  /* Depois de pronto: o vídeo final toca no monitor e a agulha anda com ele pela timeline montada. */
  async function reproduzir() {
    let b = ultimo;
    if (!b?.trilhas) { try { b = await api("GET", `/api/cortes/${id}/bastidores`); } catch { return; } }
    limpar(); modo = "replay";
    q("#bs-titulo").textContent = "Como este corte foi editado"; q("#bs-gancho").textContent = b.gancho || ""; passos("pronto");
    if (!b.trilhas) { escrever("etapa", "Este corte foi feito antes de o Clipador guardar os bastidores. Os próximos já vêm com o registro completo."); }
    else {
      (b.log || []).forEach((l) => filaLog.push([l.tipo, l.texto, l.t]));
      prepararCorte(b.trilhas);
    }
    const v = q("#bs-video"); v.src = `/cortes/${id}/corte.mp4?v=${b.versao || 0}`; v.hidden = false; q("#bs-img").hidden = true; forma("alto");
    v.muted = false; v.controls = true; v.currentTime = 0; v.play().catch(() => { v.muted = true; v.play().catch(() => {}); });
    const anda = () => {
      if (base && b.trilhas) {
        const frac = v.duration ? v.currentTime / v.duration : 0;
        q("#bs-agulha").style.left = `calc(var(--rotulo) + (100% - var(--rotulo) - 2.5rem) * ${frac})`;
        $$(".bs-item, .bs-ponto", dlg).forEach((n) => n.classList.toggle("passou", parseFloat(n.style.left) <= frac * 100));
      }
      q("#bs-leg").hidden = true; q("#bs-tit").hidden = true;
      q("#bs-selo").textContent = "Vídeo final";
      parar.quadro = requestAnimationFrame(anda);
    };
    anda(); q("#bs-fim").hidden = false;
  }

  window.abrirBastidores = async (corteId, rever = false) => {
    id = corteId; limpar(); modo = rever ? "replay" : "vivo";
    q("#bs-titulo").textContent = "Assistindo a edição";
    if (!dlg.open) dlg.showModal();
    if (rever) { reproduzir(); return; }
    await puxar();
    if (ultimo && ultimo.status !== "pronto" && ultimo.status !== "erro") vigia = setInterval(puxar, 450);
  };
})();
