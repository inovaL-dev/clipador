"use strict";
/* Camada de interface da 1.19: ícones, paleta de comandos (Ctrl+K), atalhos, tour de boas-vindas
   e estados vazios com ações. Tudo em JavaScript puro, sem bibliotecas, para o programa continuar leve. */
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const calmo = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Ícones (traço de 1,8, no mesmo desenho dos ícones da barra lateral) ---------- */
  const ICONES = {
    play: '<path d="M7 4.5v15l12-7.5z"/>',
    tesoura: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 7.5 20 17M8 16.5 20 7"/>',
    camadas: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    check: '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="m8 12 3 3 5-6"/>',
    x: '<circle cx="12" cy="12" r="8.5"/><path d="m9 9 6 6M15 9l-6 6"/>',
    lixo: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    enviado: '<path d="M4 12.5 9 17 20 6"/>',
    upload: '<path d="M12 16V5M7.5 9.5 12 5l4.5 4.5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    filme: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    busca: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    lapis: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    baixar: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M4 19h16"/>',
    relogio: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    mais: '<path d="M12 5v14M5 12h14"/>',
    salvar: '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    atualizar: '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16M20 20v-4h-4"/>',
    copiar: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    vivo: '<circle cx="12" cy="12" r="3"/><path d="M6.3 17.7a8 8 0 0 1 0-11.4M17.7 6.3a8 8 0 0 1 0 11.4"/>',
    raio: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    pincel: '<path d="M5 19 15.5 8.5l3 3L8 22H5z" transform="translate(0 -2)"/><path d="M14 4h6M17 1v6" transform="translate(0 2)"/>',
    lampada: '<path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/><path d="M10 20h4"/>',
    ajustes: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    teclado: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h1M10 10h1M14 10h1M18 10h0M7 14h10"/>',
    mapa: '<path d="M9 4 3 6.5v13L9 17l6 2.5 6-2.5V4l-6 2.5z"/><path d="M9 4v13M15 6.5v13"/>',
    olho: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    agenda: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    frase: '<rect x="4" y="3.5" width="16" height="17" rx="2.5"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    pasta: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    seta: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h0"/>',
    alerta: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4M12 17h0"/>',
    ok: '<circle cx="12" cy="12" r="8.5"/><path d="m8 12 3 3 5-6"/>',
  };
  function icone(nome, classe = "ic") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", classe);
    svg.innerHTML = ICONES[nome] || ICONES.info;
    return svg;
  }
  window.clipadorIcone = icone;

  /* Ícones nos botões principais */
  const BOTOES = {
    "#link-enviar": "play", "#ver-cortes": "tesoura", "#abrir-montagem": "camadas", "#cancelar-edicoes": "x", "#selecionar-cortes": "check",
    "#sel-postado": "enviado", "#sel-apagar": "lixo", "#apagar-selecionados": "lixo", "#hor-mais": "mais", "#hor-salvar": "salvar",
    "#gr-enviar": "tesoura", "#lg-criar": "filme", "#ps-buscar": "busca", "#ps-minha": "lapis", "#ps-baixar": "baixar",
    "#jl-enviar": "upload", "#jl-timeline": "filme", "#it-timeline": "filme", "#ed-timeline": "filme", "#ed-bastidores": "olho",
    "#ed-salvar": "atualizar", "#ed-copiar": "copiar", "#it-copiar-titulo": "copiar", "#it-copiar-desc": "copiar", "#jl-copiar-titulo": "copiar",
    "#jl-copiar-desc": "copiar", "#ed-melhorar": "raio", "#aj-atualizar": "atualizar", "#ed-enquadrar": "olho", "#cam-salvar": "salvar",
  };
  for (const [q, nome] of Object.entries(BOTOES)) { const b = $(q); if (b && !b.querySelector("svg")) b.prepend(icone(nome)); }

  /* Ícones nas abas internas e nos filtros */
  const SUBS = { '[data-sub="agenda"]': "agenda", '[data-sub="pastas"]': "pasta", '[data-sub="horarios"]': "relogio", '[data-sub="canal"]': "upload",
    '[data-filtro="postar"]': "play", '[data-filtro="postados"]': "enviado", '[data-filtro="montagens"]': "camadas", '[data-filtro="todos"]': "tesoura" };
  for (const [q, nome] of Object.entries(SUBS)) $$(q).forEach((b) => { if (!b.querySelector("svg.ic")) b.prepend(icone(nome)); });

  /* Ícone de cada página no título, igual ao da barra lateral */
  for (const b of $$(".abas button[data-aba]")) {
    const h1 = $(`#aba-${b.dataset.aba} .pagina-topo h1`), svg = b.querySelector("svg");
    if (h1 && svg && !h1.querySelector(".selo-pagina")) { const s = document.createElement("span"); s.className = "selo-pagina"; s.append(svg.cloneNode(true)); h1.prepend(s); }
  }

  /* ---------- Avisos com ícone e cor ---------- */
  const toast = $("#toast");
  if (toast) {
    const marcar = () => {
      const t = toast.textContent || "";
      toast.dataset.tipo = /não |nao |erro|falh|inválid|invalido|escolha |confira|aguarde|sem acesso|nenhum/i.test(t) ? "erro" : "ok";
    };
    new MutationObserver(marcar).observe(toast, { childList: true, characterData: true, subtree: true });
  }

  /* ---------- Paleta de comandos ---------- */
  const irPara = (aba) => $(`.abas button[data-aba="${aba}"]`)?.click();
  const clicar = (q) => () => { const b = $(q); if (b && !b.hidden && !b.disabled) b.click(); };
  const COMANDOS = [
    { n: "Acompanhar uma live", d: "Colar o link da Kick, Twitch, YouTube ou X", i: "vivo", f: () => { irPara("vivo"); setTimeout(() => $("#link")?.focus(), 60); } },
    { n: "Cortar agora", d: "Corta a live que está sendo gravada", i: "raio", k: "C", f: () => { irPara("vivo"); setTimeout(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "c" })), 60); } },
    { n: "Ver os cortes", d: "Todos os cortes prontos e em edição", i: "tesoura", k: "Ctrl 2", f: () => irPara("cortes") },
    { n: "Cortar um vídeo pronto", d: "Live que já acabou ou arquivo do computador", i: "upload", f: () => { irPara("longos"); setTimeout(() => $("#form-gravada")?.scrollIntoView({ block: "start", behavior: calmo ? "auto" : "smooth" }), 80); } },
    { n: "Criar montagem", d: "Juntar os melhores momentos em um vídeo", i: "camadas", f: () => { irPara("cortes"); setTimeout(clicar("#abrir-montagem"), 80); } },
    { n: "Selecionar cortes", d: "Para apagar ou marcar vários de uma vez", i: "check", f: () => { irPara("cortes"); setTimeout(clicar("#selecionar-cortes"), 80); } },
    { n: "Cancelar todas as edições", d: "Para a fila de edição", i: "x", f: () => { irPara("cortes"); setTimeout(() => { const b = $("#cancelar-edicoes"); if (b && !b.hidden) { b.scrollIntoView({ block: "center" }); b.focus(); } }, 80); } },
    { n: "Agenda de postagem", d: "Pastas, horários e canal do YouTube", i: "agenda", k: "Ctrl 3", f: () => irPara("postagem") },
    { n: "Vídeos longos", d: "Vídeos de 5 a 30 minutos com os melhores momentos", i: "filme", k: "Ctrl 4", f: () => irPara("longos") },
    { n: "Posts de frase", d: "As melhores falas para o feed e os stories", i: "frase", k: "Ctrl 5", f: () => irPara("posts") },
    { n: "Abrir o editor", d: "Timeline, transições e efeitos", i: "filme", k: "Ctrl 6", f: () => irPara("editor") },
    { n: "Estilo do vídeo", d: "Legenda, título, selo da live, filtro e fontes", i: "pincel", f: clicar("#abrir-estilo") },
    { n: "Aprendizado", d: "O que o Clipador está aprendendo com o seu canal", i: "lampada", f: clicar("#abrir-aprendizado") },
    { n: "Ajustes", d: "Cortes, legenda, potencial, desempenho", i: "ajustes", k: "Ctrl ,", f: clicar("#abrir-ajustes") },
    { n: "Procurar atualizações", d: "Ver se tem versão nova do Clipador", i: "atualizar", f: clicar("#aj-atualizar") },
    { n: "Atalhos de teclado", d: "Todas as teclas rápidas", i: "teclado", k: "?", f: () => abrirAtalhos() },
    { n: "Ver o tour de novo", d: "Os primeiros passos, rapidinho", i: "mapa", f: () => tour(true) },
  ];
  const semAcento = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  const paleta = document.createElement("dialog");
  paleta.className = "paleta"; paleta.setAttribute("aria-label", "Buscar ações");
  paleta.innerHTML = '<div class="paleta-busca"><input type="text" placeholder="O que você quer fazer?" aria-label="Buscar ações" autocomplete="off" spellcheck="false"><kbd>Esc</kbd></div><ul role="listbox"></ul><p class="paleta-pe"><span><kbd>↑</kbd><kbd>↓</kbd> escolher</span><span><kbd>Enter</kbd> abrir</span><span><kbd>Ctrl</kbd><kbd>K</kbd> abre de qualquer lugar</span></p>';
  paleta.querySelector(".paleta-busca").prepend(icone("busca"));
  document.body.append(paleta);
  const campo = paleta.querySelector("input"), lista = paleta.querySelector("ul");
  let filtrados = [], ativo = 0;
  function desenhar() {
    const q = semAcento(campo.value.trim());
    filtrados = COMANDOS.filter((c) => !q || semAcento(`${c.n} ${c.d}`).includes(q) || q.split(" ").every((p) => semAcento(`${c.n} ${c.d}`).includes(p)));
    ativo = Math.min(ativo, Math.max(0, filtrados.length - 1));
    lista.replaceChildren(...filtrados.map((c, n) => {
      const li = document.createElement("li"); li.setAttribute("role", "option"); li.setAttribute("aria-selected", String(n === ativo));
      const txt = document.createElement("div"); const b = document.createElement("b"); b.textContent = c.n; const s = document.createElement("span"); s.textContent = c.d; txt.append(b, s);
      li.append(icone(c.i), txt); if (c.k) { const k = document.createElement("kbd"); k.textContent = c.k; li.append(k); }
      li.addEventListener("click", () => executar(c)); li.addEventListener("pointermove", () => { if (ativo !== n) { ativo = n; marcarAtivo(); } });
      return li;
    }));
    if (!filtrados.length) { const li = document.createElement("li"); li.className = "paleta-nada"; li.textContent = "Nada encontrado. Tente outra palavra."; lista.append(li); }
  }
  function marcarAtivo() { [...lista.children].forEach((li, n) => li.setAttribute("aria-selected", String(n === ativo))); lista.children[ativo]?.scrollIntoView({ block: "nearest" }); }
  function executar(c) { paleta.close(); setTimeout(c.f, 30); }
  function abrirPaleta() { if (paleta.open) return; document.querySelector("dialog[open]")?.close(); campo.value = ""; ativo = 0; desenhar(); paleta.showModal(); campo.focus(); }
  campo.addEventListener("input", () => { ativo = 0; desenhar(); });
  campo.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); ativo = (ativo + 1) % Math.max(1, filtrados.length); marcarAtivo(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); ativo = (ativo - 1 + filtrados.length) % Math.max(1, filtrados.length); marcarAtivo(); }
    else if (ev.key === "Enter" && filtrados[ativo]) { ev.preventDefault(); executar(filtrados[ativo]); }
  });
  paleta.addEventListener("click", (ev) => { if (ev.target === paleta) paleta.close(); });

  /* Botão de busca na barra lateral */
  const marca = $(".lateral .marca");
  if (marca) {
    const b = document.createElement("button"); b.type = "button"; b.className = "busca-acoes"; b.id = "busca-acoes";
    b.append(icone("busca")); const t = document.createElement("span"); t.textContent = "Buscar ações"; const k = document.createElement("kbd"); k.textContent = "Ctrl K"; b.append(t, k);
    b.addEventListener("click", abrirPaleta); marca.after(b);
  }

  /* ---------- Atalhos ---------- */
  const ATALHOS = [["Ctrl K", "Buscar ações"], ["Ctrl 1 a 6", "Trocar de tela"], ["Ctrl ,", "Ajustes"], ["C", "Cortar agora (tela Ao vivo)"], ["Esc", "Fechar janela ou sair da seleção"], ["?", "Esta lista"]];
  const janelaAtalhos = document.createElement("dialog");
  janelaAtalhos.className = "janela atalhos-app"; janelaAtalhos.setAttribute("aria-label", "Atalhos de teclado");
  janelaAtalhos.innerHTML = `<header><h2>Atalhos de teclado</h2><button class="botao fantasma" type="button" aria-label="Fechar">✕</button></header><dl>${ATALHOS.map(([k, d]) => `<div><dt>${k.split(" ").map((x) => x === "a" ? "<i>a</i>" : `<kbd>${x}</kbd>`).join("")}</dt><dd>${d}</dd></div>`).join("")}</dl>`;
  janelaAtalhos.querySelector("button").addEventListener("click", () => janelaAtalhos.close());
  document.body.append(janelaAtalhos);
  function abrirAtalhos() { document.querySelector("dialog[open]")?.close(); janelaAtalhos.showModal(); }
  const ABAS = ["vivo", "cortes", "postagem", "longos", "posts", "editor"];
  document.addEventListener("keydown", (ev) => {
    const digitando = ev.target.closest?.("input, textarea, select, [contenteditable]");
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") { ev.preventDefault(); paleta.open ? paleta.close() : abrirPaleta(); return; }
    if ((ev.ctrlKey || ev.metaKey) && ev.key === ",") { ev.preventDefault(); if (!document.querySelector("dialog[open]")) $("#abrir-ajustes")?.click(); return; }
    if ((ev.ctrlKey || ev.metaKey) && /^[1-6]$/.test(ev.key) && !document.querySelector("dialog[open]")) { ev.preventDefault(); irPara(ABAS[+ev.key - 1]); return; }
    if (ev.key === "?" && !digitando && !document.querySelector("dialog[open]") && $("#aba-editor")?.hidden !== false) { ev.preventDefault(); abrirAtalhos(); }
  });
  /* Dica do atalho em cada item da barra lateral */
  $$(".abas button[data-aba]").forEach((b) => { const n = ABAS.indexOf(b.dataset.aba) + 1; if (n) b.title = `${b.querySelector(".aba-nome")?.textContent || ""} (Ctrl+${n})`; });

  /* ---------- Estados vazios com ícone e ação ---------- */
  const VAZIOS = {
    "#sem-cortes": { i: "tesoura", acoes: [["Acompanhar uma live", "vivo", () => COMANDOS[0].f()], ["Cortar um vídeo pronto", "upload", () => COMANDOS[3].f()]] },
    "#agenda-vazia": { i: "agenda", acoes: [["Escolher as pastas", "pasta", () => $('#aba-postagem [data-sub="pastas"]')?.click()]] },
    "#longos-vazio": { i: "filme", acoes: [] },
    "#ps-vazio": { i: "frase", acoes: [["Ver os cortes", "tesoura", () => irPara("cortes")]] },
  };
  for (const [q, v] of Object.entries(VAZIOS)) {
    const p = $(q); if (!p || p.closest(".vazio-card")) continue;
    const card = document.createElement("div"); card.className = "vazio-card"; p.before(card);
    const bola = document.createElement("span"); bola.className = "vazio-icone"; bola.append(icone(v.i));
    const acoes = document.createElement("div"); acoes.className = "vazio-acoes";
    v.acoes.forEach(([t, i, f], n) => { const b = document.createElement("button"); b.type = "button"; b.className = n ? "botao" : "botao principal"; b.append(icone(i), t); b.addEventListener("click", f); acoes.append(b); });
    card.append(bola, p, acoes);
    const sincronizar = () => { card.hidden = p.hidden; };
    sincronizar(); new MutationObserver(sincronizar).observe(p, { attributes: true, attributeFilter: ["hidden"] });
  }

  /* ---------- Tour de boas-vindas ---------- */
  const PASSOS = [
    { alvo: "#form-link", aba: "vivo", t: "Comece aqui", d: "Cole o link de uma ou várias lives e clique em Acompanhar live. O Clipador grava, lê o chat e corta sozinho." },
    { alvo: '.abas button[data-aba="cortes"]', t: "Seus cortes", d: "Os cortes aparecem aqui com a nota de potencial de viralizar. Os melhores ficam no topo." },
    { alvo: "#abrir-estilo", t: "Deixe com a sua cara", d: "Legenda, título, selo da live, fontes e filtro. Vale para todos os próximos cortes." },
    { alvo: "#busca-acoes", t: "Tudo a um atalho", d: "Aperte Ctrl+K para buscar qualquer ação. Aperte ? para ver todos os atalhos." },
  ];
  const CHAVE_TOUR = "clipador-tour-1.19";
  function tour(forcar = false) {
    try { if (!forcar && localStorage.getItem(CHAVE_TOUR)) return; } catch {}
    let n = 0;
    const fundo = document.createElement("div"); fundo.className = "tour-fundo";
    const luz = document.createElement("div"); luz.className = "tour-luz";
    const caixa = document.createElement("div"); caixa.className = "tour-caixa"; caixa.setAttribute("role", "dialog"); caixa.setAttribute("aria-live", "polite");
    document.body.append(fundo, luz, caixa);
    const fim = () => { fundo.remove(); luz.remove(); caixa.remove(); removeEventListener("resize", mostrar); try { localStorage.setItem(CHAVE_TOUR, "1"); } catch {} };
    function mostrar() {
      const p = PASSOS[n]; if (p.aba) irPara(p.aba);
      const alvo = $(p.alvo); if (!alvo) { if (++n < PASSOS.length) mostrar(); else fim(); return; }
      alvo.scrollIntoView({ block: "center" });
      requestAnimationFrame(() => {
        const r = alvo.getBoundingClientRect(), m = 8;
        Object.assign(luz.style, { left: `${r.left - m}px`, top: `${r.top - m}px`, width: `${r.width + m * 2}px`, height: `${r.height + m * 2}px` });
        caixa.innerHTML = `<p class="tour-passo">${n + 1} de ${PASSOS.length}</p><h3></h3><p class="tour-texto"></p><div class="tour-botoes"><button type="button" class="botao fantasma" data-pular>Pular</button><button type="button" class="botao principal" data-proximo>${n + 1 < PASSOS.length ? "Próximo" : "Começar"}</button></div>`;
        caixa.querySelector("h3").textContent = p.t; caixa.querySelector(".tour-texto").textContent = p.d;
        const larg = Math.min(340, innerWidth - 32), abaixo = r.bottom + 16 + 190 < innerHeight;
        let x = r.left + r.width / 2 - larg / 2; if (r.width < 260 && r.left < 300) x = r.right + 20;
        Object.assign(caixa.style, { width: `${larg}px`, left: `${Math.max(16, Math.min(innerWidth - larg - 16, x))}px`, top: r.width < 260 && r.left < 300 ? `${Math.max(16, r.top - 20)}px` : abaixo ? `${r.bottom + 16}px` : `${Math.max(16, r.top - 206)}px` });
        caixa.querySelector("[data-pular]").addEventListener("click", fim);
        caixa.querySelector("[data-proximo]").addEventListener("click", () => { if (++n < PASSOS.length) mostrar(); else fim(); });
        caixa.querySelector("[data-proximo]").focus();
      });
    }
    addEventListener("resize", mostrar);
    fundo.addEventListener("click", fim);
    mostrar();
  }
  setTimeout(() => { if (!document.querySelector("dialog[open]")) tour(); }, document.documentElement.classList.contains("sem-abertura") ? 600 : 2600);
})();
