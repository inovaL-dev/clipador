"use strict";
/* Movimento da interface. Nada aqui é necessário para o programa funcionar. */
(() => {
  const nav = document.querySelector(".abas"), main = document.querySelector("#conteudo");
  const marca = document.createElement("span"); marca.className = "abas-marca"; marca.setAttribute("aria-hidden", "true"); nav.prepend(marca);
  function moverMarca() { const b = nav.querySelector('button[aria-pressed="true"]'); if (!b) return; marca.style.transform = `translate(${b.offsetLeft}px, ${b.offsetTop}px)`; marca.style.width = `${b.offsetWidth}px`; marca.style.height = `${b.offsetHeight}px`; }
  moverMarca(); new ResizeObserver(moverMarca).observe(nav); document.fonts?.ready.then(moverMarca);

  /* A capa aparece suavemente quando termina de carregar */
  const mostrarCapa = (ev) => { if (ev.target.tagName === "IMG") ev.target.classList.add("carregada"); };
  main.addEventListener("load", mostrarCapa, true); main.addEventListener("error", mostrarCapa, true);
  const conferirCapas = () => main.querySelectorAll(".poster > img:not(.carregada), .longo-capa > img:not(.carregada)").forEach((i) => { if (i.complete) i.classList.add("carregada"); });

  const regua = document.createElement("div"); regua.className = "regua-trabalho"; regua.setAttribute("aria-hidden", "true"); regua.append(document.createElement("i")); document.body.append(regua);

  const abrirOriginal = window.abrirAba;
  let abaAtual = nav.querySelector('button[aria-pressed="true"]')?.dataset.aba;
  window.abrirAba = (aba, rolar) => {
    abrirOriginal(aba, rolar); moverMarca();
    if (aba === abaAtual) return; abaAtual = aba;
    const pagina = main.querySelector(":scope > .pagina:not([hidden])");
    if (pagina && !pagina.querySelector(".st-mesa:not([hidden])")) { pagina.classList.remove("entra"); void pagina.offsetWidth; pagina.classList.add("entra"); setTimeout(() => pagina.classList.remove("entra"), 700); }
  };

  const renderOriginal = window.renderTudo;
  window.renderTudo = () => {
    renderOriginal();
    conferirCapas(); conferirContadores();
    const e = window.estado ?? (typeof estado !== "undefined" ? estado : null); if (!e) return;
    document.body.dataset.trabalhando = String(e.canais.some((c) => c.status === "gravando") || e.cortes.some((c) => !["pronto", "erro"].includes(c.status)) || e.longos.some((v) => !["pronto", "erro"].includes(v.status)));
  };

  /* O número só pula quando o valor realmente muda. */
  const contadores = new Map();
  nav.addEventListener("animationend", (ev) => ev.target.classList?.remove("salto"));
  function conferirContadores() {
    nav.querySelectorAll(".contador").forEach((n) => { const v = n.textContent; if (contadores.has(n) && contadores.get(n) !== v && v) n.classList.add("salto"); contadores.set(n, v); });
  }

  if (!matchMedia("(hover: hover)").matches) return;
  /* Luz que acompanha o mouse nos painéis */
  let pedido = 0, ultimo = null;
  main.addEventListener("pointermove", (ev) => { ultimo = ev; if (pedido) return; pedido = requestAnimationFrame(() => { pedido = 0; const p = ultimo.target.closest?.(".comando, .live, .agora, .post-bloco, .auto-longo, .cartao-acao"); if (!p) return; const r = p.getBoundingClientRect(); p.style.setProperty("--mx", `${ultimo.clientX - r.left}px`); p.style.setProperty("--my", `${ultimo.clientY - r.top}px`); }); }, { passive: true });

  /* O vídeo começa a tocar ao passar o mouse no cartão */
  let atual = null, espera = 0;
  function parar() { clearTimeout(espera); if (!atual) return; atual.video.pause(); atual.video.removeAttribute("src"); atual.video.load(); atual.video.remove(); atual.linha.remove(); atual = null; }
  function tocar(caixa) {
    const m = caixa.querySelector("img")?.getAttribute("src")?.match(/^\/(cortes|longos)\/([^/]+)\/capa/); if (!m) return;
    const video = document.createElement("video"); Object.assign(video, { muted: true, loop: true, playsInline: true, preload: "auto", src: m[1] === "cortes" ? `/cortes/${m[2]}/corte.mp4` : `/longos/${m[2]}/video.mp4#t=12` }); video.className = "previa-viva"; video.setAttribute("aria-hidden", "true"); video.tabIndex = -1;
    const linha = document.createElement("span"); linha.className = "previa-linha"; const barra = document.createElement("i"); linha.append(barra);
    video.addEventListener("playing", () => video.classList.add("tocando")); video.addEventListener("timeupdate", () => { if (video.duration) barra.style.width = `${video.currentTime / video.duration * 100}%`; });
    caixa.append(video, linha); atual = { caixa, video, linha }; video.play().catch(() => {});
  }
  main.addEventListener("pointerover", (ev) => {
    const caixa = ev.target.closest?.(".corte .poster, button.longo .longo-capa"); if (caixa === atual?.caixa) return; parar(); if (!caixa || ev.pointerType === "touch") return;
    espera = setTimeout(() => { if (caixa.isConnected) tocar(caixa); }, 340);
  }, { passive: true });
  main.addEventListener("pointerleave", parar); main.addEventListener("click", parar, true); document.addEventListener("visibilitychange", parar);
})();
