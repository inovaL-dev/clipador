"use strict";
/* Estúdio: timeline, prévia, inspetor, assistente e capas. O vídeo final sai do mesmo projeto, renderizado no computador. */
(() => {
const S = { aberto: false, tipo: null, id: null, p: null, capa: null, modo: "video", sel: new Set(), t: 0, tocando: false, px: 30, sujo: false, gerando: false,
  h: { video: { d: [], r: [] }, capa: { d: [], r: [] } }, caixas: new Map(), painel: "midia", zoomMao: false, filtros: [], fontes: [], sons: [], sug: [], clipe: [], ondas: new Map(), ultimoSom: 0, altFaixa: 1, vel: 1, ferr: "sel" };
const ALTURAS = { video: 46, texto: 28, legenda: 30, efeito: 24, audio: 44 };  // áudio mais alto para ver e arrastar o volume
const altF = (f) => Math.round(ALTURAS[f.tipo] * S.altFaixa);
const ROTULOS = { video: "Vídeo", imagem: "Imagem", forma: "Forma", texto: "Texto", legenda: "Legenda", efeito: "Efeito", audio: "Áudio" };
const ANIM = [["nenhuma", "Nenhuma"], ["fade", "Aparecer"], ["pop", "Pop"], ["zoom", "Zoom"], ["subir", "Subir"], ["descer", "Descer"], ["esquerda", "Da direita"], ["direita", "Da esquerda"], ["quique", "Quicar"], ["digitando", "Digitando"]];
const TRANS = [["corte", "Corte seco"], ["dissolver", "Dissolver"], ["preto", "Passar pelo preto"], ["branco", "Clarão branco"], ["zoom", "Zoom"], ["esquerda", "Deslizar para a esquerda"], ["direita", "Deslizar para a direita"], ["cima", "Deslizar para cima"], ["baixo", "Deslizar para baixo"], ["chicote", "Chicote"], ["queda", "Chicote vertical"], ["impulso", "Impulso de zoom"], ["giro", "Giro"], ["glitch", "Glitch"], ["rgb", "Separação de cores"], ["clarao_rapido", "Clarão rápido"], ["desfoque_rapido", "Desfoque rápido"]];
const EFEITOS = [["clarao", "Clarão"], ["tremor", "Tremor"], ["vinheta", "Vinheta"], ["escurecer", "Escurecer aos poucos"], ["clarear", "Surgir do preto"], ["desfoque", "Desfoque"], ["filtro", "Filtro de cor"], ["progresso", "Barra de progresso"], ["glitch", "Glitch"], ["rgb", "Separação de cores"], ["pulso", "Pulso de zoom"], ["sacudir", "Sacudir"], ["barras", "Barras de cinema"], ["pb", "Preto e branco"], ["brilho", "Brilho"], ["negativo", "Negativo"], ["espelho", "Espelho"]];
const PAD_EST = { fonte: "Poppins-Bold", tamanho: 66, cor: "#FFFFFF", opacidade: 100, maiusculas: false, alinhamento: "centro", ancora: "centro", espacamento: 0, entrelinha: 115, largura: 900, contorno: 0, contorno_cor: "#000000", sombra: false, sombra_cor: "#000000", sombra_opac: 60, sombra_x: 0, sombra_y: 4, sombra_blur: 8, fundo: false, fundo_cor: "#000000", fundo_opac: 75, fundo_raio: 14, fundo_pad: 18, borda: 0, borda_cor: "#FFFFFF", destaque: "nenhum", cor_destaque: "#FFC933", destaque_caixa: false, palavra_a_palavra: false, entrada: "nenhuma", saida: "nenhuma", efeito_texto: "nenhum", efeito_forca: 100, tempo_anim: .15 };
const FORTES = /^(nossa|caraca|meu|deus|absurdo|insano|incrivel|incrível|mano|socorro|nunca|sempre|muito|demais)/i;
const tela = $("#st-canvas"), g = tela.getContext("2d"), sobre = $("#st-sobre"), exato = $("#st-exato"), rolagem = $("#st-rolagem"), faixasEl = $("#st-faixas"), trilhas = $("#st-trilhas"), regua = $("#st-regua");
const lim = (v, a, b) => Math.min(b, Math.max(a, v)), arred = (v, n = 3) => +(+v).toFixed(n);
const tempoTxt = (s) => { const m = Math.floor(s / 60), r = s - m * 60; return `${m}:${r.toFixed(1).padStart(4, "0")}`; };
const nid = (p = "e") => p + Math.random().toString(16).slice(2, 11);
const clonar = (o) => JSON.parse(JSON.stringify(o));
const urlMidia = (m) => `/estudio/midia?raiz=${encodeURIComponent(m.raiz)}&rel=${encodeURIComponent(m.rel)}`;
const itens = () => S.p.faixas.flatMap((f) => f.itens.map((i) => [f, i]));
const achar = (id) => { for (const f of S.p.faixas) { const i = f.itens.find((x) => x.id === id); if (i) return [f, i]; } return [null, null]; };
const duracao = () => Math.max(0.1, ...S.p.faixas.flatMap((f) => f.itens.map((i) => i.ini + i.dur)));
const selecionados = () => [...S.sel].map((id) => achar(id)[1]).filter(Boolean);
const sel1 = () => { const a = selecionados(); return a.length === 1 ? a[0] : null; };

/* ---------- Valores e estilos ---------- */
const svg = (d) => `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICONES = { olho: svg('<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'), trava: svg('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'), som: svg('<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M17 9a4 4 0 0 1 0 6"/>') };
const PAD_T = { x: 0, y: 0, w: 100, h: 100, escala: 1, rot: 0, opac: 100, zoom: 1, zx: .5, zy: .5, cl: 0, ct: 0, cr: 0, cb: 0 };
const suave = (p) => p * p * (3 - 2 * p);
function val(item, prop, u) {
  const c = item.kf?.[prop];
  if (!c?.length) return item.t?.[prop] ?? PAD_T[prop] ?? 0;
  if (u <= c[0].t) return c[0].v;
  for (let n = 0; n < c.length - 1; n++) if (u < c[n + 1].t) { let p = (u - c[n].t) / Math.max(1e-6, c[n + 1].t - c[n].t); p = c[n].e === "degrau" ? 0 : c[n].e === "suave" ? suave(p) : p; return c[n].v + (c[n + 1].v - c[n].v) * p; }
  return c[c.length - 1].v;
}
const local = (i) => lim(S.t - i.ini, 0, i.dur);
function porProp(item, prop, v) {
  const c = item.kf?.[prop];
  if (!c?.length) { (item.t ||= {})[prop] = v; return; }
  const u = arred(local(item)), k = c.find((x) => Math.abs(x.t - u) < .02);
  if (k) k.v = v; else { c.push({ t: u, v, e: "linear" }); c.sort((a, b) => a.t - b.t); }
}
const estiloDe = (i) => i.tipo === "legenda" ? { ...PAD_EST, ...S.p.global.legenda, ...(i.estilo || {}) } : { ...PAD_EST, ...(i.estilo || {}) };

/* ---------- Histórico e gravação ---------- */
const pilha = () => S.h[S.modo];
const foto = () => JSON.stringify(S.modo === "capa" ? S.capa : S.p);
function antes() { const h = pilha(); h.d.push(foto()); if (h.d.length > 60) h.d.shift(); h.r = []; botoes(); }
function aplicarFoto(j) { if (S.modo === "capa") S.capa = JSON.parse(j); else S.p = JSON.parse(j); const existe = (id) => S.modo === "capa" ? S.capa.camadas?.some((c) => c.id === id) : achar(id)[1]; S.sel = new Set([...S.sel].filter(existe)); mudou(true); if (S.modo !== "capa") montarCabecas(); }  // continua com o mesmo elemento selecionado
function desfazer() { const h = pilha(); if (h.d.length) { h.r.push(foto()); aplicarFoto(h.d.pop()); botoes(); } }
function refazer() { const h = pilha(); if (h.r.length) { h.d.push(foto()); aplicarFoto(h.r.pop()); botoes(); } }
function botoes() { $("#st-desfazer").disabled = !pilha().d.length; $("#st-refazer").disabled = !pilha().r.length; }
let tempoSalvar;
function mudou(estrutura = false) {
  fecharPrevia(); S.rev = (S.rev || 0) + 1;
  S.sujo = true; $("#st-salvo").textContent = "Alterações não salvas";
  clearTimeout(tempoSalvar); tempoSalvar = setTimeout(salvar, 1200);
  pedirPintura(); pedirExato(); desenharLinha();
  if (estrutura) { montarInspetor(); montarPainel(); }
}
async function salvar() {
  clearTimeout(tempoSalvar); if (!S.aberto || !S.sujo) return;
  S.sujo = false; $("#st-salvo").textContent = "Salvando…";
  try {
    if (S.capa) await api("POST", `/api/estudio/${S.tipo}/${S.id}/capa`, { capa: S.capa });
    await api("POST", `/api/estudio/${S.tipo}/${S.id}/salvar`, { projeto: S.p });
    $("#st-salvo").textContent = `Salvo às ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  } catch (e) { S.sujo = true; $("#st-salvo").textContent = `Não salvou: ${e.message}`; tempoSalvar = setTimeout(salvar, 5000); }
}
addEventListener("beforeunload", (ev) => { if (S.aberto && S.sujo) { salvar(); ev.preventDefault(); } });

/* ---------- Fontes e mídias da prévia ---------- */
const fontesPedidas = new Set();
function fonteCss(id) {
  if (!fontesPedidas.has(id)) {
    fontesPedidas.add(id);
    const f = S.fontes.find((x) => x.id === id);
    if (f) new FontFace(`st-${id}`, `url("${f.url}")`).load().then((x) => { document.fonts.add(x); pedirPintura(); }).catch(() => {});
  }
  return `"st-${id}", "Instrument Sans", sans-serif`;
}
const videos = new Map(), imagens = new Map(), audios = new Map();
function elVideo(mid) {
  if (!videos.has(mid)) { const v = document.createElement("video"); v.src = urlMidia(S.p.midias[mid]); v.preload = "auto"; v.playsInline = true; v.addEventListener("seeked", pedirPintura); v.addEventListener("loadeddata", pedirPintura); videos.set(mid, v); }
  return videos.get(mid);
}
function elImagem(chave, m) {
  if (!imagens.has(chave)) { const i = new Image(); i.onload = pedirPintura; i.src = urlMidia(m); imagens.set(chave, i); }
  return imagens.get(chave);
}
const ativos = (tipoFaixa) => S.p.faixas.filter((f) => tipoFaixa(f)).flatMap((f) => f.itens.filter((i) => S.t >= i.ini && S.t < i.ini + i.dur).map((i) => [f, i]));
function sincronizarMidia() {
  const quer = new Map();
  for (const [f, i] of ativos((x) => x.tipo === "video" && !x.oculta)) if (i.tipo === "video" && S.p.midias[i.midia]) {
    const cand = { alvo: (i.entrada || 0) + local(i) * (i.velocidade || 1), vel: i.velocidade || 1, som: !i.mudo && !f.muda, vol: (i.volume ?? 100) / 100 * (S.p.global.volume_fala ?? 100) / 100 };
    const a = quer.get(i.midia); if (!a || (cand.som && !a.som)) quer.set(i.midia, cand);
  }
  for (const [mid, v] of videos) {
    const q = quer.get(mid);
    if (!q) { if (!v.paused) v.pause(); continue; }
    v.muted = !q.som || S.vel !== 1; v.volume = lim(q.vol, 0, 1); v.playbackRate = q.vel;
    if (S.tocando && S.vel > 0) { v.playbackRate = lim(q.vel * S.vel, .25, 8); if (Math.abs(v.currentTime - q.alvo) > .3 * Math.max(1, S.vel)) v.currentTime = q.alvo; if (v.paused) v.play().catch(() => {}); }
    else { if (!v.paused) v.pause(); if (Math.abs(v.currentTime - q.alvo) > .02 && !v.seeking) v.currentTime = q.alvo; }
  }
  for (const mid of quer.keys()) if (!videos.has(mid)) elVideo(mid);
}
let ctxAudio = null;
const buffers = new Map(), tocandoSons = new Set();
function audioCtx() { ctxAudio ||= new (window.AudioContext || window.webkitAudioContext)(); if (ctxAudio.state === "suspended") ctxAudio.resume(); return ctxAudio; }
function bufferDe(mid) {
  if (!buffers.has(mid)) buffers.set(mid, fetch(urlMidia(S.p.midias[mid])).then((r) => r.arrayBuffer()).then((b) => audioCtx().decodeAudioData(b)).catch(() => null));
  return buffers.get(mid);
}
const ganhosVivos = new Set();
function ganhoEm(i, t) { // volume, volume do tipo e entrada e saída suaves, como o vídeo final
  const g0 = S.p.global, cat = i.categoria || "efeito", u = t - i.ini, fi = +i.fade_in || 0, fo = +i.fade_out || 0;
  let g = (i.volume ?? 100) / 100 * (cat === "musica" ? g0.volume_musica ?? 100 : cat === "voz" ? g0.volume_fala ?? 100 : g0.volume_efeitos ?? 100) / 100;
  if (fi > 0 && u < fi) g *= Math.max(0, u / fi); if (fo > 0 && u > i.dur - fo) g *= Math.max(0, (i.dur - u) / fo); return g;
}
function atualizarGanhos() { if (!ctxAudio) return; for (const v of ganhosVivos) { const [, i] = achar(v.id); if (i) v.gn.gain.setTargetAtTime(ganhoEm(i, S.t), ctxAudio.currentTime, .015); } }
async function tocarSom(i, f) {
  const a = await bufferDe(i.midia); if (!a || !S.tocando) return;
  const c = audioCtx(), src = c.createBufferSource(), gn = c.createGain();
  src.buffer = a; gn.gain.value = ganhoEm(i, S.t);
  src.connect(gn).connect(c.destination); const salto = Math.max(0, S.t - i.ini); src.start(0, (i.entrada || 0) + salto, Math.max(.01, i.dur - salto)); tocandoSons.add(src);
  const vivo = { id: i.id, gn }; ganhosVivos.add(vivo); src.onended = () => { tocandoSons.delete(src); ganhosVivos.delete(vivo); };
}
function tocar(vel = 1) {
  if (!S.p) return; fecharPrevia(); S.vel = vel; if (vel > 0 && S.t >= duracao() - .03) S.t = 0;
  audioCtx(); S.tocando = true; S.ultimoSom = S.t - .001; S.relogio = performance.now(); exato.hidden = true; $("#st-tocar").textContent = "Pausar";
  for (const [f, i] of itens()) if (f.tipo === "audio" && !f.muda && i.ini < S.t && i.ini + i.dur > S.t + .1) tocarSom(i, f);
}
function pausar() { if (!S.tocando) return; S.tocando = false; S.vel = 1; $("#st-tocar").textContent = "Reproduzir"; tocandoSons.forEach((s) => { try { s.stop(); } catch {} }); tocandoSons.clear(); videos.forEach((v) => v.pause()); pedirExato(); }
function irPara(t) { S.t = lim(t, 0, duracao()); S.ultimoSom = S.t; exato.hidden = true; pedirPintura(); pedirExato(); moverAgulha(); atualizarCampos(); }
$("#st-tocar").addEventListener("click", () => (S.tocando ? pausar() : tocar()));
function vaivem(sentido) { const v = S.tocando && Math.sign(S.vel) === sentido ? lim(Math.abs(S.vel) * 2, 1, 8) * sentido : sentido; if (S.tocando) { S.vel = v; S.relogio = performance.now(); } else tocar(v); $("#st-selo").textContent = v === 1 ? "" : `${v > 0 ? "Avançando" : "Voltando"} ${Math.abs(v)}x`; }

/* ---------- Pintura da prévia ---------- */
let pintar = true; function pedirPintura() { pintar = true; }
function laco(agora) {
  requestAnimationFrame(laco);
  if (!S.aberto || $("#aba-editor").hidden || S.modo !== "video") { if (S.aberto && S.modo === "capa" && pintar) { pintar = false; pintarCapa(); } return; }
  if (S.tocando) {
    const dt = (agora - S.relogio) / 1000; S.relogio = agora; S.t += Math.min(.25, dt) * S.vel;
    if (S.t >= duracao()) { S.t = duracao(); pausar(); } else if (S.t <= 0) { S.t = 0; pausar(); }
    if (S.vel === 1) for (const [f, i] of itens()) if (f.tipo === "audio" && !f.muda && i.ini > S.ultimoSom && i.ini <= S.t) tocarSom(i, f);
    S.ultimoSom = S.t; atualizarGanhos(); moverAgulha(); atualizarCampos(); pintar = true;
  }
  sincronizarMidia();
  if (pintar) { pintar = false; pintarProjeto(); desenharAlca(); }
}
requestAnimationFrame(laco);
function ajustarTela() {
  const W = S.modo === "capa" ? S.capa?.largura : S.p?.largura, H = S.modo === "capa" ? S.capa?.altura : S.p?.altura; if (!W) return;
  const c = $("#st-tela").getBoundingClientRect(), e = Math.min(c.width / W, c.height / H), w = W * e, h = H * e;
  for (const n of [tela, exato, sobre]) Object.assign(n.style, { width: `${w}px`, height: `${h}px`, left: `${(c.width - w) / 2}px`, top: `${(c.height - h) / 2}px` });
  const r = Math.min(1, Math.max(.4, w * (devicePixelRatio || 1) / W)); if (tela.width !== Math.round(W * r)) { tela.width = Math.round(W * r); tela.height = Math.round(H * r); } S.escTela = r; pedirPintura(); desenharAlca();
}
new ResizeObserver(ajustarTela).observe($("#st-tela"));
function filtroCss(i) {
  const fil = i.filtro || S.p?.global?.filtro, a = i.ajustes || {}, css = [];
  const f = fil?.nome && S.filtros.find((x) => x.id === fil.nome); if (f && f.css !== "none") css.push(f.css);
  if (a.brilho) css.push(`brightness(${1 + a.brilho / 100})`); if (a.contraste) css.push(`contrast(${1 + a.contraste / 100})`); if (a.saturacao) css.push(`saturate(${1 + a.saturacao / 100})`);
  if (a.desfoque) css.push(`blur(${a.desfoque * S.escTela}px)`); return css.join(" ") || "none";
}
function desenharVisual(item, u, m = {}) {
  const v = (p) => val(item, p, u), e = v("escala") * (m.esc ?? 1), bw = v("w") * e, bh = v("h") * e, x = v("x") + (m.dx || 0), y = v("y") + (m.dy || 0), rot = v("rot") * Math.PI / 180, al = v("opac") / 100 * (m.al ?? 1);
  S.caixas.set(item.id, { x, y, w: bw, h: bh, rot });
  g.save(); g.translate(x, y); g.rotate(rot); g.globalAlpha = lim(al, 0, 1);
  if (item.tipo === "forma") {
    g.fillStyle = item.cor || "#FFC933"; g.globalAlpha *= (item.cor_opac ?? 100) / 100; g.beginPath();
    if (item.forma === "circulo") g.ellipse(0, 0, bw / 2, bh / 2, 0, 0, 7); else g.roundRect(-bw / 2, -bh / 2, bw, bh, Math.min(item.raio || 0, Math.min(bw, bh) / 2)); g.fill();
    if (item.borda) { g.strokeStyle = item.borda_cor || "#FFF"; g.lineWidth = item.borda; g.stroke(); } g.restore(); return;
  }
  const mid = S.p.midias[item.midia], src = mid?.tipo === "imagem" ? elImagem(item.midia, mid) : mid ? elVideo(item.midia) : null;
  const w = src?.videoWidth || src?.naturalWidth, h = src?.videoHeight || src?.naturalHeight;
  if (w) {
    const [cl, ct, cr, cb] = ["cl", "ct", "cr", "cb"].map(v), fx0 = cl, fx1 = Math.max(cl + .01, 1 - cr), fy0 = ct, fy1 = Math.max(ct + .01, 1 - cb), forca = (S.p.global.zoom_forca ?? 100) / 100 * (item.zoom_forca ?? 100) / 100;
    const z = Math.max(1, 1 + (v("zoom") - 1) * forca), lx = (fx1 - fx0) / z, ly = (fy1 - fy0) / z, zx = lim(fx0 + v("zx") * (fx1 - fx0), fx0 + lx / 2, fx1 - lx / 2), zy = lim(fy0 + v("zy") * (fy1 - fy0), fy0 + ly / 2, fy1 - ly / 2);
    g.filter = filtroCss(item); try { g.drawImage(src, (zx - lx / 2) * w, (zy - ly / 2) * h, lx * w, ly * h, -bw / 2, -bh / 2, bw, bh); } catch {}
  }
  g.restore();
}
function comTransicao(f, item, u) {
  const tr = item.transicao || {}, tipo = tr.tipo || "corte", d = tr.dur ?? .4;
  if (tipo === "corte" || u >= d || !["video", "imagem"].includes(item.tipo)) { desenharVisual(item, u); return; }
  const p = suave(lim(u / d, 0, 1)), a = f.itens.find((x) => x !== item && Math.abs(x.ini + x.dur - item.ini) < .08), ua = S.t - (a?.ini ?? 0), W = S.p.largura, H = S.p.altura;
  if (tipo === "dissolver") { if (a) desenharVisual(a, ua); desenharVisual(item, u, { al: p }); }
  else if (tipo === "preto" || tipo === "branco") { if (p < .5) { if (a) desenharVisual(a, ua); } else desenharVisual(item, u); g.fillStyle = tipo === "preto" ? "#000" : "#fff"; g.globalAlpha = p < .5 ? p * 2 : (1 - p) * 2; g.fillRect(0, 0, W, H); g.globalAlpha = 1; }
  else if (tipo === "zoom") { if (a) desenharVisual(a, ua); desenharVisual(item, u, { al: p, esc: 1.35 - .35 * p }); }
  else if (["chicote", "queda", "impulso", "giro", "glitch", "rgb", "clarao_rapido", "desfoque_rapido"].includes(tipo)) { if (p < .5 && a) desenharVisual(a, ua, { esc: 1 + p * .5 }); else desenharVisual(item, u, { esc: 1 + (1 - p) * .5 }); }
  else { const [dx, dy] = { esquerda: [W, 0], direita: [-W, 0], cima: [0, H], baixo: [0, -H] }[tipo] || [0, 0]; if (a) desenharVisual(a, ua, { dx: -dx * p, dy: -dy * p }); desenharVisual(item, u, { dx: dx * (1 - p), dy: dy * (1 - p) }); }
}
function animar(est, u, dur) {
  const r = { al: 1, dx: 0, dy: 0, esc: 1, mostrar: 1 }, tempo = Math.max(.01, est.tempo_anim);
  for (const [tipo, p] of [[est.entrada, Math.min(1, u / tempo)], [est.saida, Math.min(1, (dur - u) / tempo)]]) {
    if (p >= 1 || tipo === "nenhuma") continue; const e = 1 - (1 - p) ** 3;
    if (tipo === "fade") r.al *= p; else if (tipo === "pop") { r.esc *= .7 + .3 * (e + Math.sin(p * Math.PI) * .12); r.al *= Math.min(1, p * 2); }
    else if (tipo === "zoom") { r.esc *= 1.5 - .5 * e; r.al *= p; } else if (tipo === "subir") { r.dy += (1 - e) * 60; r.al *= p; } else if (tipo === "descer") { r.dy -= (1 - e) * 60; r.al *= p; }
    else if (tipo === "esquerda") { r.dx += (1 - e) * 90; r.al *= p; } else if (tipo === "direita") { r.dx -= (1 - e) * 90; r.al *= p; }
    else if (tipo === "quique") { r.esc *= 1 + Math.sin(p * Math.PI * 2.5) * (1 - p) * .35; r.al *= Math.min(1, p * 3); } else if (tipo === "digitando") r.mostrar = Math.min(r.mostrar, p);
  }
  return r;
}
const EF_TEXTO = [["nenhum", "Sem efeito"], ["neon", "Neon"], ["brilho", "Brilho"], ["reflexo", "Reflexo"], ["ouro", "Ouro"], ["fogo", "Fogo"], ["gelo", "Gelo"], ["arcoiris", "Arco-íris"], ["glitch", "Glitch"], ["rgb", "Cores separadas"], ["onda", "Onda"], ["pulsar", "Pulsar"], ["batida", "Batida"], ["tremer", "Tremer"], ["balancar", "Balançar"], ["flutuar", "Flutuar"], ["piscar", "Piscar"]];
function movTexto(est, u) {
  const r = { dx: 0, dy: 0, esc: 1, rot: 0, al: 1 }, f = (est.efeito_forca ?? 100) / 100, t = est.tamanho, tipo = est.efeito_texto, T = Math.PI * 2;
  if (tipo === "pulsar") r.esc = 1 + .07 * f * Math.sin(u * T * 1.6);
  else if (tipo === "batida") { const a = (u * 1.5) % 1; r.esc = 1 + .16 * f * (Math.exp(-a * 9) + (a > .24 ? .55 * Math.exp(-(a - .24) * 11) : 0)); }
  else if (tipo === "tremer") { const n = Math.floor(u * 24); r.dx = t * .05 * f * Math.sin(n * 12.9898); r.dy = t * .05 * f * Math.sin(n * 78.233); }
  else if (tipo === "balancar") r.rot = 5 * f * Math.sin(u * T * .9); else if (tipo === "flutuar") r.dy = t * .14 * f * Math.sin(u * T * .7);
  else if (tipo === "piscar") r.al = Math.sin(u * T * 3) < -.2 ? 1 - Math.min(1, f) * .75 : 1;
  return r;
}
function tintaTexto(est, u, lar, alt) {
  const faixa = (pares) => { const d = g.createLinearGradient(0, -alt / 2, 0, alt / 2); pares.forEach(([p, c]) => d.addColorStop(p, c)); return d; };
  if (est.efeito_texto === "ouro") return faixa([[.2, "#fff7be"], [.5, "#f5be46"], [.85, "#a8660f"]]); if (est.efeito_texto === "gelo") return faixa([[.25, "#ffffff"], [.8, "#6ed7ff"]]); if (est.efeito_texto === "fogo") return faixa([[.2, "#ff3c14"], [.55, "#ff9619"], [.85, "#ffeb78"]]);
  if (est.efeito_texto === "arcoiris") { const d = g.createLinearGradient(-lar / 2, 0, lar / 2, 0); for (let n = 0; n <= 6; n++) d.addColorStop(n / 6, `hsl(${(n * 60 + u * 160) % 360} 90% 60%)`); return d; }
  return null;
}
function desenharTexto(txt, est, x, y, esc, rot, al, ativa, u = 0) {
  g.save(); g.font = `${est.tamanho}px ${fonteCss(est.fonte)}`; g.textBaseline = "alphabetic"; g.letterSpacing = `${est.espacamento}px`;
  const vazio = g.measureText(" ").width, linhas = []; let n = 0;
  for (const bloco of String(txt).split("\n")) { let at = [], us = 0; for (const b of bloco.split(/\s+/).filter(Boolean)) { const q = est.maiusculas ? b.toLocaleUpperCase("pt-BR") : b, w = g.measureText(q).width; if (at.length && us + vazio + w > est.largura) { linhas.push(at); at = []; us = 0; } us += (at.length ? vazio : 0) + w; at.push({ q, w, n: n++ }); } linhas.push(at); }
  const passo = est.tamanho * est.entrelinha / 100, altT = est.tamanho * 1.5 + passo * (linhas.length - 1), largs = linhas.map((l) => l.reduce((s, p) => s + p.w, 0) + vazio * Math.max(0, l.length - 1)), lar = Math.max(1, ...largs), pad = est.fundo ? est.fundo_pad : 0, h = altT + pad * 2;
  const cy = y + (est.ancora === "topo" ? h / 2 : est.ancora === "base" ? -h / 2 : 0);
  g.translate(x, cy); g.rotate(rot * Math.PI / 180); g.scale(esc, esc); g.globalAlpha = lim(al * est.opacidade / 100, 0, 1);
  if (est.fundo) { g.fillStyle = est.fundo_cor; const a0 = g.globalAlpha; g.globalAlpha = a0 * est.fundo_opac / 100; g.beginPath(); g.roundRect(-lar / 2 - pad, -h / 2, lar + pad * 2, h, est.fundo_raio); g.fill(); g.globalAlpha = a0; if (est.borda) { g.strokeStyle = est.borda_cor; g.lineWidth = est.borda; g.stroke(); } }
  if (est.sombra) { g.shadowColor = est.sombra_cor + Math.round(est.sombra_opac * 2.55).toString(16).padStart(2, "0"); g.shadowBlur = est.sombra_blur * 2 * S.escTela; g.shadowOffsetX = est.sombra_x * S.escTela; g.shadowOffsetY = est.sombra_y * S.escTela; }
  const fxT = est.efeito_texto, fxF = (est.efeito_forca ?? 100) / 100, tinta = tintaTexto(est, u, lar, altT), desvio = fxT === "rgb" || fxT === "glitch" ? est.tamanho * .06 * fxF : 0;
  if (fxT === "neon" || fxT === "brilho" || fxT === "fogo" || fxT === "gelo") { g.shadowColor = fxT === "neon" ? est.cor_destaque : fxT === "brilho" ? est.cor : fxT === "fogo" ? "#ff5a0f" : "#5ac8ff"; g.shadowBlur = est.tamanho * .5 * fxF * S.escTela; g.shadowOffsetX = 0; g.shadowOffsetY = 0; }
  g.lineJoin = "round"; linhas.forEach((l, i) => {
    let px = -lar / 2 + (est.alinhamento === "esquerda" ? 0 : est.alinhamento === "direita" ? lar - largs[i] : (lar - largs[i]) / 2); const py = -altT / 2 + est.tamanho * 1.1 + passo * i;
    for (const p of l) { const py0 = py;
      const atv = ativa === p.n && ["palavra", "ambos"].includes(est.destaque), imp = ["importantes", "ambos"].includes(est.destaque) && (FORTES.test(p.q) || /[!?]$/.test(p.q));
      if (est.destaque_caixa && ativa === p.n) { g.fillStyle = est.cor_destaque; g.beginPath(); g.roundRect(px - est.tamanho * .14, py - est.tamanho * 1.02, p.w + est.tamanho * .28, est.tamanho * 1.34, est.tamanho * .16); g.fill(); }
      if (est.contorno && !(est.destaque_caixa && ativa === p.n)) { g.strokeStyle = est.contorno_cor; g.lineWidth = est.contorno * 2; g.strokeText(p.q, px, py); }
      if (desvio) { g.fillStyle = "#ff2a55"; g.fillText(p.q, px + desvio, py0); g.fillStyle = "#22e0ff"; g.fillText(p.q, px - desvio, py0); }
      g.fillStyle = tinta || (atv ? (est.destaque_caixa ? "#141414" : est.cor_destaque) : imp ? est.cor_destaque : est.cor); g.fillText(p.q, px, fxT === "onda" ? py0 + Math.sin(px / (est.tamanho * 1.1) - u * 6) * est.tamanho * .13 * fxF : py0); px += p.w + vazio;
    }
  });
  g.restore(); return { x, y: cy, w: (lar + pad * 2 + est.contorno * 2) * esc, h: h * esc, rot };
}
function pintarItemTexto(i, u) {
  const est = estiloDe(i), an = animar(est, u, i.dur); let txt = i.texto || "", ativa = null;
  if (i.palavras?.length) { i.palavras.forEach((p, n) => { if (u >= p.ini) ativa = n; }); ativa ??= 0; if (est.palavra_a_palavra) { txt = i.palavras[ativa].p; ativa = 0; } }
  if (an.mostrar < 1) txt = txt.slice(0, Math.round(txt.length * an.mostrar));
  const leg = i.tipo === "legenda", x = leg ? est.x ?? S.p.largura / 2 : val(i, "x", u), y = leg ? est.y ?? S.p.altura * .86 : val(i, "y", u);
  const mv = movTexto(est, u);
  S.caixas.set(i.id, desenharTexto(txt, est, x + an.dx + mv.dx, y + an.dy + mv.dy, (leg ? 1 : val(i, "escala", u)) * an.esc * mv.esc, (leg ? 0 : val(i, "rot", u)) + mv.rot, an.al * mv.al * (leg ? 1 : val(i, "opac", u) / 100), ativa, u));
}
function pintarEfeito(i, u) {
  const W = S.p.largura, H = S.p.altura, [ax, ay, aw, ah] = i.area || [0, 0, W, H], f = i.forca ?? 1;
  let k = 0, cor = "#fff";
  if (i.efeito === "clarao") k = f * Math.exp(-u * 13); else if (i.efeito === "escurecer") { k = f * u / i.dur; cor = "#000"; } else if (i.efeito === "clarear") { k = f * (1 - u / i.dur); cor = "#000"; }
  else if (i.efeito === "progresso") { g.fillStyle = i.cor || "#FFC933"; g.fillRect(0, 0, W * (i.ini + u) / duracao(), 9); return; }
  else if (i.efeito === "vinheta") { const gr = g.createRadialGradient(W / 2, H / 2, Math.min(W, H) * .35, W / 2, H / 2, Math.max(W, H) * .7); gr.addColorStop(0, "rgba(0,0,0,0)"); gr.addColorStop(1, `rgba(0,0,0,${.42 * f * suave(lim(Math.min(u / .2, (i.dur - u) / .3), 0, 1))})`); g.fillStyle = gr; g.fillRect(0, 0, W, H); return; }
  if (k > .01) { g.globalAlpha = lim(k, 0, 1); g.fillStyle = cor; g.fillRect(ax, ay, aw, ah); g.globalAlpha = 1; }
}
function pintarProjeto() {
  g.setTransform(S.escTela, 0, 0, S.escTela, 0, 0); g.filter = "none"; g.globalAlpha = 1; g.fillStyle = "#000"; g.fillRect(0, 0, S.p.largura, S.p.altura); S.caixas.clear();
  for (const f of S.p.faixas) { if (f.oculta || f.tipo === "audio") continue;
    for (const i of f.itens) { if (S.t < i.ini || S.t >= i.ini + i.dur) continue; const u = S.t - i.ini; if (["video", "imagem", "forma"].includes(i.tipo)) comTransicao(f, i, u); else if (["texto", "legenda"].includes(i.tipo)) pintarItemTexto(i, u); else if (i.tipo === "efeito") pintarEfeito(i, u); } }
  $("#st-tempo").textContent = `${tempoTxt(S.t)} / ${tempoTxt(duracao())}`;
}
/* Quadro exato: o mesmo motor da exportação, usado sempre que a prévia está parada. */
let tempoExato, seqExato = 0;
function pedirExato() {
  clearTimeout(tempoExato); exato.hidden = true; $("#st-selo").textContent = ""; if (S.tocando || !S.aberto) return;
  tempoExato = setTimeout(async () => {
    const n = ++seqExato, capa = S.modo === "capa";
    try {
      const url = capa ? "/api/estudio/capa/quadro" : `/api/estudio/${S.tipo}/${S.id}/quadro`, corpo = capa ? { capa: S.capa, escala: 1 } : { projeto: S.p, t: S.t, altura: 1920 };
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) }); if (!r.ok || n !== seqExato || S.tocando) return;
      const blob = await r.blob(); if (n !== seqExato) return; URL.revokeObjectURL(exato.src); exato.src = URL.createObjectURL(blob); exato.hidden = false; $("#st-selo").textContent = "Prévia igual ao vídeo final";
    } catch {}
  }, 260);
}

/* ---------- Manipular direto na prévia ---------- */
const cap = () => S.modo === "capa";
const objSel = () => cap() ? S.capa.camadas.find((c) => S.sel.has(c.id)) : sel1();
const lerP = (o, p) => cap() ? o[p] ?? PAD_T[p] : o.tipo === "legenda" ? estiloDe(o)[p] : val(o, p, local(o));
function porP(o, p, v) { if (cap()) o[p] = v; else if (o.tipo === "legenda") (o.estilo ||= {})[p] = v; else porProp(o, p, v); }
function desenharAlca() {
  sobre.replaceChildren(); const o = objSel(), b = o && S.caixas.get(o.id); if (!b) return;
  const W = tela.clientWidth / (cap() ? S.capa.largura : S.p.largura), n = el("div", { class: "st-alca", style: `left:${(b.x - b.w / 2) * W}px;top:${(b.y - b.h / 2) * W}px;width:${b.w * W}px;height:${b.h * W}px;transform:rotate(${b.rot || 0}deg)` });
  if (cap() || o.tipo !== "legenda") { for (const [a, l, t] of [["nw", 0, 0], ["ne", 100, 0], ["sw", 0, 100], ["se", 100, 100]]) n.append(el("i", { dados: { a }, style: `left:${l}%;top:${t}%` })); n.append(el("i", { dados: { a: "rot" } })); }
  sobre.append(n);
}
function pontoCena(ev) { const r = sobre.getBoundingClientRect(), W = cap() ? S.capa.largura : S.p.largura, H = cap() ? S.capa.altura : S.p.altura; return [(ev.clientX - r.left) / r.width * W, (ev.clientY - r.top) / r.height * H]; }
function noPonto(x, y) {
  const lista = cap() ? [...S.capa.camadas].filter((c) => !c.travada && !c.oculta).map((c) => c.id) : S.p.faixas.filter((f) => !f.travada && !f.oculta && f.tipo !== "efeito" && f.tipo !== "audio").flatMap((f) => f.itens.map((i) => i.id));
  for (const id of lista.reverse()) { const b = S.caixas.get(id); if (!b) continue; const a = -(b.rot || 0) * Math.PI / 180, dx = x - b.x, dy = y - b.y, lx = dx * Math.cos(a) - dy * Math.sin(a), ly = dx * Math.sin(a) + dy * Math.cos(a); if (Math.abs(lx) <= b.w / 2 && Math.abs(ly) <= b.h / 2) return id; }
  return null;
}
let gesto = null;
sobre.addEventListener("pointerdown", (ev) => {
  pausar(); const [x, y] = pontoCena(ev), alca = ev.target.dataset?.a;
  if (!alca) { const id = noPonto(x, y); if (S.sel.size !== 1 || !S.sel.has(id)) { S.sel.clear(); if (id) S.sel.add(id); selecaoMudou(); } }
  const o = objSel(); if (!o) return; const b = S.caixas.get(o.id); if (!b) return;
  gesto = { o, alca, x0: x, y0: y, px: lerP(o, "x"), py: lerP(o, "y"), esc: cap() ? o.escala ?? 1 : o.tipo === "legenda" ? estiloDe(o).tamanho : lerP(o, "escala"), rot: lerP(o, "rot") || 0, d0: Math.hypot(x - b.x, y - b.y) || 1, a0: Math.atan2(y - b.y, x - b.x), cx: b.x, cy: b.y, feito: false, zx: !cap() && o.tipo === "video" ? lerP(o, "zx") : 0, zy: !cap() && o.tipo === "video" ? lerP(o, "zy") : 0 };
  sobre.setPointerCapture(ev.pointerId);
});
sobre.addEventListener("pointermove", (ev) => {
  if (!gesto) return; const [x, y] = pontoCena(ev), g0 = gesto, W = cap() ? S.capa.largura : S.p.largura, H = cap() ? S.capa.altura : S.p.altura;
  if (!g0.feito) { if (Math.hypot(x - g0.x0, y - g0.y0) < W / 300) return; antes(); g0.feito = true; }
  if (g0.alca === "rot") { let r = g0.rot + (Math.atan2(y - g0.cy, x - g0.cx) - g0.a0) * 180 / Math.PI; if (Math.abs(r % 90) < 3) r = Math.round(r / 90) * 90; porP(g0.o, "rot", arred(r, 1)); }
  else if (g0.alca) { const f = Math.hypot(x - g0.cx, y - g0.cy) / g0.d0; if (!cap() && g0.o.tipo === "legenda") (g0.o.estilo ||= {}).tamanho = Math.round(g0.esc * f); else porP(g0.o, "escala", arred(lim(g0.esc * f, .05, 12))); }
  else if ((S.zoomMao || S.ponto?.id === g0.o.id) && !cap() && g0.o.tipo === "video") { const z = Math.max(1, val(g0.o, "zoom", local(g0.o))); porProp(g0.o, "zx", arred(lim(g0.zx - (x - g0.x0) / (val(g0.o, "w", 0) * z), 0, 1), 4)); porProp(g0.o, "zy", arred(lim(g0.zy - (y - g0.y0) / (val(g0.o, "h", 0) * z), 0, 1), 4)); }
  else { let nx = g0.px + x - g0.x0, ny = g0.py + y - g0.y0; sobre.querySelectorAll(".st-guia").forEach((n) => n.remove()); const m = W / 90; if (Math.abs(nx - W / 2) < m) nx = W / 2; if (Math.abs(ny - H / 2) < m) ny = H / 2; porP(g0.o, "x", arred(nx, 1)); porP(g0.o, "y", arred(ny, 1)); }
  exato.hidden = true; pedirPintura(); if (cap()) pintarCapa(); atualizarCampos();
});
const fimGesto = () => { if (gesto?.feito) mudou(); gesto = null; };
sobre.addEventListener("pointerup", fimGesto); sobre.addEventListener("pointercancel", fimGesto);
sobre.addEventListener("wheel", (ev) => { const o = sel1(); if (!S.zoomMao || !o || o.tipo !== "video") return; ev.preventDefault(); antes(); porProp(o, "zoom", arred(lim(val(o, "zoom", local(o)) * (ev.deltaY < 0 ? 1.06 : .94), 1, 6), 3)); mudou(); atualizarCampos(); }, { passive: false });

/* ---------- Timeline ---------- */
const larguraT = () => (duracao() + 8) * S.px;
function ajustarZoom() { S.px = lim((rolagem.clientWidth - 30) / duracao(), 1, 300); rolagem.scrollLeft = 0; desenharLinha(); }
function zoomT(f) { const c = S.t; S.px = lim(S.px * f, .4, 400); desenharLinha(); rolagem.scrollLeft = c * S.px - rolagem.clientWidth / 2; }
$("#st-mais").addEventListener("click", () => zoomT(1.5)); $("#st-menos").addEventListener("click", () => zoomT(1 / 1.5)); $("#st-ajustar").addEventListener("click", ajustarZoom);
rolagem.addEventListener("scroll", () => { $("#st-cab-caixa").scrollTop = rolagem.scrollTop; desenharLinha(); }, { passive: true });
$("#st-cab-caixa").addEventListener("wheel", (ev) => { rolagem.scrollTop += ev.deltaY; ev.preventDefault(); }, { passive: false });
function alturaFaixas(v) { S.altFaixa = lim(v, .6, 2.6); $("#st-alt-faixa").value = Math.round(S.altFaixa * 100); try { localStorage.setItem("st-alt-faixa", S.altFaixa); } catch {} montarCabecas(); desenharLinha(); }
$("#st-alt-faixa").addEventListener("input", (ev) => alturaFaixas(ev.target.value / 100));
function alturaLinha(px) { const h = lim(px, 110, innerHeight * .75); $("#st-mesa").style.setProperty("--st-altura", `${h}px`); try { localStorage.setItem("st-altura", h); } catch {} desenharLinha(); }
{ const d = $("#st-divisor"); let ini = null;
  d.addEventListener("pointerdown", (ev) => { ini = { y: ev.clientY, h: $(".st-corpo").offsetHeight }; d.setPointerCapture(ev.pointerId); });
  d.addEventListener("pointermove", (ev) => { if (ini) alturaLinha(ini.h + ini.y - ev.clientY); }); d.addEventListener("pointerup", () => (ini = null)); d.addEventListener("pointercancel", () => (ini = null));
  d.addEventListener("keydown", (ev) => { if (ev.key === "ArrowUp" || ev.key === "ArrowDown") { ev.preventDefault(); ev.stopPropagation(); alturaLinha($(".st-corpo").offsetHeight + (ev.key === "ArrowUp" ? 30 : -30)); } }); }
try { const a = +localStorage.getItem("st-altura"), b = +localStorage.getItem("st-alt-faixa"); if (a) $("#st-mesa").style.setProperty("--st-altura", `${a}px`); if (b) { S.altFaixa = b; $("#st-alt-faixa").value = Math.round(b * 100); } } catch {}
rolagem.addEventListener("wheel", (ev) => { if (ev.ctrlKey || ev.metaKey) { ev.preventDefault(); zoomT(ev.deltaY < 0 ? 1.2 : 1 / 1.2); } else if (ev.altKey) { ev.preventDefault(); alturaFaixas(S.altFaixa + (ev.deltaY < 0 ? .1 : -.1)); } }, { passive: false });
let linhaPedida = false; function desenharLinha() { if (linhaPedida || !S.aberto || cap()) return; linhaPedida = true; requestAnimationFrame(() => { linhaPedida = false; montarLinha(); }); }
function montarCabecas() {
  const ordem = [...S.p.faixas].reverse();
  $("#st-cabecas").replaceChildren(...ordem.map((f) => { const ci = S.p.faixas.indexOf(f);
    const b = (txt, tit, on, fn) => { const n = el("button", { type: "button", title: tit, "aria-label": tit, dados: on ? { on: "1" } : {}, onclick: fn }); n.innerHTML = ICONES[txt] || txt; return n; };
    return el("div", { class: "st-cab", style: `height:${altF(f)}px`, title: "Arraste para mudar a ordem. No teclado: Alt + seta para cima ou para baixo", tabindex: "0", onkeydown: (ev) => { if (ev.altKey && (ev.key === "ArrowUp" || ev.key === "ArrowDown")) { ev.preventDefault(); ev.stopPropagation(); moverFaixa(ci, ev.key === "ArrowUp" ? 1 : -1); $(`#st-cabecas .st-cab:nth-child(${S.p.faixas.length - S.p.faixas.indexOf(f)})`)?.focus(); } }, dados: { tipo: f.tipo, ci } }, el("span", { class: "st-alca", "aria-hidden": "true" }), el("b", { title: f.nome }, f.nome),
      f.tipo === "audio" ? b("som", "Silenciar faixa", f.muda, () => { antes(); f.muda = !f.muda; mudou(); montarCabecas(); }) : b("olho", "Esconder faixa", f.oculta, () => { antes(); f.oculta = !f.oculta; mudou(); montarCabecas(); }),
      b("trava", "Travar faixa", f.travada, () => { antes(); f.travada = !f.travada; mudou(); montarCabecas(); }), b("×", "Apagar faixa", false, () => { antes(); S.p.faixas.splice(ci, 1); mudou(true); montarCabecas(); })); }));
}
{ // arrastar a faixa pelo nome para subir ou descer
  let ar = null; const cabs = $("#st-cabecas");
  const alvo = (y) => { const l = [...cabs.querySelectorAll(".st-cab")]; let n = l.length; for (const [k, c] of l.entries()) { const r = c.getBoundingClientRect(); if (y < r.top + r.height / 2) { n = k; break; } } return n; };
  const linha = (n) => { const l = [...cabs.querySelectorAll(".st-cab")], cx = cabs.getBoundingClientRect(), r = n < l.length ? l[n].getBoundingClientRect().top : l[l.length - 1].getBoundingClientRect().bottom; ar.marca.style.top = `${r - cx.top - 1}px`; };
  cabs.addEventListener("pointerdown", (ev) => { const c = ev.target.closest(".st-cab"); if (!c || ev.button !== 0 || ev.target.closest("button")) return; ev.preventDefault(); ar = { c, y0: ev.clientY, de: [...cabs.children].indexOf(c), ativo: false, marca: el("i", { class: "st-cab-linha" }) }; cabs.setPointerCapture(ev.pointerId); });
  cabs.addEventListener("pointermove", (ev) => { if (!ar) return; if (!ar.ativo) { if (Math.abs(ev.clientY - ar.y0) < 4) return; ar.ativo = true; ar.c.dataset.arrastando = "1"; cabs.dataset.arrastando = "1"; cabs.append(ar.marca); } ar.para = alvo(ev.clientY); linha(ar.para); });
  const soltar = () => { if (!ar) return; const { ativo, de, para } = ar; ar.marca.remove(); delete cabs.dataset.arrastando; delete ar.c.dataset.arrastando; ar = null; if (!ativo || para == null) return;
    const ordem = [...S.p.faixas].reverse(), f = ordem[de], destino = para > de ? para - 1 : para; if (destino === de) return; antes(); ordem.splice(de, 1); ordem.splice(destino, 0, f); S.p.faixas = ordem.reverse(); mudou(true); montarCabecas(); };
  cabs.addEventListener("pointerup", soltar); cabs.addEventListener("pointercancel", soltar);
}
function moverFaixa(i, d) { const j = i + d; if (j < 0 || j >= S.p.faixas.length) return; antes(); [S.p.faixas[i], S.p.faixas[j]] = [S.p.faixas[j], S.p.faixas[i]]; mudou(); montarCabecas(); }
/* ---------- Pontos de animação, como no CapCut ---------- */
const PROPS_ZOOM = ["zoom", "zx", "zy"];
function pontosDe(i) {
  const m = new Map();
  for (const [p, c] of Object.entries(i.kf || {})) for (const k of c) { if (k.t < -.001 || k.t > i.dur + .001) continue; const t = [...m.keys()].find((x) => Math.abs(x - k.t) < .02) ?? k.t; if (!m.has(t)) m.set(t, []); m.get(t).push([p, k]); }
  return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([t, ks]) => ({ t, ks }));
}
function pontoAtual() { if (!S.ponto) return null; const [, i] = achar(S.ponto.id), c = i && pontosDe(i).find((x) => Math.abs(x.t - S.ponto.t) < .02); return c ? { i, c } : null; }
function selecionarPonto(i, t) { pausar(); S.ponto = { id: i.id, t }; irPara(i.ini + t); montarInspetor(); desenharLinha(); }
function moverPonto(i, chaves, t) { for (const k of chaves) k.t = t; for (const c of Object.values(i.kf)) c.sort((a, b) => a.t - b.t); S.ponto = { id: i.id, t }; irPara(i.ini + t); mudou(); desenharLinha(); }
function fixarChave(i, p, t, v) { i.kf ||= {}; const c = i.kf[p] ||= [], k = c.find((x) => Math.abs(x.t - t) < .02); if (k) k.v = v; else { c.push({ t, v, e: "suave" }); c.sort((a, b) => a.t - b.t); } }
function apagarChaves(i, ks) { for (const [p, k] of ks) { const c = i.kf[p]; c.splice(c.indexOf(k), 1); if (!c.length) { delete i.kf[p]; (i.t ||= {})[p] = p === "zoom" ? 1 : k.v; } } }
function apagarPonto() { const a = pontoAtual(); if (!a) return; antes(); apagarChaves(a.i, a.c.ks); S.ponto = null; mudou(true); selecaoMudou(); }
function adicionarPonto(i) { const u = arred(local(i)), ja = pontosDe(i).find((x) => Math.abs(x.t - u) < .02); if (!ja) { antes(); const v = PROPS_ZOOM.map((p) => arred(val(i, p, u), 4)); PROPS_ZOOM.forEach((p, n) => fixarChave(i, p, u, v[n])); mudou(true); } selecionarPonto(i, ja?.t ?? u); }
function secPontos(i) {
  const lista = pontosDe(i).filter((c) => c.ks.some(([p]) => PROPS_ZOOM.includes(p))), a = pontoAtual(), atual = a?.i === i ? a.c : null;
  const linhas = lista.map((c) => { const sel = atual?.t === c.t; return el("li", { dados: sel ? { sel: "1" } : {} }, el("button", { class: "st-pz-ir", type: "button", "aria-pressed": String(sel), onclick: () => selecionarPonto(i, c.t) }, el("span", {}, tempoTxt(c.t)), (() => { const z = el("b"), ver = () => { z.textContent = `${String(arred(val(i, "zoom", c.t), 2)).replace(".", ",")}×`; }; vivos.push(ver); ver(); return z; })()), el("button", { class: "st-pz-x", type: "button", title: "Apagar ponto", "aria-label": `Apagar ponto em ${tempoTxt(c.t)}`, onclick: () => { S.ponto = { id: i.id, t: c.t }; apagarPonto(); } }, "×")); });
  const blocos = [el("div", { class: "st-botoes" }, btn("Adicionar ponto aqui", () => adicionarPonto(i), "botao destaque"))];
  if (lista.length) blocos.push(el("ul", { class: "st-pz" }, ...linhas)); else blocos.push(el("p", { class: "dica" }, "Leve a agulha até o momento do zoom e adicione um ponto."));
  if (atual) { const t = () => S.ponto.t, sel = el("select", { "aria-label": "Curva" }, ...[["suave", "Suave"], ["linear", "Constante"], ["degrau", "Sem animação"]].map(([v, r]) => el("option", { value: v }, r))); sel.value = atual.ks[0][1].e || "linear"; sel.addEventListener("change", () => { antes(); const c = pontoAtual()?.c; c?.ks.forEach(([, k]) => { k.e = sel.value; }); mudou(); });
    const l = pontosDe(i), n = l.findIndex((x) => x.t === atual.t), de = n > 0 ? l[n - 1].t + .04 : 0, ate = n < l.length - 1 ? l[n + 1].t - .04 : i.dur, chaves = atual.ks.map(([, k]) => k), ed = (p) => ({ get: () => val(i, p, t()), set: (v) => { fixarChave(i, p, t(), v); desenharLinha(); queueMicrotask(atualizarCampos); } });
    blocos.push(el("div", { class: "st-pz-ed" }, campo("Momento", { get: t, set: (v) => moverPonto(i, chaves, lim(arred(v), de, Math.max(de, ate))), min: de, max: Math.max(de, ate), step: .01 }), campo("Zoom", { ...ed("zoom"), min: 1, max: 5, step: .01 }), campo("Foco X", { ...ed("zx"), min: 0, max: 1, step: .005 }), campo("Foco Y", { ...ed("zy"), min: 0, max: 1, step: .005 }), linha("Curva", sel), btn("Apagar este ponto", apagarPonto), el("p", { class: "dica" }, "Arraste o vídeo na prévia para mudar o foco."))); }
  if (lista.length) blocos.push(btn("Apagar todos os pontos de zoom", () => { antes(); for (const p of PROPS_ZOOM) if (i.kf) delete i.kf[p]; i.t.zoom = 1; S.ponto = null; mudou(true); selecaoMudou(); }));
  return sec(`Pontos de zoom${lista.length ? ` (${lista.length})` : ""}`, ...blocos);
}
function montarLinha() {
  const W = rolagem.clientWidth, esq = rolagem.scrollLeft, de = esq / S.px - 2, ate = (esq + W) / S.px + 2;
  faixasEl.style.width = `${larguraT()}px`;
  trilhas.replaceChildren(...[...S.p.faixas].reverse().map((f) => {
    const n = el("div", { class: "st-trilha", style: `height:${altF(f)}px`, dados: { f: f.id, ...(f.oculta ? { oculta: "1" } : {}) } });
    for (const i of f.itens) { if (i.ini + i.dur < de || i.ini > ate) continue;
      const s = S.sel.has(i.id), b = el("div", { class: `st-bl ${i.tipo}${s ? " sel" : ""}${s && arr?.modo === "mover" && arr.feito ? " arrastando" : ""}`, style: `left:${i.ini * S.px}px;width:${Math.max(3, i.dur * S.px)}px`, title: rotuloItem(i), dados: { i: i.id } }, el("span", {}, rotuloItem(i)));
      if (s && !f.travada && i.dur * S.px >= 30) b.append(el("em", { class: "a", dados: { b: "a" } }), el("em", { class: "b", dados: { b: "b" } }));
      if (s && i.tipo === "audio" && !f.travada) { const h = altF(f), vol = i.volume ?? 100, fi = +i.fade_in || 0, fo = +i.fade_out || 0;
        b.append(el("i", { class: "st-vol", title: `Volume ${Math.round(vol)}%. Arraste para cima ou para baixo.`, style: `top:${4 + (1 - Math.min(200, vol) / 200) * (h - 8)}px`, dados: { vol: "1" } }),
          el("i", { class: "st-fade", title: `Entrada suave: ${String(arred(fi)).replace(".", ",")} s. Arraste para os lados.`, style: `left:${fi * S.px}px`, dados: { fade: "in" } }),
          el("i", { class: "st-fade", title: `Saída suave: ${String(arred(fo)).replace(".", ",")} s. Arraste para os lados.`, style: `left:${(i.dur - fo) * S.px}px`, dados: { fade: "out" } })); }
      if (s) for (const c of pontosDe(i)) b.append(el("button", { class: "st-pt", type: "button", title: `Ponto em ${tempoTxt(c.t)}. Arraste para mover, Delete para apagar.`, "aria-label": `Ponto em ${tempoTxt(c.t)}`, style: `left:${c.t * S.px}px`, dados: { pt: c.t, ...(S.ponto?.id === i.id && Math.abs(S.ponto.t - c.t) < .02 ? { sel: "1" } : {}) } }));
      if (i.transicao?.tipo && i.transicao.tipo !== "corte") b.append(el("s", { style: `width:${i.transicao.dur * S.px}px` }));
      n.append(b);
      if (f.tipo === "video" && ehCorte(f, i)) { const tr = i.transicao?.tipo && i.transicao.tipo !== "corte", nome = tr ? nomeTr(i.transicao.tipo) : "Adicionar transição"; const m = el("button", { class: "st-tr", type: "button", title: nome, "aria-label": `${nome} em ${tempoTxt(i.ini)}`, style: `left:${i.ini * S.px}px`, dados: { t: i.ini, ...(tr ? { on: "1" } : {}) } }); m.innerHTML = svg('<path d="M4 5l8 7-8 7zM20 5l-8 7 8 7z"/>'); n.append(m); } }
    if (S.alvoF === f.id) n.dataset.alvo = "1";
    return n; }));
  const alt = trilhas.scrollHeight, d = devicePixelRatio || 1, topo = $("#st-regua-topo"); regua.width = W * d; regua.height = alt * d; regua.style.width = `${W}px`; regua.style.height = `${alt}px`; regua.style.left = `${esq}px`;
  topo.width = W * d; topo.height = 24 * d; topo.style.width = `${W}px`; topo.style.height = "24px";
  const r0 = topo.getContext("2d"); r0.scale(d, d); r0.fillStyle = "#0b1518"; r0.fillRect(0, 0, W, 24); r0.font = "11px 'Instrument Sans',sans-serif"; r0.fillStyle = "#a6babc"; r0.strokeStyle = "#2c444e";
  const passo = [.1, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((p) => p * S.px >= 64) || 1200;
  for (let t = Math.floor(esq / S.px / passo) * passo; t * S.px < esq + W; t += passo) { const x = t * S.px - esq; r0.beginPath(); r0.moveTo(x + .5, 16); r0.lineTo(x + .5, 24); r0.stroke(); r0.fillText(passo < 1 ? tempoTxt(t) : relogio(t), x + 3, 13); }
  r0.fillStyle = "#5ad1b3"; for (const m of S.p.marcadores || []) { const x = m * S.px - esq; r0.beginPath(); r0.moveTo(x - 5, 14); r0.lineTo(x + 5, 14); r0.lineTo(x, 23); r0.fill(); }
  const c = regua.getContext("2d"); c.scale(d, d);
  let y = 0; c.fillStyle = "rgba(255,255,255,.42)";
  for (const f of [...S.p.faixas].reverse()) { const h = altF(f);
    if (["video", "audio"].includes(f.tipo)) for (const i of f.itens) { if (i.mudo || i.tipo === "imagem" || i.tipo === "forma" || i.ini + i.dur < de || i.ini > ate) continue; const m = S.p.midias[i.midia], o = m && ondaDe(m); if (!o?.length || !m.dur) continue;
      const x0 = Math.max(0, i.ini * S.px - esq), x1 = Math.min(W, (i.ini + i.dur) * S.px - esq); const aud = i.tipo === "audio", nivel = (u) => aud ? Math.min(2, ganhoEmItem(i, u)) : 1;
      for (let x = x0; x < x1; x += 2) { const u = (x + esq) / S.px - i.ini, v = o[Math.floor(((i.entrada || 0) + u * (i.velocidade || 1)) / m.dur * o.length)] || 0, a = Math.max(1, Math.min(1, v * nivel(u)) * (h - 10)); c.fillRect(x, y + h - 3 - a, 1.2, a); }
      if (aud) { c.save(); c.strokeStyle = "rgba(255,201,51,.95)"; c.lineWidth = 1.5; c.beginPath(); for (let x = x0; x <= x1; x += 2) { const u = (x + esq) / S.px - i.ini, yy = y + 4 + (1 - nivel(u) / 2) * (h - 8); x === x0 ? c.moveTo(x, yy) : c.lineTo(x, yy); } c.stroke(); c.restore(); } }
    y += h + 1; }
  moverAgulha(false);
  const n = S.sel.size, u = sel1(); $("#st-sel").textContent = n > 1 ? `${n} elementos selecionados` : u ? `${ROTULOS[u.tipo]}: ${tempoTxt(u.ini)} a ${tempoTxt(u.ini + u.dur)}` : "";
}
function ganhoEmItem(i, u) { const fi = +i.fade_in || 0, fo = +i.fade_out || 0; let g = (i.volume ?? 100) / 100; if (fi > 0 && u < fi) g *= Math.max(0, u / fi); if (fo > 0 && u > i.dur - fo) g *= Math.max(0, (i.dur - u) / fo); return g; }
function ondaDe(m) { const k = `${m.raiz}:${m.rel}`; if (!S.ondas.has(k)) { S.ondas.set(k, []); api("GET", `/api/estudio/onda?raiz=${encodeURIComponent(m.raiz)}&rel=${encodeURIComponent(m.rel)}`).then((o) => { S.ondas.set(k, o); desenharLinha(); }).catch(() => {}); } return S.ondas.get(k); }
const rotuloItem = (i) => i.tipo === "legenda" || i.tipo === "texto" ? i.texto : i.nome || ROTULOS[i.tipo];
function alvoTrMudou() { if (S.painel !== "transicoes" || !$("#st-tr-alvo")) return; const c = alvoTr(), k = c ? `c${c.t}` : "n"; if (k !== S.chaveTr) { S.chaveTr = k; if (!S.tocando) montarPainel(); } else if (!c) $("#st-tr-alvo strong").textContent = `Novo corte em ${tempoTxt(S.t)}`; }
function moverAgulha(seguir = true) { alvoTrMudou(); const x = S.t * S.px; $("#st-agulha").style.transform = `translateX(${x}px)`; $("#st-tempo").textContent = `${tempoTxt(S.t)} / ${tempoTxt(duracao())}`; if (seguir && S.tocando && (x > rolagem.scrollLeft + rolagem.clientWidth - 40 || x < rolagem.scrollLeft)) rolagem.scrollLeft = x - 60; }
function pontosIma(ignorar) { const p = [0, S.t]; for (const [, i] of itens()) if (!ignorar.has(i.id)) p.push(i.ini, i.ini + i.dur); return p; }
const imantar = (t, pts) => { if (!$("#st-ima").checked) return t; const m = 8 / S.px; let m0 = m, r = t; for (const p of pts) if (Math.abs(p - t) < m0) { m0 = Math.abs(p - t); r = p; } return r; };
const compativel = (fx, i) => ({ video: ["video", "imagem", "forma"], texto: ["texto"], legenda: ["legenda"], efeito: ["efeito"], audio: ["audio"] }[fx.tipo] || []).includes(i.tipo);
let arr = null;
faixasEl.addEventListener("dragstart", (ev) => ev.preventDefault()); faixasEl.addEventListener("selectstart", (ev) => ev.preventDefault());
const guiaT = el("i", { class: "st-guia-t", hidden: "" }), dicaArr = el("output", { class: "st-dica-arr", hidden: "" }); faixasEl.append(guiaT); document.body.append(dicaArr);
function mostrarGuia(t) { guiaT.hidden = t == null; if (t != null) guiaT.style.left = `${t * S.px}px`; }
function mostrarDica(ev, txt) { dicaArr.hidden = !txt; if (txt) { dicaArr.textContent = txt; dicaArr.style.left = `${Math.min(ev.clientX + 14, innerWidth - dicaArr.offsetWidth - 8)}px`; dicaArr.style.top = `${ev.clientY - 34}px`; } }
function rolarNaBorda(ev) { const v = rolagem.getBoundingClientRect(); if (ev.clientX > v.right - 48) rolagem.scrollLeft += 18; else if (ev.clientX < v.left + 36) rolagem.scrollLeft -= 18; if (ev.clientY > v.bottom - 28) rolagem.scrollTop += 10; else if (ev.clientY < v.top + 34) rolagem.scrollTop -= 10; }
trilhas.addEventListener("click", (ev) => { const m = ev.target.closest(".st-tr"); if (!m) return; pausar(); irPara(+m.dataset.t); abrirPainel("transicoes"); });
faixasEl.addEventListener("pointerdown", (ev) => {
  fecharPrevia(); if (ev.target.closest(".st-tr")) return;
  const alca = ev.target.closest(".st-vol, .st-fade");
  if (alca) { ev.preventDefault(); ev.stopPropagation(); const [, i] = achar(alca.closest(".st-bl").dataset.i); if (!i) return; arr = { modo: alca.dataset.vol ? "volume" : `fade_${alca.dataset.fade}`, i, x0: ev.clientX, y0: ev.clientY, v0: alca.dataset.vol ? i.volume ?? 100 : +i[`fade_${alca.dataset.fade}`] || 0, h: alca.closest(".st-trilha").offsetHeight - 8, feito: false }; faixasEl.setPointerCapture(ev.pointerId); return; }
  const marca = ev.target.closest(".st-pt");
  if (marca) { ev.preventDefault(); const [, i] = achar(marca.closest(".st-bl").dataset.i), c = pontosDe(i).find((x) => Math.abs(x.t - +marca.dataset.pt) < .02); if (!c) return; selecionarPonto(i, c.t); const l = pontosDe(i), n = l.findIndex((x) => x.t === c.t); arr = { modo: "ponto", i, chaves: c.ks.map(([, k]) => k), x0: ev.clientX, t0: c.t, min: n > 0 ? l[n - 1].t + .04 : 0, max: n < l.length - 1 ? l[n + 1].t - .04 : i.dur, feito: false }; faixasEl.setPointerCapture(ev.pointerId); return; }
  if (S.ponto) { S.ponto = null; montarInspetor(); desenharLinha(); }
  const bl = ev.target.closest(".st-bl"), r = faixasEl.getBoundingClientRect(), x = ev.clientX - r.left;
  document.activeElement?.blur?.();
  if (!bl) {
    const naRegua = ev.clientY - rolagem.getBoundingClientRect().top < 24;
    if (naRegua) { pausar(); arr = { modo: "agulha" }; faixasEl.setPointerCapture(ev.pointerId); irPara(x / S.px); }
    else if (ev.pointerType !== "touch") { pausar(); arr = { modo: "laco", x0: x, y0: ev.clientY - r.top - 24, base: new Set(ev.shiftKey || ev.ctrlKey || ev.metaKey ? S.sel : []), andou: false }; faixasEl.setPointerCapture(ev.pointerId); }
    return;
  }
  const id = bl.dataset.i, [f, i] = achar(id); pausar();
  if (S.ferr === "lamina") { const t = arred(imantar(x / S.px, pontosIma(new Set([id])))); if (!f.travada && t > i.ini + .03 && t < i.ini + i.dur - .03) { antes(); const [a, b] = partir(i, t); f.itens.splice(f.itens.indexOf(i), 1, a, b); S.sel = new Set([b.id]); irPara(t); mudou(true); } return; }
  if (ev.shiftKey || ev.ctrlKey || ev.metaKey) { S.sel.has(id) ? S.sel.delete(id) : S.sel.add(id); selecaoMudou(); return; }
  const ja = S.sel.has(id), soEste = ja && S.sel.size > 1 ? id : null; if (!ja) { S.sel.clear(); S.sel.add(id); selecaoMudou(); }
  if (f.travada || (ev.pointerType === "touch" && !ja)) return;
  const grupo = selecionados().map((o) => ({ o, ini: o.ini, dur: o.dur, ent: o.entrada ?? 0, kf: clonar(o.kf || {}), pal: clonar(o.palavras || []) }));
  arr = { modo: ev.target.dataset.b || "mover", i, f, x0: ev.clientX, y0: ev.clientY, s0: rolagem.scrollLeft, origens: new Set([f]), grupo, feito: false, pts: pontosIma(S.sel), soEste }; faixasEl.setPointerCapture(ev.pointerId);
});
faixasEl.addEventListener("pointermove", (ev) => {
  if (!arr) return; const r = faixasEl.getBoundingClientRect();
  if (arr.modo === "agulha") { irPara((ev.clientX - r.left) / S.px); return; }
  if (arr.modo === "volume" || arr.modo.startsWith("fade_")) {
    if (!arr.feito) { if (Math.hypot(ev.clientX - arr.x0, ev.clientY - arr.y0) < 2) return; antes(); arr.feito = true; } const i = arr.i;
    if (arr.modo === "volume") { i.volume = Math.round(lim(arr.v0 - (ev.clientY - arr.y0) * (ev.shiftKey ? .5 : 2), 0, 200)); dicaArr.textContent = `Volume ${i.volume}%`; }
    else { const k = arr.modo, outro = k === "fade_in" ? +i.fade_out || 0 : +i.fade_in || 0, d = (ev.clientX - arr.x0) / S.px * (k === "fade_in" ? 1 : -1); i[k] = arred(lim(arr.v0 + d, 0, Math.max(0, i.dur - outro))); dicaArr.textContent = `${k === "fade_in" ? "Entrada" : "Saída"} suave ${String(i[k]).replace(".", ",")} s`; }
    Object.assign(dicaArr.style, { left: `${ev.clientX + 14}px`, top: `${ev.clientY - 30}px` }); dicaArr.hidden = false; mudou(); atualizarGanhos(); atualizarCampos(); desenharLinha(); return; }
  if (arr.modo === "ponto") { if (!arr.feito) { if (Math.abs(ev.clientX - arr.x0) < 3) return; antes(); arr.feito = true; } moverPonto(arr.i, arr.chaves, lim(arred(arr.t0 + (ev.clientX - arr.x0) / S.px), arr.min, Math.max(arr.min, arr.max))); return; }
  if (arr.modo === "laco") { moverLaco(ev, r); return; }
  if (!arr.feito) { if (Math.hypot(ev.clientX - arr.x0, ev.clientY - arr.y0) < 4) return; antes(); arr.feito = true; }
  rolarNaBorda(ev);
  const dx = (ev.clientX + rolagem.scrollLeft - arr.x0 - arr.s0) / S.px, base = arr.grupo.find((g0) => g0.o === arr.i);
  if (arr.modo === "mover") {
    const cru = base.ini + dx, porIni = imantar(cru, arr.pts), porFim = imantar(cru + base.dur, arr.pts) - base.dur, usaFim = porIni === cru && porFim !== cru, novo = usaFim ? porFim : porIni;
    const d = novo - base.ini, min = Math.min(...arr.grupo.map((g0) => g0.ini)), dd = Math.max(-min, d);
    arr.grupo.forEach((g0) => { g0.o.ini = arred(g0.ini + dd); }); mostrarGuia(novo !== cru ? (usaFim ? novo + base.dur : novo) : null);
    let aviso = "";
    if (arr.grupo.length === 1) { const alvo = document.elementsFromPoint(ev.clientX, ev.clientY).find((n) => n.classList?.contains("st-trilha")); const fx = alvo && S.p.faixas.find((x) => x.id === alvo.dataset.f);
      if (fx && fx !== arr.f && compativel(fx, arr.i) && !fx.travada) { arr.f.itens.splice(arr.f.itens.indexOf(arr.i), 1); fx.itens.push(arr.i); arr.f = fx; arr.origens.add(fx); } else if (fx && fx !== arr.f) aviso = `${ROTULOS[arr.i.tipo]} não entra na faixa ${fx.nome}`; S.alvoF = arr.f.id; }
    mostrarDica(ev, aviso || `${tempoTxt(arr.i.ini)} em ${arr.f.nome}`);
  } else for (const g0 of arr.grupo) { const o = g0.o, m = o.midia && S.p.midias[o.midia], vel = o.velocidade || 1;
    if (arr.modo === "a") { let ini = imantar(g0.ini + dx, arr.pts); ini = lim(ini, Math.max(0, m?.dur ? g0.ini - g0.ent / vel : 0), g0.ini + g0.dur - .1); const d = ini - g0.ini; o.ini = arred(ini); o.dur = arred(g0.dur - d); if (o.entrada !== undefined) o.entrada = arred(g0.ent + d * vel);
      if (Object.keys(g0.kf).length) o.kf = Object.fromEntries(Object.entries(g0.kf).map(([p, c]) => [p, c.map((k) => ({ ...k, t: arred(k.t - d) }))])); if (g0.pal.length) o.palavras = g0.pal.map((w) => ({ ...w, ini: Math.max(0, arred(w.ini - d)), fim: arred(w.fim - d) })); }
    else { let fim = imantar(g0.ini + g0.dur + dx, arr.pts); const max = ["video", "audio"].includes(o.tipo) && m?.dur ? g0.ini + (m.dur - g0.ent) / vel : Infinity; o.dur = arred(lim(fim, g0.ini + .1, max) - g0.ini); } }
  pedirPintura(); desenharLinha(); atualizarCampos();
});
function moverLaco(ev, r) {
  const x = ev.clientX - r.left, y = ev.clientY - r.top - 24;
  if (!arr.andou && Math.hypot(x - arr.x0, y - arr.y0) < 4) return; arr.andou = true;
  const v = rolagem.getBoundingClientRect(); if (ev.clientX > v.right - 40) rolagem.scrollLeft += 24; else if (ev.clientX < v.left + 30) rolagem.scrollLeft -= 24; if (ev.clientY > v.bottom - 30) rolagem.scrollTop += 14; else if (ev.clientY < v.top + 34) rolagem.scrollTop -= 14;
  const x0 = Math.min(x, arr.x0), x1 = Math.max(x, arr.x0), y0 = Math.min(y, arr.y0), y1 = Math.max(y, arr.y0);
  let n = $("#st-laco"); if (!n) { n = el("div", { id: "st-laco", class: "st-laco" }); faixasEl.append(n); }
  Object.assign(n.style, { left: `${x0}px`, top: `${y0 + 24}px`, width: `${x1 - x0}px`, height: `${y1 - y0}px` });
  const novos = new Set(arr.base); let topo = 0;
  for (const f of [...S.p.faixas].reverse()) { const h = altF(f) + 1; if (!f.travada && topo < y1 && topo + h > y0) for (const i of f.itens) if (i.ini * S.px < x1 && (i.ini + i.dur) * S.px > x0) novos.add(i.id); topo += h; }
  S.sel = novos; desenharLinha();
}
const soltar = (ev) => {
  if (arr && (arr.modo === "volume" || arr.modo.startsWith?.("fade_"))) { dicaArr.hidden = true; const feito = arr.feito; arr = null; if (feito) { mudou(true); selecaoMudou(); } return; }
  if (arr?.modo === "laco") { $("#st-laco")?.remove(); if (!arr.andou) { irPara(arr.x0 / S.px); S.sel = arr.base; } selecaoMudou(); }
  else if (arr?.feito) { if (arr.modo === "mover") assentar(); mudou(true); montarCabecas(); }
  else if (arr?.soEste) { S.sel = new Set([arr.soEste]); selecaoMudou(); }
  arr = null; S.alvoF = null; mostrarGuia(null); mostrarDica(null, ""); desenharLinha();
};
/* Ao soltar sobre outro elemento, o bloco desce para uma faixa livre, como no CapCut. */
function assentar() {
  const movidos = new Set(arr.grupo.map((g0) => g0.o));
  const bate = (f, o) => f.itens.some((x) => x !== o && !movidos.has(x) && x.ini < o.ini + o.dur - .02 && x.ini + x.dur > o.ini + .02);
  for (const o of movidos) { const f = achar(o.id)[0]; if (!bate(f, o)) continue;
    const livre = S.p.faixas.find((x) => x !== f && x.tipo === f.tipo && !x.travada && compativel(x, o) && !bate(x, o)) || novaFaixa(f.tipo);
    f.itens.splice(f.itens.indexOf(o), 1); livre.itens.push(o); arr.origens.add(f); }
  for (const f of arr.origens) if (!f.itens.length && S.p.faixas.filter((x) => x.tipo === f.tipo).length > 1) S.p.faixas.splice(S.p.faixas.indexOf(f), 1);
}
faixasEl.addEventListener("pointerup", soltar); faixasEl.addEventListener("pointercancel", soltar);
sobre.addEventListener("pointerdown", () => document.activeElement?.blur?.(), true);
function partir(i, t) {
  const u = t - i.ini, a = clonar(i), b = clonar(i); b.id = nid(); a.dur = arred(u); b.ini = arred(t); b.dur = arred(i.dur - u); if (b.entrada !== undefined) b.entrada = arred(b.entrada + u * (b.velocidade || 1)); delete b.transicao;
  for (const [p, c] of Object.entries(i.kf || {})) { const v = arred(val(i, p, u), 4); a.kf[p] = [...c.filter((k) => k.t < u), { t: arred(u), v, e: "linear" }]; b.kf[p] = [{ t: 0, v, e: "linear" }, ...c.filter((k) => k.t > u).map((k) => ({ ...k, t: arred(k.t - u) }))]; }
  if (i.palavras) { a.palavras = i.palavras.filter((w) => w.ini < u); b.palavras = i.palavras.filter((w) => w.ini >= u).map((w) => ({ ...w, ini: arred(w.ini - u), fim: arred(w.fim - u) })); a.texto = a.palavras.map((w) => w.p).join(" "); b.texto = b.palavras.map((w) => w.p).join(" "); }
  return [a, b];
}
function dividir() {
  const lista = (S.sel.size ? selecionados() : itens().filter(([f, i]) => !f.travada && f.tipo !== "efeito").map(([, i]) => i)).filter((i) => S.t > i.ini + .03 && S.t < i.ini + i.dur - .03);
  if (!lista.length) { avisar("Coloque a agulha sobre o elemento que quer dividir"); return; } antes(); S.sel.clear();
  for (const i of lista) { const [f] = achar(i.id), [a, b] = partir(i, S.t); f.itens.splice(f.itens.indexOf(i), 1, a, b); S.sel.add(b.id); } mudou(true);
}
function duplicar() { const l = selecionados(); if (!l.length) return; antes(); S.sel.clear(); const fim = Math.max(...l.map((i) => i.ini + i.dur)), ini = Math.min(...l.map((i) => i.ini)); for (const i of l) { const [f] = achar(i.id), n = clonar(i); n.id = nid(); n.ini = arred(i.ini + fim - ini); f.itens.push(n); S.sel.add(n.id); } mudou(true); }
function apagar() { const l = selecionados(); if (!l.length) return; antes(); for (const i of l) { const [f] = achar(i.id); f.itens.splice(f.itens.indexOf(i), 1); } S.sel.clear(); mudou(true); }
async function cortarTempo(lista) { await salvar(); antes(); const r = await api("POST", `/api/estudio/${S.tipo}/${S.id}/aplicar`, { projeto: S.p, sugestoes: [{ acao: { tipo: "cortar_varios", intervalos: lista } }] }); S.p = r.projeto; S.sel.clear(); S.t = Math.min(S.t, duracao()); mudou(true); montarCabecas(); }
function apagarJuntando() { const l = selecionados(); if (!l.length) return; cortarTempo(l.map((i) => [i.ini, i.ini + i.dur])).catch((e) => avisar(e.message)); }
$("#st-abrir-tr").addEventListener("click", () => abrirPainel("transicoes")); $("#st-dividir").addEventListener("click", dividir); $("#st-duplicar").addEventListener("click", duplicar); $("#st-apagar").addEventListener("click", () => (cap() ? apagarCamada() : apagar())); $("#st-fechar-vao").addEventListener("click", apagarJuntando);
$("#st-desfazer").addEventListener("click", desfazer); $("#st-refazer").addEventListener("click", refazer); $("#st-salvar").addEventListener("click", () => { S.sujo = true; salvar(); });
$("#st-nova-faixa").addEventListener("change", (ev) => { const t = ev.target.value; ev.target.value = ""; if (!t) return; antes(); novaFaixa(t); mudou(); montarCabecas(); });
function novaFaixa(tipo) { const f = { id: nid("f"), tipo, nome: { video: "Vídeo", texto: "Textos", legenda: "Legendas", efeito: "Efeitos", audio: "Áudio" }[tipo] + " " + (S.p.faixas.filter((x) => x.tipo === tipo).length + 1), oculta: false, muda: false, travada: false, itens: [] };
  const n = S.p.faixas.map((x) => x.tipo).lastIndexOf(tipo); S.p.faixas.splice(n < 0 ? S.p.faixas.length : n + 1, 0, f); return f; }
function ferramenta(f) { S.ferr = f; faixasEl.dataset.ferr = f; $("#st-f-sel").setAttribute("aria-pressed", String(f === "sel")); $("#st-f-lamina").setAttribute("aria-pressed", String(f === "lamina")); }
$("#st-f-sel").addEventListener("click", () => ferramenta("sel")); $("#st-f-lamina").addEventListener("click", () => ferramenta("lamina"));
function dividirTudo() { const l = itens().filter(([f, i]) => !f.travada && S.t > i.ini + .03 && S.t < i.ini + i.dur - .03); if (!l.length) return; antes(); for (const [f, i] of l) { const [a, b] = partir(i, S.t); f.itens.splice(f.itens.indexOf(i), 1, a, b); } mudou(true); }
function alvoAgulha() { return sel1() || itens().filter(([f, i]) => f.tipo === "video" && !f.travada && i.tipo !== "forma" && S.t > i.ini && S.t < i.ini + i.dur).map(([, i]) => i).pop(); }
function aparoLocal(i, lado) { const [f] = achar(i.id), [a, b] = partir(i, S.t), fica = lado === "esq" ? b : a; antes(); f.itens.splice(f.itens.indexOf(i), 1, fica); S.sel = new Set([fica.id]); mudou(true); }
function aparar(lado, juntar = true) {
  const i = alvoAgulha(); if (!i || S.t <= i.ini + .03 || S.t >= i.ini + i.dur - .03) { avisar("Coloque a agulha sobre o trecho que quer aparar"); return; }
  if (!juntar || !["video", "imagem"].includes(i.tipo)) { aparoLocal(i, lado); return; }
  const a = i.ini, b = i.ini + i.dur, t = S.t; cortarTempo([lado === "esq" ? [a, t] : [t, b]]).then(() => irPara(lado === "esq" ? a : t)).catch((e) => avisar(e.message));
}
function pontoCorte(sentido) { const p = [...new Set(itens().filter(([f]) => f.tipo === "video").flatMap(([, i]) => [i.ini, i.ini + i.dur]).map((v) => arred(v)))].sort((a, b) => a - b), n = sentido > 0 ? p.find((v) => v > S.t + .01) : p.reverse().find((v) => v < S.t - .01); if (n !== undefined) { irPara(n); const x = n * S.px; if (x < rolagem.scrollLeft || x > rolagem.scrollLeft + rolagem.clientWidth - 30) rolagem.scrollLeft = x - 80; } }
function marcador() { antes(); const l = S.p.marcadores ||= [], n = l.findIndex((m) => Math.abs(m - S.t) < .05); if (n >= 0) l.splice(n, 1); else l.push(arred(S.t)); mudou(); }
const abrirAtalhos = () => $("#st-dlg-atalhos").showModal();
$("#st-atalhos").addEventListener("click", abrirAtalhos); $$("#st-dlg-atalhos [data-fechar], #st-dlg-exportar [data-fechar]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
const digitando = (n) => n.closest?.('textarea, select, input:not([type=range]):not([type=checkbox]):not([type=radio]):not([type=color])');
document.addEventListener("pointerup", (ev) => { const n = document.activeElement; if (n?.closest?.("#st-mesa") && n.matches("button, input[type=range], input[type=checkbox], #st-divisor")) n.blur(); });
addEventListener("keydown", (ev) => {
  if (!S.aberto || $("#aba-editor").hidden || document.querySelector("dialog[open]")) return;
  if (ev.key === " " && ev.target.matches?.("input[type=number]")) ev.target.blur();
  else if (digitando(ev.target)) return;
  if (ev.key === " " && ev.repeat) { ev.preventDefault(); return; }
  if (ev.target.matches?.("input[type=range]") && ev.key.startsWith("Arrow")) return;
  const k = ev.key.toLowerCase(), c = ev.ctrlKey || ev.metaKey, sh = ev.shiftKey, faz = (fn) => { ev.preventDefault(); fn(); };
  if (c && k === "z") return faz(sh ? refazer : desfazer); if (c && k === "y") return faz(refazer); if (c && k === "s") return faz(() => { S.sujo = true; salvar(); }); if (c && k === "e") return faz(() => $("#st-exportar").click());
  if (k === "?" || (c && k === "/")) return faz(abrirAtalhos);
  if (cap()) { if (k === "delete" || k === "backspace") faz(apagarCamada); return; }
  if (c && k === "b") return faz(sh ? dividirTudo : dividir); if (c && k === "d") return faz(duplicar); if (c && k === "a") return faz(() => { S.sel = new Set(itens().map(([, i]) => i.id)); selecaoMudou(); });
  if (c && k === "c") return faz(() => { S.clipe = clonar(selecionados()); if (S.clipe.length) avisar("Copiado"); }); if (c && k === "x") return faz(() => { S.clipe = clonar(selecionados()); apagar(); });
  if (c && k === "v") return faz(() => { if (!S.clipe.length) return; antes(); const ini = Math.min(...S.clipe.map((i) => i.ini)); S.sel.clear(); for (const i of S.clipe) { const n = clonar(i); n.id = nid(); n.ini = arred(S.t + i.ini - ini); (S.p.faixas.find((f) => compativel(f, n)) || novaFaixa(n.tipo === "audio" ? "audio" : "video")).itens.push(n); S.sel.add(n.id); } mudou(true); });
  if (c && (k === "=" || k === "+")) return faz(() => zoomT(1.4)); if (c && k === "-") return faz(() => zoomT(1 / 1.4)); if (c) return;
  if (k === " ") return faz(() => (S.tocando ? pausar() : tocar())); if (k === "j") return faz(() => vaivem(-1)); if (k === "l") return faz(() => vaivem(1)); if (k === "k") return faz(pausar);
  if (sh && k === "z") return faz(ajustarZoom); if (k === "q") return faz(() => aparar("esq")); if (k === "w") return faz(() => aparar("dir")); if (k === "[") return faz(() => aparar("esq", false)); if (k === "]") return faz(() => aparar("dir", false));
  if (k === "a") return faz(() => ferramenta("sel")); if (k === "b") return faz(() => ferramenta("lamina")); if (k === "s") return faz(dividir); if (k === "n") return faz(() => { $("#st-ima").checked = !$("#st-ima").checked; avisar($("#st-ima").checked ? "Ímã ligado" : "Ímã desligado"); }); if (k === "m") return faz(marcador);
  if ((k === "delete" || k === "backspace") && pontoAtual()) return faz(apagarPonto);
  if (k === "escape" && S.ponto) return faz(() => { S.ponto = null; montarInspetor(); desenharLinha(); });
  if (k === "delete" || k === "backspace") return faz(sh ? apagarJuntando : apagar); if (k === "escape") return faz(() => { ferramenta("sel"); S.sel.clear(); selecaoMudou(); });
  if (k === "arrowleft") return faz(() => { pausar(); irPara(S.t - (sh ? 1 : 1 / 30)); }); if (k === "arrowright") return faz(() => { pausar(); irPara(S.t + (sh ? 1 : 1 / 30)); }); if (k === "arrowup") return faz(() => { pausar(); pontoCorte(-1); }); if (k === "arrowdown") return faz(() => { pausar(); pontoCorte(1); });
  if (k === "home") return faz(() => { irPara(0); rolagem.scrollLeft = 0; }); if (k === "end") return faz(() => irPara(duracao()));
});
function selecaoMudou() { montarInspetor(); desenharLinha(); pedirPintura(); if (cap() || S.painel === "efeitos") montarPainel(); }
/* ---------- Componentes do inspetor ---------- */
let vivos = [];
function atualizarCampos() { vivos.forEach((f) => f()); }
const sec = (titulo, ...f) => el("section", { class: "st-sec" }, titulo ? el("h3", {}, titulo) : null, ...f);
const btn = (txt, fn, cls = "botao") => el("button", { class: cls, type: "button", onclick: fn }, txt);
function botaoKf(i, p) {
  const b = el("button", { class: "st-kf", type: "button", title: "Keyframe neste instante", "aria-label": `Keyframe de ${p}` });
  const ver = () => { const c = i.kf?.[p] || [], u = local(i), aqui = c.some((k) => Math.abs(k.t - u) < .02); b.textContent = aqui ? "◆" : "◇"; c.length ? b.dataset.tem = "1" : delete b.dataset.tem; aqui ? b.dataset.aqui = "1" : delete b.dataset.aqui; };
  b.addEventListener("click", () => { antes(); i.kf ||= {}; const u = arred(local(i)), v = arred(val(i, p, u), 4), c = i.kf[p] ||= [], n = c.findIndex((k) => Math.abs(k.t - u) < .02); if (n >= 0) c.splice(n, 1); else { c.push({ t: u, v, e: "suave" }); c.sort((a, d) => a.t - d.t); } if (!c.length) { delete i.kf[p]; (i.t ||= {})[p] = v; } mudou(); ver(); desenharLinha(); });
  vivos.push(ver); ver(); return b;
}
function campo(rot, { get, set, min = 0, max = 100, step = 1, kf }) {
  const r = el("input", { type: "range", min, max, step, "aria-label": rot }), n = el("input", { type: "number", step, "aria-label": rot }); let m = false;
  const ver = () => { const v = get(); if (document.activeElement !== n) n.value = arred(v, 3); r.value = v; };
  const pos = (v) => { if (Number.isNaN(+v)) return; if (!m) { antes(); m = true; } set(+v); mudou(); ver(); };
  r.addEventListener("input", () => pos(r.value)); n.addEventListener("input", () => pos(n.value)); for (const x of [r, n]) x.addEventListener("change", () => (m = false));
  vivos.push(ver); ver(); return el("label", { class: `st-campo${kf ? "" : " sem-kf"}` }, el("span", {}, rot), r, n, kf ? botaoKf(...kf) : null);
}
const campoT = (i, p, rot, o) => campo(rot, { ...o, get: () => val(i, p, local(i)), set: (v) => porProp(i, p, v), kf: [i, p] });
function linha(rot, ctrl) { return el("label", { class: "st-campo largo" }, el("span", {}, rot), ctrl); }
function escolha(rot, ops, v, fn) { const s = el("select", { "aria-label": rot }, ...ops.map(([a, b]) => el("option", { value: a }, b))); s.value = v ?? ops[0][0]; s.addEventListener("change", () => { antes(); fn(s.value); mudou(); }); return linha(rot, s); }
function corCampo(rot, v, fn) { const c = el("input", { type: "color", value: String(v || "#ffffff").slice(0, 7) }); let m = false; c.addEventListener("input", () => { if (!m) { antes(); m = true; } fn(c.value.toUpperCase()); mudou(); }); c.addEventListener("change", () => (m = false)); return linha(rot, c); }
function marca(rot, v, fn) { const c = el("input", { type: "checkbox" }); c.checked = !!v; c.addEventListener("change", () => { antes(); fn(c.checked); mudou(); }); return el("label", { class: "marcar" }, c, el("span", {}, rot)); }
const opFontes = () => S.fontes.map((f) => [f.id, f.nome]);
function controlesEstilo(est, por) {
  const n = (k, rot, min, max, step = 1) => campo(rot, { get: () => est()[k], set: (v) => por(k, v), min, max, step });
  const envioFonte = el("input", { type: "file", accept: ".ttf,.otf", hidden: "" });
  envioFonte.addEventListener("change", async () => { const a = envioFonte.files[0]; if (!a) return; const r = await fetch(`/api/estudio/fontes?nome=${encodeURIComponent(a.name)}`, { method: "POST", body: a }); const d = await r.json(); if (r.ok) { S.fontes = d; montarInspetor(); avisar("Fonte adicionada"); } else avisar(d.erro); });
  return [sec("Fonte", escolha("Fonte", opFontes(), est().fonte, (v) => por("fonte", v)), btn("Enviar fonte", () => envioFonte.click()), envioFonte, n("tamanho", "Tamanho", 10, 300), corCampo("Cor", est().cor, (v) => por("cor", v)), n("opacidade", "Opacidade", 0, 100), marca("Letras maiúsculas", est().maiusculas, (v) => por("maiusculas", v))),
    sec("Layout", escolha("Alinhar", [["centro", "Centro"], ["esquerda", "Esquerda"], ["direita", "Direita"]], est().alinhamento, (v) => por("alinhamento", v)), n("espacamento", "Espaço letras", -5, 40), n("entrelinha", "Entrelinhas", 70, 220), n("largura", "Largura", 100, 3000, 10)),
    sec("Contorno e sombra", n("contorno", "Contorno", 0, 40), corCampo("Cor", est().contorno_cor, (v) => por("contorno_cor", v)), marca("Sombra", est().sombra, (v) => por("sombra", v)), corCampo("Cor", est().sombra_cor, (v) => por("sombra_cor", v)), n("sombra_x", "Sombra X", -40, 40), n("sombra_y", "Sombra Y", -40, 40), n("sombra_blur", "Suavidade", 0, 40), n("sombra_opac", "Força", 0, 100)),
    sec("Fundo e borda", marca("Caixa de fundo", est().fundo, (v) => por("fundo", v)), corCampo("Cor", est().fundo_cor, (v) => por("fundo_cor", v)), n("fundo_opac", "Opacidade", 0, 100), n("fundo_raio", "Arredondar", 0, 80), n("fundo_pad", "Margem", 0, 80), n("borda", "Borda", 0, 20), corCampo("Cor borda", est().borda_cor, (v) => por("borda_cor", v))),
    sec("Destaque de palavras", escolha("Destacar", [["nenhum", "Nada"], ["palavra", "Palavra falada"], ["importantes", "Palavras importantes"], ["ambos", "Falada e importantes"]], est().destaque, (v) => por("destaque", v)), corCampo("Cor", est().cor_destaque, (v) => por("cor_destaque", v)), marca("Caixa na palavra falada", est().destaque_caixa, (v) => por("destaque_caixa", v)), marca("Uma palavra por vez", est().palavra_a_palavra, (v) => por("palavra_a_palavra", v))),
    sec("Animação", escolha("Entrada", ANIM, est().entrada, (v) => por("entrada", v)), escolha("Saída", ANIM, est().saida, (v) => por("saida", v)), n("tempo_anim", "Tempo (s)", .03, 1.5, .01))];
}
function alinhar(i, modo) { antes(); const b = S.caixas.get(i.id), W = S.p.largura, H = S.p.altura, w = b?.w ?? 0, h = b?.h ?? 0, m = { e: ["x", w / 2], c: ["x", W / 2], d: ["x", W - w / 2], t: ["y", h / 2], m: ["y", H / 2], b: ["y", H - h / 2] }[modo]; porP(i, m[0], arred(m[1], 1)); mudou(); atualizarCampos(); }
function secTempo(i) { return sec("Tempo", campo("Início", { get: () => i.ini, set: (v) => { i.ini = Math.max(0, arred(v)); }, min: 0, max: Math.ceil(duracao()), step: .01 }), campo("Duração", { get: () => i.dur, set: (v) => { const f = Math.max(.1, v) / i.dur; i.dur = arred(Math.max(.1, v)); if (i.palavras) i.palavras = i.palavras.map((w) => ({ ...w, ini: arred(w.ini * f), fim: arred(w.fim * f) })); }, min: .1, max: Math.max(30, Math.ceil(i.dur * 2)), step: .01 })); }
/* ---------- Reenquadrar: escolhe a parte do vídeo original que aparece ---------- */
const RQ = { item: null, faixa: null, v: null, r: null, ini: null, fmt: "atual", vw: 16, vh: 9 }, rqDlg = $("#st-rq"), rqOrig = $("#rq-original"), rqFim = $("#rq-resultado"), rqJanela = $("#rq-janela");
const RQ_FORMATOS = [["atual", "Atual"], ["9:16", "9:16"], ["4:5", "4:5"], ["1:1", "1:1"], ["orig", "Original"], ["livre", "Livre"]];
const rqAspecto = () => { const { fmt, vw, vh, r, item } = RQ; return fmt === "atual" ? val(item, "w", 0) / val(item, "h", 0) : fmt === "orig" ? vw / vh : fmt === "livre" ? (r.w * vw) / (r.h * vh) : { "9:16": 9 / 16, "4:5": .8, "1:1": 1 }[fmt]; };
const rqRazao = () => rqAspecto() * RQ.vh / RQ.vw;
function rqEncaixar(cx, cy, w) { const n = rqRazao(); let h = w / n; if (h > 1) { h = 1; w = n; } if (w > 1) { w = 1; h = 1 / n; } RQ.r = { x: lim(cx - w / 2, 0, 1 - w), y: lim(cy - h / 2, 0, 1 - h), w, h }; }
function rqCaixa() { const W = S.p.largura, H = S.p.altura, i = RQ.item; if (RQ.fmt === "atual") { const e = val(i, "escala", 0); return { x: val(i, "x", 0), y: val(i, "y", 0), w: val(i, "w", 0) * e, h: val(i, "h", 0) * e }; } const a = rqAspecto(), w = Math.min(W, H * a); return { x: W / 2, y: H / 2, w, h: w / a }; }
const rqOutro = () => { const { item, faixa } = RQ, n = S.p.faixas.indexOf(faixa); return S.p.faixas.slice(0, n).some((f) => f.tipo === "video" && !f.oculta && f.itens.some((j) => !j.ajustes?.desfoque && j.ini < item.ini + item.dur && item.ini < j.ini + j.dur)); };
const rqCobre = (c) => c.x - c.w / 2 <= 1 && c.y - c.h / 2 <= 1 && c.x + c.w / 2 >= S.p.largura - 1 && c.y + c.h / 2 >= S.p.altura - 1;
function rqCheio() { const n = (S.p.largura / S.p.altura) * RQ.vh / RQ.vw, w = n <= 1 ? n : 1, h = n <= 1 ? 1 : 1 / n; return { x: (1 - w) / 2, y: (1 - h) / 2, w, h }; }
function rqDesenhar() {
  const { v, r, vw, vh } = RQ; if (!r) return;
  Object.assign(rqJanela.style, { left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` });
  const c = rqCaixa(), cobre = rqCobre(c), o = rqOrig.getContext("2d"), f = rqFim.getContext("2d"), W = rqFim.width, k = W / S.p.largura; $("#rq-rotulo-fundo").hidden = cobre || rqOutro();
  f.fillStyle = "#000"; f.fillRect(0, 0, W, rqFim.height); if (!v?.videoWidth) return;
  o.drawImage(v, 0, 0, rqOrig.width, rqOrig.height);
  if (!cobre && !rqOutro() && $("#rq-fundo").checked) { const b = rqCheio(); f.filter = "blur(8px) brightness(.8)"; f.drawImage(v, b.x * vw, b.y * vh, b.w * vw, b.h * vh, 0, 0, W, rqFim.height); f.filter = "none"; }
  f.drawImage(v, r.x * vw, r.y * vh, r.w * vw, r.h * vh, (c.x - c.w / 2) * k, (c.y - c.h / 2) * k, c.w * k, c.h * k);
}
function rqFormato(fmt) { RQ.fmt = fmt; rqJanela.dataset.livre = String(fmt === "livre"); if (fmt === "atual") RQ.r = { ...RQ.ini }; else if (fmt !== "livre") rqEncaixar(RQ.r.x + RQ.r.w / 2, RQ.r.y + RQ.r.h / 2, 1); $$("#rq-formatos button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.f === fmt))); rqDesenhar(); }
function rqVer() { const { v, item } = RQ; if (v?.readyState) v.currentTime = lim((item.entrada || 0) + +$("#rq-momento").value * (item.velocidade || 1), 0, Math.max(0, (v.duration || 1) - .05)); }
function abrirReenquadrar(item) {
  const [faixa] = achar(item.id), mid = S.p.midias[item.midia]; if (!mid) return; pausar();
  const v = document.createElement("video"); RQ.v?.removeAttribute("src"); Object.assign(RQ, { item, faixa, v, fmt: "atual", r: null }); v.muted = true; v.preload = "auto"; v.playsInline = true; v.src = urlMidia(mid);
  const m = $("#rq-momento"); m.max = String(item.dur); m.value = String(lim(S.t - item.ini, 0, item.dur));
  $("#rq-formatos").replaceChildren(...RQ_FORMATOS.map(([f, t]) => el("button", { class: "botao", type: "button", dados: { f }, onclick: () => rqFormato(f) }, t)));
  $("#rq-rotulo-todas").hidden = faixa.itens.filter((i) => i.midia === item.midia).length < 2;
  v.addEventListener("loadedmetadata", () => {
    RQ.vw = v.videoWidth; RQ.vh = v.videoHeight; const e = 760 / Math.max(RQ.vw, RQ.vh); rqOrig.width = Math.round(RQ.vw * e); rqOrig.height = Math.round(RQ.vh * e); rqFim.width = 216; rqFim.height = Math.round(216 * S.p.altura / S.p.largura);
    const [cl, ct, cr, cb] = ["cl", "ct", "cr", "cb"].map((p) => val(item, p, 0)), w = Math.max(.02, 1 - cl - cr), h = Math.max(.02, 1 - ct - cb); RQ.r = { x: cl, y: ct, w, h }; rqEncaixar(cl + w / 2, ct + h / 2, Math.min(w, h * rqRazao())); RQ.ini = { ...RQ.r }; rqFormato("atual"); rqVer();
  }, { once: true });
  v.addEventListener("seeked", rqDesenhar); rqDlg.showModal();
}
function rqFundo(faixa, alvo) {
  const W = S.p.largura, H = S.p.altura, b = rqCheio(), borrado = (i, j) => j.ajustes?.desfoque && j.ini < i.ini + i.dur && i.ini < j.ini + j.dur; let base = null;
  for (const i of alvo) {
    if (S.p.faixas.some((f) => f.tipo === "video" && f.itens.some((j) => j !== i && borrado(i, j)))) continue;
    if (!base) { base = { id: nid("f"), tipo: "video", nome: "Fundo", oculta: false, muda: false, travada: false, itens: [] }; S.p.faixas.splice(S.p.faixas.indexOf(faixa), 0, base); }
    base.itens.push({ ...clonar(i), id: nid(), nome: "Fundo desfocado", mudo: true, transicao: undefined, kf: {}, ajustes: { desfoque: 40, brilho: -20, saturacao: 15 }, t: { ...clonar(i.t), x: W / 2, y: H / 2, w: W, h: H, escala: 1, rot: 0, opac: 100, zoom: 1, zx: .5, zy: .5, cl: b.x, ct: b.y, cr: 1 - b.x - b.w, cb: 1 - b.y - b.h } });
  }
}
function rqAplicar() {
  const { item, faixa, r, fmt } = RQ; if (!r) return; const c = rqCaixa(), alvo = $("#rq-todas").checked ? faixa.itens.filter((i) => i.midia === item.midia) : [item];
  antes();
  for (const i of alvo) {
    Object.assign(i.t, { cl: arred(r.x, 4), ct: arred(r.y, 4), cr: arred(1 - r.x - r.w, 4), cb: arred(1 - r.y - r.h, 4) });
    const fora = ["cl", "ct", "cr", "cb", ...(fmt === "atual" ? [] : ["x", "y", "w", "h", "escala"])]; fora.forEach((p) => { if (i.kf) delete i.kf[p]; });
    if (fmt !== "atual") Object.assign(i.t, { x: arred(c.x, 1), y: arred(c.y, 1), w: arred(c.w, 1), h: arred(c.h, 1), escala: 1 });
  }
  if (!rqCobre(c) && !rqOutro() && $("#rq-fundo").checked) rqFundo(faixa, alvo);
  rqDlg.close(); mudou(true); selecaoMudou();
}
{
  let ges = null; const ponto = (ev) => { const b = $("#rq-palco").getBoundingClientRect(); return [lim((ev.clientX - b.left) / b.width, 0, 1), lim((ev.clientY - b.top) / b.height, 0, 1)]; };
  rqJanela.addEventListener("pointerdown", (ev) => { if (!RQ.r) return; ev.preventDefault(); rqJanela.focus(); const [x, y] = ponto(ev), c = ev.target.dataset?.c, r = RQ.r; ges = { x, y, c, r: { ...r }, ax: c?.includes("w") ? r.x + r.w : r.x, ay: c?.includes("n") ? r.y + r.h : r.y }; rqJanela.setPointerCapture(ev.pointerId); });
  rqJanela.addEventListener("pointermove", (ev) => {
    if (!ges) return; const [x, y] = ponto(ev), { c, r, ax, ay } = ges;
    if (!c) { RQ.r = { ...r, x: lim(r.x + x - ges.x, 0, 1 - r.w), y: lim(r.y + y - ges.y, 0, 1 - r.h) }; rqDesenhar(); return; }
    if (c.length === 1) { // bolinhas do meio: mexem só um lado
      const n = { ...r }, d = r.x + r.w, b = r.y + r.h;
      if (c === "e") n.w = lim(x - r.x, .06, 1 - r.x); if (c === "w") { n.x = lim(x, 0, d - .06); n.w = d - n.x; }
      if (c === "s") n.h = lim(y - r.y, .06, 1 - r.y); if (c === "n") { n.y = lim(y, 0, b - .06); n.h = b - n.y; }
      RQ.r = n; rqDesenhar(); return;
    }
    const esq = c.includes("w"), cima = c.includes("n"), maxW = esq ? ax : 1 - ax, maxH = cima ? ay : 1 - ay; let w = esq ? ax - x : x - ax, h = cima ? ay - y : y - ay;
    if (RQ.fmt === "livre") { w = lim(w, .06, maxW); h = lim(h, .06, maxH); } else { const n = rqRazao(); w = lim(Math.max(w, h * n), .06, Math.min(maxW, maxH * n)); h = w / n; }
    RQ.r = { x: esq ? ax - w : ax, y: cima ? ay - h : ay, w, h }; rqDesenhar();
  });
  const soltar = () => { ges = null; }; rqJanela.addEventListener("pointerup", soltar); rqJanela.addEventListener("pointercancel", soltar);
  rqDlg.addEventListener("keydown", (ev) => { ev.stopPropagation(); const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[ev.key]; if (!d || ev.target !== rqJanela || !RQ.r) return; ev.preventDefault(); const r = RQ.r, p = ev.shiftKey ? .05 : .01; RQ.r = { ...r, x: lim(r.x + d[0] * p, 0, 1 - r.w), y: lim(r.y + d[1] * p, 0, 1 - r.h) }; rqDesenhar(); });
  $("#rq-fechar").addEventListener("click", () => rqDlg.close()); $("#rq-aplicar").addEventListener("click", rqAplicar); $("#rq-momento").addEventListener("input", rqVer); $("#rq-fundo").addEventListener("change", rqDesenhar);
  $("#rq-tudo").addEventListener("click", () => { RQ.r = { x: 0, y: 0, w: 1, h: 1 }; rqFormato("orig"); });
  $("#rq-centro").addEventListener("click", () => { const r = RQ.r; RQ.r = { ...r, x: (1 - r.w) / 2, y: (1 - r.h) / 2 }; rqDesenhar(); });
  sobre.addEventListener("dblclick", () => { const o = !cap() && sel1(); if (o?.tipo === "video") abrirReenquadrar(o); });
}
function montarInspetor() {
  vivos = []; const c = $("#st-insp"); if (cap()) { inspetorCapa(c); return; } if (S.ponto && (!S.sel.has(S.ponto.id) || !pontoAtual())) S.ponto = null;
  const l = selecionados(), i = l.length === 1 ? l[0] : null;
  if (!l.length) { c.replaceChildren(el("h2", {}, "Ajustes"), el("p", { class: "dica" }, "Clique em um elemento na prévia ou na timeline para ajustar posição, tempo, estilo e animação.")); return; }
  const legs = l.filter((x) => ["legenda", "texto"].includes(x.tipo));
  if (!i && legs.length !== l.length) { c.replaceChildren(el("h2", {}, `${l.length} elementos`), el("p", { class: "dica" }, "Use Dividir, Duplicar ou Apagar na timeline.")); return; }
  const b = i || legs[0], blocos = [el("h2", {}, i ? `${ROTULOS[i.tipo]}` : `${l.length} textos selecionados`)];
  if (i?.tipo === "video") blocos.push(sec("", btn("Reenquadrar vídeo", () => abrirReenquadrar(i), "botao principal rq-abrir"), el("p", { class: "dica" }, "Mostre as laterais que ficaram de fora.")));
  if (i) blocos.push(secTempo(i));
  if (["video", "imagem", "forma"].includes(b.tipo)) {
    blocos.push(sec("Posição e tamanho", campoT(b, "x", "X", { min: -S.p.largura, max: S.p.largura * 2 }), campoT(b, "y", "Y", { min: -S.p.altura, max: S.p.altura * 2 }), campoT(b, "escala", "Escala", { min: .05, max: 5, step: .01 }), campoT(b, "rot", "Rotação", { min: -180, max: 180 }), campoT(b, "opac", "Opacidade", { min: 0, max: 100 }), campoT(b, "w", "Largura", { min: 10, max: S.p.largura * 2 }), campoT(b, "h", "Altura", { min: 10, max: S.p.altura * 2 }),
      el("div", { class: "st-botoes" }, ...[["e", "Esquerda"], ["c", "Centro"], ["d", "Direita"], ["t", "Topo"], ["m", "Meio"], ["b", "Base"]].map(([m, t]) => btn(t, () => alinhar(b, m))))));
    if (b.tipo !== "forma") {
      const mao = marca("Ajustar arrastando na prévia", S.zoomMao, (v) => { S.zoomMao = v; });
      if (b.tipo === "video" && i) blocos.push(secPontos(b));
      blocos.push(sec("Zoom e enquadramento", mao, campoT(b, "zoom", "Zoom", { min: 1, max: 5, step: .01 }), campoT(b, "zx", "Foco X", { min: 0, max: 1, step: .005 }), campoT(b, "zy", "Foco Y", { min: 0, max: 1, step: .005 }), campo("Força", { get: () => b.zoom_forca ?? 100, set: (v) => { b.zoom_forca = v; }, min: 0, max: 200 })),
        sec("Recorte", campoT(b, "cl", "Esquerda", { min: 0, max: .9, step: .005 }), campoT(b, "cr", "Direita", { min: 0, max: .9, step: .005 }), campoT(b, "ct", "Topo", { min: 0, max: .9, step: .005 }), campoT(b, "cb", "Base", { min: 0, max: .9, step: .005 })));
      const fil = () => b.filtro || {}, aj = (k, rot, a, z) => campo(rot, { get: () => b.ajustes?.[k] ?? 0, set: (v) => { (b.ajustes ||= {})[k] = v; }, min: a, max: z });
      blocos.push(sec("Transição de entrada", escolha("Tipo", TRANS, b.transicao?.tipo || "corte", (v) => { b.transicao = { tipo: v, dur: b.transicao?.dur ?? .4 }; }), campo("Duração", { get: () => b.transicao?.dur ?? .4, set: (v) => { b.transicao = { tipo: b.transicao?.tipo || "corte", dur: v }; }, min: .1, max: 2, step: .05 })),
        sec("Cor", escolha("Filtro", [["", "Igual ao projeto"], ...S.filtros.map((f) => [f.id, f.nome])], fil().nome || "", (v) => { b.filtro = v ? { nome: v, forca: fil().forca ?? 100 } : null; }), campo("Intensidade", { get: () => fil().forca ?? 100, set: (v) => { if (b.filtro) b.filtro.forca = v; } }), aj("brilho", "Brilho", -60, 60), aj("contraste", "Contraste", -60, 60), aj("saturacao", "Saturação", -100, 100), aj("temperatura", "Temperatura", -100, 100), aj("desfoque", "Desfoque", 0, 60)));
    } else blocos.push(sec("Aparência", corCampo("Cor", b.cor, (v) => { b.cor = v; }), campo("Opacidade", { get: () => b.cor_opac ?? 100, set: (v) => { b.cor_opac = v; } }), campo("Arredondar", { get: () => b.raio ?? 0, set: (v) => { b.raio = v; }, max: 200 }), campo("Borda", { get: () => b.borda ?? 0, set: (v) => { b.borda = v; }, max: 40 }), corCampo("Cor borda", b.borda_cor, (v) => { b.borda_cor = v; })));
    if (b.tipo === "video") blocos.push(sec("Som e velocidade", campo("Volume", { get: () => b.volume ?? 100, set: (v) => { b.volume = v; }, max: 200 }), marca("Sem som", b.mudo, (v) => { b.mudo = v; }), campo("Velocidade", { get: () => b.velocidade ?? 1, set: (v) => { const f = (b.velocidade ?? 1) / v; b.velocidade = v; b.dur = arred(b.dur * f); }, min: .25, max: 4, step: .05 })));
  } else if (b.tipo === "legenda" || b.tipo === "texto") {
    const t = el("textarea", { "aria-label": "Texto" }); t.value = b.texto;
    t.addEventListener("change", () => { antes(); b.texto = t.value; if (b.palavras) { const ps = t.value.split(/\s+/).filter(Boolean), tot = ps.reduce((s, p) => s + p.length + 1, 0) || 1; let pos = 0; b.palavras = ps.map((p) => { const d = b.dur * (p.length + 1) / tot, w = { p, ini: arred(pos), fim: arred(pos + d) }; pos += d; return w; }); } mudou(); desenharLinha(); });
    if (i) blocos.push(sec("Texto", t));
    const est = () => estiloDe(b), por = (k, v) => { for (const x of legs) (x.estilo ||= {})[k] = v; };
    if (b.tipo === "legenda") {
      const grupo = el("input", { type: "text", value: b.grupo || "", placeholder: "Nome do grupo" }); grupo.addEventListener("change", () => { antes(); for (const x of legs) x.grupo = grupo.value.trim(); mudou(true); });
      const todas = () => itens().filter(([, x]) => x.tipo === "legenda").map(([, x]) => x);
      blocos.push(sec("Aplicar este estilo", btn("Aplicar a todas as legendas", () => { antes(); S.p.global.legenda = { ...S.p.global.legenda, ...b.estilo }; todas().forEach((x) => { x.estilo = {}; }); mudou(true); avisar("Estilo aplicado a todas as legendas"); }, "botao destaque"),
        l.length > 1 ? btn(`Aplicar às ${l.length} selecionadas`, () => { antes(); legs.forEach((x) => { x.estilo = { ...b.estilo }; }); mudou(true); }) : null, linha("Grupo", grupo),
        b.grupo ? btn(`Aplicar ao grupo ${b.grupo}`, () => { antes(); todas().filter((x) => x.grupo === b.grupo).forEach((x) => { x.estilo = { ...b.estilo }; }); mudou(true); }) : null, btn("Voltar ao estilo global", () => { antes(); legs.forEach((x) => { x.estilo = {}; }); mudou(true); })),
        sec("Posição", campo("X", { get: () => est().x ?? S.p.largura / 2, set: (v) => por("x", v), max: S.p.largura }), campo("Y", { get: () => est().y ?? S.p.altura * .86, set: (v) => por("y", v), max: S.p.altura })));
    } else if (i) blocos.push(sec("Posição", campoT(b, "x", "X", { min: -200, max: S.p.largura + 200 }), campoT(b, "y", "Y", { min: -200, max: S.p.altura + 200 }), campoT(b, "escala", "Escala", { min: .1, max: 6, step: .01 }), campoT(b, "rot", "Rotação", { min: -180, max: 180 }), campoT(b, "opac", "Opacidade", { min: 0, max: 100 }), el("div", { class: "st-botoes" }, ...[["e", "Esquerda"], ["c", "Centro"], ["d", "Direita"], ["t", "Topo"], ["m", "Meio"], ["b", "Base"]].map(([m, x]) => btn(x, () => alinhar(b, m))))));
    blocos.push(sec("Efeito do texto", escolha("Efeito", EF_TEXTO, est().efeito_texto, (v) => por("efeito_texto", v)), campo("Força", { get: () => est().efeito_forca, set: (v) => por("efeito_forca", v), min: 0, max: 200 })));
    blocos.push(...controlesEstilo(est, por));
  } else if (b.tipo === "efeito") {
    blocos.push(sec("Efeito", escolha("Tipo", EFEITOS, b.efeito, (v) => { b.efeito = v; }), campo("Força", { get: () => b.forca ?? 1, set: (v) => { b.forca = v; }, min: 0, max: b.efeito === "tremor" ? 30 : 1, step: b.efeito === "tremor" ? .5 : .01 }), b.efeito === "filtro" ? escolha("Filtro", S.filtros.map((f) => [f.id, f.nome]), b.filtro, (v) => { b.filtro = v; }) : null, b.efeito === "progresso" ? corCampo("Cor", b.cor, (v) => { b.cor = v; }) : null));
  } else if (b.tipo === "audio") {
    blocos.push(sec("Áudio", el("p", {}, b.nome), escolha("Tipo", [["efeito", "Efeito sonoro"], ["musica", "Música de fundo"], ["voz", "Voz"]], b.categoria || "efeito", (v) => { b.categoria = v; }), campo("Volume", { get: () => b.volume ?? 100, set: (v) => { b.volume = v; }, max: 200 }), campo("Entrada suave", { get: () => b.fade_in ?? 0, set: (v) => { b.fade_in = v; }, max: 10, step: .1 }), campo("Saída suave", { get: () => b.fade_out ?? 0, set: (v) => { b.fade_out = v; }, max: 10, step: .1 })));
  }
  c.replaceChildren(...blocos);
}

/* ---------- Painéis ---------- */
const ICONE_RAIL = { midia: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9l5 3-5 3z"/>', texto: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>', sons: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>', efeitos: '<path d="M12 3l2 5.5L19.5 10 14 12l-2 6-2-6-5.5-2L10 8.5z"/><path d="M19 16v4M17 18h4"/>', transicoes: '<path d="M4 5l8 7-8 7zM20 5l-8 7 8 7z"/>', cenas: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4v5M16 4v5"/>', ia: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><rect x="7" y="7" width="10" height="10" rx="2"/>', global: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>' };
const RAIL_VIDEO = [["midia", "Mídia"], ["texto", "Textos"], ["sons", "Sons"], ["efeitos", "Efeitos"], ["transicoes", "Transições"], ["cenas", "Cenas"], ["ia", "IA"], ["global", "Global"]], RAIL_CAPA = [["camadas", "Camadas"], ["modelos", "Modelos"]];
function montarRail() { const l = cap() ? RAIL_CAPA : RAIL_VIDEO; if (!l.some(([k]) => k === S.painel)) S.painel = l[0][0]; $("#st-rail").replaceChildren(...l.map(([k, n]) => { const b = el("button", { type: "button", role: "tab", "aria-selected": String(k === S.painel), onclick: () => abrirPainel(k) }); if (ICONE_RAIL[k]) b.innerHTML = svg(ICONE_RAIL[k]).replace('width="14" height="14"', 'width="20" height="20"'); b.append(el("span", {}, n)); return b; })); }
function abrirPainel(k) { fecharPrevia(); S.painel = k; montarRail(); montarPainel(); }
function montarPainel() { if (!S.aberto) return; const c = $("#st-painel"); const fn = { midia: pMidia, texto: pTexto, sons: pSons, efeitos: pEfeitos, transicoes: pTransicoes, cenas: pCenas, ia: pIa, global: pGlobal, camadas: pCamadas, modelos: pModelos }[S.painel]; if (S.painel === "sons" && c.dataset.p === "sons") return; c.dataset.p = S.painel; c.replaceChildren(...fn()); }
function faixaLivre(tipo, ini, dur) { const f = S.p.faixas.find((x) => x.tipo === tipo && !x.travada && !x.itens.some((i) => i.ini < ini + dur && i.ini + i.dur > ini)); if (f) return f; const n = novaFaixa(tipo); montarCabecas(); return n; }
function colocar(tipo, item) { antes(); item.id ||= nid(); item.ini = arred(S.t); faixaLivre(tipo, item.ini, item.dur).itens.push(item); S.sel = new Set([item.id]); mudou(true); montarCabecas(); }
function usarMidia(m) {
  S.p.midias[m.id] = m; const W = S.p.largura, H = S.p.altura;
  if (m.tipo === "audio") return colocar("audio", { tipo: "audio", nome: m.nome, midia: m.id, dur: arred(m.dur), entrada: 0, volume: m.dur > 20 ? 40 : 80, categoria: m.dur > 20 ? "musica" : "efeito" });
  const e = Math.min(W / (m.lar || W), H / (m.alt || H)) * (m.tipo === "imagem" ? .6 : 1);
  colocar("video", { tipo: m.tipo, nome: m.nome, midia: m.id, dur: arred(m.tipo === "video" ? m.dur : 5), entrada: 0, velocidade: 1, volume: 100, t: { x: W / 2, y: H / 2, w: arred((m.lar || W) * e, 1), h: arred((m.alt || H) * e, 1), escala: 1, rot: 0, opac: 100, zoom: 1, zx: .5, zy: .5, cl: 0, ct: 0, cr: 0, cb: 0 }, kf: {} });
}
function envioArquivos(accept, fn) { const n = el("input", { type: "file", accept, multiple: "", hidden: "" }); n.addEventListener("change", async () => { for (const a of [...n.files]) { $("#st-salvo").textContent = `Enviando ${a.name}…`; try { const r = await fetch(`/api/estudio/midia?nome=${encodeURIComponent(a.name)}`, { method: "POST", body: a }), d = await r.json(); if (!r.ok) throw new Error(d.erro); fn(d); } catch (e) { avisar(e.message); } } $("#st-salvo").textContent = ""; n.value = ""; }); return n; }
function pMidia() {
  const inp = envioArquivos("image/*,video/*,audio/*", usarMidia), l = Object.values(S.p.midias).filter((m) => m.raiz !== "som");
  return [el("h2", {}, "Mídia"), btn("Enviar imagem, vídeo ou áudio", () => inp.click(), "botao destaque"), inp, el("div", { class: "st-midias" }, ...l.map((m) => el("button", { class: "st-midia", type: "button", title: "Adicionar na agulha", onclick: () => usarMidia(m) }, m.tipo === "imagem" ? el("img", { src: urlMidia(m), alt: "", loading: "lazy" }) : m.tipo === "video" ? el("video", { src: `${urlMidia(m)}#t=1`, preload: "metadata", muted: "" }) : null, el("span", {}, m.nome || ROTULOS[m.tipo]))))];
}
function trabalho(nome, corpo, b, fim) {
  const txt = b.textContent; b.disabled = true; b.textContent = "Ouvindo o vídeo…"; const fimB = () => { b.disabled = false; b.textContent = txt; };
  api("POST", `/api/estudio/${S.tipo}/${S.id}/${nome}`, corpo).then(async () => { for (;;) { await new Promise((r) => setTimeout(r, 1500)); const r = await api("GET", `/api/estudio/${S.tipo}/${S.id}/trabalho/${nome}`); if (r.estado === "erro") throw new Error(r.erro); if (r.estado === "pronto") { antes(); S.p = r.projeto; fim(); mudou(true); montarCabecas(); break; } } }).catch((e) => avisar(e.message)).finally(fimB);
}
const MODELOS_LEGENDA = [
  ["Viral amarelo", { fonte: "Anton", tamanho: 74, cor: "#FFFFFF", cor_destaque: "#FFD400", contorno: 8, maiusculas: true, destaque: "palavra", destaque_caixa: false, palavra_a_palavra: false, fundo: false, sombra: true, entrada: "pop" }],
  ["Caixa verde", { fonte: "Montserrat-Black", tamanho: 58, cor: "#FFFFFF", cor_destaque: "#2BE36B", contorno: 6, maiusculas: true, destaque: "palavra", destaque_caixa: true, palavra_a_palavra: false, fundo: false, sombra: true, entrada: "pop" }],
  ["Uma palavra", { fonte: "Poppins-Black", tamanho: 86, cor: "#FFFFFF", cor_destaque: "#FFC933", contorno: 9, maiusculas: false, destaque: "importantes", destaque_caixa: false, palavra_a_palavra: true, fundo: false, sombra: true, entrada: "pop" }],
  ["Desenho", { fonte: "Luckiest-Guy", tamanho: 76, cor: "#FFE14D", cor_destaque: "#FF4B5C", contorno: 9, maiusculas: true, destaque: "palavra", destaque_caixa: false, palavra_a_palavra: false, fundo: false, sombra: true, entrada: "quique" }],
  ["Quadrinho", { fonte: "Bangers", tamanho: 84, cor: "#141414", cor_destaque: "#D7263D", contorno: 0, maiusculas: true, destaque: "palavra", destaque_caixa: false, palavra_a_palavra: false, fundo: true, fundo_cor: "#FFE14D", fundo_opac: 100, fundo_raio: 6, borda: 4, borda_cor: "#141414", sombra: false, entrada: "pop" }],
  ["Gamer", { fonte: "Orbitron-Black", tamanho: 54, cor: "#E9FBFF", cor_destaque: "#00E5FF", contorno: 5, maiusculas: true, destaque: "palavra", destaque_caixa: false, palavra_a_palavra: false, fundo: false, sombra: true, sombra_cor: "#00E5FF", sombra_y: 0, sombra_blur: 14, sombra_opac: 90, entrada: "zoom" }],
  ["Neon rosa", { fonte: "Audiowide", tamanho: 60, cor: "#FF5FCF", cor_destaque: "#FFFFFF", contorno: 0, maiusculas: false, destaque: "palavra", destaque_caixa: false, palavra_a_palavra: false, fundo: false, sombra: true, sombra_cor: "#FF5FCF", sombra_y: 0, sombra_blur: 18, sombra_opac: 100, entrada: "fade" }],
  ["Cinema", { fonte: "Bebas-Neue", tamanho: 70, cor: "#F6F0E4", cor_destaque: "#F2B544", contorno: 0, espacamento: 4, maiusculas: true, destaque: "nenhum", destaque_caixa: false, palavra_a_palavra: false, fundo: false, sombra: true, sombra_y: 3, sombra_blur: 10, entrada: "fade", saida: "fade" }],
  ["Terror", { fonte: "Creepster", tamanho: 80, cor: "#E5383B", cor_destaque: "#FFFFFF", contorno: 5, maiusculas: true, destaque: "palavra", destaque_caixa: false, palavra_a_palavra: false, fundo: false, sombra: true, entrada: "quique" }],
  ["Faixa preta", { fonte: "Kanit-Black", tamanho: 56, cor: "#FFFFFF", cor_destaque: "#FFC933", contorno: 0, maiusculas: false, destaque: "palavra", destaque_caixa: false, palavra_a_palavra: false, fundo: true, fundo_cor: "#101010", fundo_opac: 88, fundo_raio: 14, borda: 0, sombra: false, entrada: "subir" }],
  ["Pincel", { fonte: "Caveat-Brush", tamanho: 86, cor: "#FFFFFF", cor_destaque: "#5AD1B3", contorno: 6, maiusculas: false, destaque: "importantes", destaque_caixa: false, palavra_a_palavra: false, fundo: false, sombra: true, entrada: "fade" }],
  ["Arcade", { fonte: "Press-Start-2P", tamanho: 38, cor: "#FFFFFF", cor_destaque: "#39FF88", contorno: 5, maiusculas: true, destaque: "palavra", destaque_caixa: false, palavra_a_palavra: false, fundo: false, sombra: false, entrada: "digitando" }],
];
function modeloEm(p, m) { const base = { fundo: false, borda: 0, espacamento: 0, saida: "nenhuma", sombra_cor: "#000000", sombra_x: 0, sombra_y: 4, sombra_blur: 6, sombra_opac: 60 }; p.global.legenda = { ...p.global.legenda, ...base, ...m }; p.faixas.forEach((f) => f.itens.forEach((i) => { if (i.tipo === "legenda") i.estilo = {}; })); }
function aplicarModeloLegenda(m) { antes(); modeloEm(S.p, m); mudou(true); avisar("Modelo aplicado a todas as legendas"); }
const cartaoModelo = ([nome, m]) => { const b = cartaoPrevia(btn(nome, null, "st-modelo"), () => { const l = textoDaPrevia(), ini = l?.tipo === "legenda" ? l.ini : S.t; return { chave: `modelo:${nome}:${ini}`, nome: `Modelo ${nome}`, ini, fim: ini + 2.6, mudar: (p) => modeloEm(p, m), aplicar: () => aplicarModeloLegenda(m) }; }); Object.assign(b.style, { fontFamily: fonteCss(m.fonte), color: m.fundo ? m.cor : m.cor_destaque, background: m.fundo ? m.fundo_cor : "#0b1518" }); return b; };
/* ---------- Modelos de título, como no CapCut ---------- */
let modelosTitulo = null;
function alvoTitulo() { const s = sel1(); if (s?.tipo === "texto") return s; return itens().map(([, i]) => i).find((i) => i.papel === "gancho") || null; }
function vestirTitulo(i, m) { i.estilo = { ...(i.estilo || {}), fundo: false, contorno: 0, sombra: false, borda: 0, efeito_texto: "nenhum", ...clonar(m.estilo) }; i.t = { ...(i.t || {}), rot: m.rot }; }
function secTitulos() {
  const grade = el("div", { class: "st-modelos st-titulos" }), alvo = alvoTitulo();
  const dica = el("p", { class: "dica" }, alvo ? `Clique para ver e aplicar em: ${alvo.nome || "Título"}.` : "Clique para ver e colocar um título novo onde está a agulha.");
  const cartao = (m) => {
    const nome = (MODELOS_GANCHO.find(([v]) => v === m.id) || [, m.id])[1], e = m.estilo, b = btn(nome, null, "st-modelo st-titulo-cartao");
    Object.assign(b.style, { fontFamily: fonteCss(e.fonte), color: e.cor, background: e.fundo === false ? "#0b1518" : e.fundo_cor, textTransform: e.maiusculas === false ? "none" : "uppercase", WebkitTextStroke: e.contorno ? `1.5px ${e.contorno_cor || "#000"}` : "", textShadow: e.sombra ? `2px 2px 0 ${e.sombra_cor || "#000"}` : "", transform: m.rot ? `rotate(${m.rot}deg)` : "", outline: e.borda ? `2px solid ${e.borda_cor}` : "" });
    return cartaoPrevia(b, () => {
      const a = alvoTitulo(), ini = a ? a.ini : S.t;
      const novo = () => ({ tipo: "texto", nome: "Título", dur: 3, texto: "SEU TÍTULO AQUI", estilo: {}, t: { x: S.p.largura / 2, y: S.p.altura * .2, escala: 1, rot: 0, opac: 100 }, kf: {} });
      return { chave: `titulo:${m.id}:${a?.id || S.t}`, nome: `Título ${nome}`, ini, fim: ini + 1.6, fps: 16,
        mudar: (p) => { if (a) { const i = p.faixas.flatMap((f) => f.itens).find((x) => x.id === a.id); if (i) vestirTitulo(i, m); } else { const i = novo(); vestirTitulo(i, m); entrarNaFaixa(p, "texto", i); } },
        aplicar: () => { if (a) { antes(); vestirTitulo(a, m); mudou(true); selecaoMudou(); avisar(`Título ${nome} aplicado`); } else { const i = novo(); vestirTitulo(i, m); colocar("texto", i); } } };
    });
  };
  const encher = (l) => grade.replaceChildren(...l.map(cartao));
  if (modelosTitulo) encher(modelosTitulo); else { grade.append(el("p", { class: "dica" }, "Carregando modelos")); fetch("/api/estudio/modelos-titulo").then((r) => r.json()).then((l) => { modelosTitulo = l; encher(l); }).catch(() => grade.replaceChildren(el("p", { class: "dica" }, "Não foi possível carregar os modelos."))); }
  return sec("Modelos de título", dica, grade);
}
function pTexto() {
  const W = S.p.largura, H = S.p.altura, item = (txt, est) => ({ tipo: "texto", nome: "Texto", dur: 4, texto: txt, estilo: est, t: { x: W / 2, y: H / 2, escala: 1, rot: 0, opac: 100 }, kf: {} });
  const tx = (nome, txt, est) => cartaoPrevia(btn(nome, null), () => ({ chave: `texto:${nome}:${S.t}`, nome, ini: S.t, fim: S.t + 1.2, fps: 16, mudar: (p) => entrarNaFaixa(p, "texto", item(txt, est)), aplicar: () => colocar("texto", item(txt, est)) }));
  const des = el("input", { type: "number", value: "0", step: ".05", "aria-label": "Atraso em segundos" });
  const gerar = btn("Gerar legendas de novo", (ev) => confirmar(ev.currentTarget, "Trocar todas", () => trabalho("legendas", { projeto: S.p }, gerar, () => avisar("Legendas geradas"))));
  return [el("h2", {}, "Textos e elementos"), el("div", { class: "st-botoes" }, tx("Texto", "Seu texto aqui", { tamanho: 72, contorno: 6 }), tx("Título grande", "TÍTULO", { fonte: "Anton", tamanho: 150, cor: "#FFC933", contorno: 10, entrada: "pop", tempo_anim: .25 }), tx("Faixa", "Faixa de destaque", { tamanho: 56, fundo: true, fundo_cor: "#FFC933", cor: "#141414", fundo_opac: 100 })),
    el("div", { class: "st-botoes" }, ...[["retangulo", "Retângulo"], ["circulo", "Círculo"]].map(([f, n]) => btn(n, () => colocar("video", { tipo: "forma", forma: f, nome: n, dur: 4, cor: "#FFC933", t: { x: W / 2, y: H / 2, w: 420, h: f === "circulo" ? 420 : 220, escala: 1, rot: 0, opac: 100 }, kf: {} })))),
    secTitulos(),
    sec("Modelos de legenda", el("div", { class: "st-modelos" }, ...MODELOS_LEGENDA.map(cartaoModelo))),
    sec("Legendas", gerar, linha("Atrasar (s)", des), btn("Mover todas as legendas", () => { const d = +des.value; if (!d) return; antes(); itens().forEach(([, i]) => { if (i.tipo === "legenda") i.ini = Math.max(0, arred(i.ini + d)); }); mudou(); avisar("Sincronia ajustada"); }))];
}
/* ---------- Prévia: mostra o resultado numa cópia do projeto, sem mudar o vídeo ---------- */
const pv = { caixa: $("#st-pv"), img: $("#st-pv-img"), carga: $("#st-pv-carga"), nome: $("#st-pv-nome"), seq: 0, relogio: 0, atual: null, cache: new Map(), rev: -1, cartao: null };
function fecharPrevia() { if (!pv.atual) return; pv.seq++; pv.atual = null; clearTimeout(pv.relogio); pv.caixa.hidden = true; pv.img.removeAttribute("src"); pv.cartao?.removeAttribute("data-vendo"); pv.cartao = null; }
function rodarPrevia(q, fps) { let n = 0; const seq = pv.seq, passo = () => { if (seq !== pv.seq) return; pv.img.src = `data:image/jpeg;base64,${q[n]}`; const fim = n === q.length - 1; n = fim ? 0 : n + 1; pv.relogio = setTimeout(passo, fim ? 650 : 1000 / fps); }; passo(); }
async function verPrevia(spec, cartao) {
  fecharPrevia(); pausar(); const seq = ++pv.seq; pv.atual = spec; pv.cartao = cartao || null; cartao?.setAttribute("data-vendo", "1");
  pv.nome.textContent = spec.nome; pv.caixa.hidden = false; pv.carga.hidden = false; pv.img.hidden = true;
  if (pv.rev !== (S.rev || 0)) { pv.cache.clear(); pv.rev = S.rev || 0; }
  const ini = Math.max(0, spec.ini), fim = Math.min(duracao() + .5, Math.max(ini + .4, spec.fim)), fps = spec.fps || 12, chave = `${spec.chave}|${ini.toFixed(2)}|${fim.toFixed(2)}`;
  try {
    let q = pv.cache.get(chave);
    if (!q) { const copia = clonar(S.p); spec.mudar(copia); const r = await api("POST", `/api/estudio/${S.tipo}/${S.id}/previa`, { projeto: copia, ini, fim, fps, altura: 720 }); if (seq !== pv.seq || r.cancelada) return; q = r.quadros; pv.cache.set(chave, q); }
    if (seq !== pv.seq) return; if (!q.length) throw new Error("Não foi possível montar a prévia deste trecho");
    pv.carga.hidden = true; pv.img.hidden = false; rodarPrevia(q, fps);
  } catch (e) { if (seq === pv.seq) { fecharPrevia(); avisar(e.message); } }
}
$("#st-pv-cancelar").addEventListener("click", fecharPrevia);
$("#st-pv-aplicar").addEventListener("click", () => { const s = pv.atual; if (!s) return; fecharPrevia(); s.aplicar(); });
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && pv.atual) { ev.stopPropagation(); fecharPrevia(); } }, true);
const cartaoPrevia = (n, spec) => { n.addEventListener("click", () => { const s = spec(); if (s) verPrevia(s, n); }); return n; };
function entrarNaFaixa(p, tipo, item) { let f = p.faixas.find((x) => x.tipo === tipo); if (!f) { f = { id: nid("f"), tipo, nome: tipo, oculta: false, muda: false, travada: false, itens: [] }; p.faixas.push(f); } f.itens.push({ ...clonar(item), id: nid(), ini: arred(S.t) }); }
function textoDaPrevia() { const sel = selecionados().find((i) => ["texto", "legenda"].includes(i.tipo)); if (sel) return sel; const l = itens().map(([, i]) => i).filter((i) => ["texto", "legenda"].includes(i.tipo)), leg = l.filter((i) => i.tipo === "legenda"); return leg.find((i) => S.t >= i.ini && S.t < i.ini + i.dur) || leg.find((i) => i.ini >= S.t) || leg[0] || l[0] || null; }

/* ---------- Efeitos ---------- */
function pEfeitos() {
  S.abaFx ||= "texto";
  const abas = el("div", { class: "st-modo st-fx-abas", role: "group", "aria-label": "Tipo de efeito" }, ...[["texto", "Texto"], ["video", "Vídeo"]].map(([k, n]) => el("button", { type: "button", "aria-pressed": String(S.abaFx === k), onclick: () => { S.abaFx = k; montarPainel(); } }, n)));
  if (S.abaFx === "video") return [el("h2", {}, "Efeitos"), abas, el("p", { class: "dica" }, "Clique para ver a prévia. O vídeo só muda quando você aplicar."), el("div", { class: "st-fx-grade" }, ...EFEITOS.map(([id, nome]) => cartaoPrevia(el("button", { class: "st-fx-card video", type: "button", dados: { fx: id } }, el("span", { class: "st-fx-am" }, ""), el("small", {}, nome)), () => { const item = { tipo: "efeito", efeito: id, nome, dur: id === "progresso" ? arred(duracao()) : 1.2, forca: id === "tremor" ? 8 : .7, filtro: "cinema", cor: "#FFC933" }; return { chave: `fx:${id}:${S.t}`, nome, ini: S.t, fim: S.t + 1.6, mudar: (p) => entrarNaFaixa(p, "efeito", item), aplicar: () => colocar("efeito", item) }; }))),
    sec("Filtros de cor", el("div", { class: "st-fx-grade" }, ...S.filtros.filter((f) => f.id !== "nenhum").map((f) => cartaoPrevia(el("button", { class: "st-fx-card video", type: "button", "aria-pressed": String(S.p.global.filtro?.nome === f.id) }, el("span", { class: "st-fx-am" }, ""), el("small", {}, f.nome)), () => { const v = { nome: f.id, forca: S.p.global.filtro?.forca ?? 100 }; return { chave: `filtro:${f.id}:${S.t}`, nome: f.nome, ini: S.t, fim: S.t + 1.2, fps: 8, mudar: (p) => { p.global.filtro = v; }, aplicar: () => { antes(); S.p.global.filtro = v; mudou(true); avisar(`Filtro ${f.nome} aplicado`); } }; }))))];
  const alvo = selecionados().filter((i) => ["texto", "legenda"].includes(i.tipo)), L = () => (S.p.global.legenda ||= {}), legendas = () => itens().filter(([, i]) => i.tipo === "legenda").map(([, i]) => i);
  const est = alvo[0] ? estiloDe(alvo[0]) : { ...PAD_EST, ...L() }, por = (k, v) => { if (alvo.length) alvo.forEach((x) => { (x.estilo ||= {})[k] = v; }); else { L()[k] = v; legendas().forEach((x) => { if (x.estilo) delete x.estilo[k]; }); } };
  const ids = new Set(alvo.map((i) => i.id));
  const porEm = (p, mud) => { const lista = p.faixas.flatMap((f) => f.itens); if (ids.size) lista.filter((i) => ids.has(i.id)).forEach((x) => { x.estilo = { ...(x.estilo || {}), ...mud }; }); else { p.global.legenda = { ...(p.global.legenda || {}), ...mud }; lista.filter((i) => i.tipo === "legenda" && i.estilo).forEach((x) => { for (const k of Object.keys(mud)) delete x.estilo[k]; }); } };
  const specTexto = (nome, mud, trecho) => () => { const b = textoDaPrevia(); if (!b) { avisar("Adicione um texto ou gere as legendas para ver a prévia"); return null; } const [ini, fim, fps] = trecho(b); return { chave: `txt:${JSON.stringify(mud)}:${[...ids]}:${b.id}`, nome, ini, fim, fps, mudar: (p) => { porEm(p, mud); }, aplicar: () => { antes(); Object.entries(mud).forEach(([k, v]) => por(k, v)); mudou(true); avisar(`${nome} aplicado`); } }; };
  const corrido = (b) => [b.ini, b.ini + 2.6, 12], inicio = (b) => [b.ini, b.ini + 1, 24], saindo = (b) => [Math.max(b.ini, b.ini + b.dur - 1), b.ini + b.dur + .1, 24];
  const cartaoAnim = (k, trecho) => ([id, nome]) => cartaoPrevia(el("button", { class: "st-fx-card", type: "button", "aria-pressed": String((est[k] || "nenhuma") === id) }, el("span", { class: "st-fx-am" }, "Aa"), el("small", {}, nome)), specTexto(`${k === "entrada" ? "Entrada" : "Saída"}: ${nome}`, { [k]: id, tempo_anim: Math.max(est.tempo_anim ?? .15, .35) }, trecho));
  const rotulo = `Clique para ver a prévia. ${alvo.length === 1 ? (alvo[0].tipo === "legenda" ? "Vale para esta legenda" : "Vale para este texto") : alvo.length ? `Vale para ${alvo.length} selecionados` : "Vale para todas as legendas. Selecione um texto para mudar só ele"}.`;
  return [el("h2", {}, "Efeitos"), abas, el("p", { class: "dica" }, rotulo),
    el("div", { class: "st-fx-grade" }, ...EF_TEXTO.map(([id, nome]) => cartaoPrevia(el("button", { class: "st-fx-card", type: "button", "aria-pressed": String((est.efeito_texto || "nenhum") === id), dados: { fx: id } }, el("span", { class: "st-fx-am" }, "Aa"), el("small", {}, nome)), specTexto(nome, { efeito_texto: id, efeito_forca: est.efeito_forca ?? 100 }, corrido)))),
    sec("Ajuste", campo("Força", { get: () => est.efeito_forca ?? 100, set: (v) => { est.efeito_forca = v; por("efeito_forca", v); }, min: 0, max: 200 }), alvo.length ? btn("Usar em todas as legendas", () => { antes(); L().efeito_texto = est.efeito_texto; L().efeito_forca = est.efeito_forca ?? 100; legendas().forEach((x) => { if (x.estilo) { delete x.estilo.efeito_texto; delete x.estilo.efeito_forca; } }); mudou(true); avisar("Efeito aplicado em todas as legendas"); }) : null),
    sec("Animação de entrada", el("div", { class: "st-fx-grade" }, ...ANIM.map(cartaoAnim("entrada", inicio)))), sec("Animação de saída", el("div", { class: "st-fx-grade" }, ...ANIM.filter(([id]) => id !== "digitando").map(cartaoAnim("saida", saindo))))];
}

/* ---------- Transições ---------- */
const NOMES_TR = { dissolver: "Dissolver", preto: "Pelo preto", branco: "Clarão branco", zoom: "Zoom", esquerda: "Para a esquerda", direita: "Para a direita", cima: "Para cima", baixo: "Para baixo", chicote: "Chicote", queda: "Chicote vertical", impulso: "Impulso", giro: "Giro", glitch: "Glitch", rgb: "Cores separadas", clarao_rapido: "Clarão rápido", desfoque_rapido: "Desfoque rápido" };
const GRUPOS_TR = [["Suaves", ["dissolver", "preto", "branco", "zoom"]], ["Deslizar", ["esquerda", "direita", "cima", "baixo"]], ["Impacto", ["chicote", "queda", "impulso", "giro", "glitch", "rgb", "clarao_rapido", "desfoque_rapido"]]];
const nomeTr = (t) => NOMES_TR[t] || "Corte seco", visual = (i) => ["video", "imagem"].includes(i.tipo);
function ehCorte(f, i) { return visual(i) && i.ini > .05 && f.itens.some((x) => x !== i && visual(x) && Math.abs(x.ini + x.dur - i.ini) < .08); }
function listaCortes() { const m = new Map(); for (const f of S.p.faixas) if (f.tipo === "video") for (const i of f.itens) if (ehCorte(f, i)) { const k = [...m.keys()].find((t) => Math.abs(t - i.ini) < .08) ?? i.ini; m.set(k, [...(m.get(k) || []), i]); } return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([t, l]) => ({ t, itens: l })); }
function alvoTr(t = S.t, raio = .75) { let m = null; for (const c of listaCortes()) if (Math.abs(c.t - t) <= raio && (!m || Math.abs(c.t - t) < Math.abs(m.t - t))) m = c; return m; }
const cortaveis = (t) => S.p.faixas.filter((f) => f.tipo === "video" && !f.travada).flatMap((f) => f.itens.filter((i) => visual(i) && t > i.ini + .2 && t < i.ini + i.dur - .2).map((i) => [f, i]));
function usarTransicao(tipo, t = S.t, raio = .75) {
  pausar(); let c = alvoTr(t, raio); const ponto = arred(t);
  if (!c && !cortaveis(ponto).length) { avisar("Leve a agulha para cima do vídeo, longe do começo e do fim da cena"); return; }
  antes();
  if (!c) { for (const [f, i] of cortaveis(ponto)) { const [a, b] = partir(i, ponto); f.itens.splice(f.itens.indexOf(i), 1, a, b); } c = alvoTr(ponto, .1); }
  const dur = S.durTr ?? .5; c.itens.forEach((i) => { i.transicao = { tipo, dur }; }); mudou(true);
  clearTimeout(S.tempoTr); irPara(Math.max(0, c.t - .5)); tocar(); S.tempoTr = setTimeout(() => { if (S.tocando) pausar(); irPara(c.t); }, (1 + dur) * 1000);
  avisar(`${nomeTr(tipo)} aplicada em ${tempoTxt(c.t)}`);
}
function specTransicao(tipo) {
  const c = alvoTr(), ponto = c ? c.t : arred(S.t), dur = S.durTr ?? .5; if (!c && !cortaveis(ponto).length) { avisar("Leve a agulha para cima do vídeo, longe do começo e do fim da cena"); return null; }
  return { chave: `tr:${tipo}:${ponto}:${dur}`, nome: nomeTr(tipo), ini: ponto - .45, fim: ponto + dur + .45, fps: 16, aplicar: () => usarTransicao(tipo, ponto),
    mudar: (p) => { for (const f of p.faixas) if (f.tipo === "video" && !f.travada) for (const i of [...f.itens]) { if (!visual(i)) continue; if (Math.abs(i.ini - ponto) < .08 && ehCorte(f, i)) i.transicao = { tipo, dur }; else if (ponto > i.ini + .2 && ponto < i.ini + i.dur - .2) { const [a, b] = partir(i, ponto); b.transicao = { tipo, dur }; f.itens.splice(f.itens.indexOf(i), 1, a, b); } } } };
}
function cartaoTr(tipo) {
  const c = alvoTr(), b = el("button", { class: "st-tr-card", type: "button", "aria-pressed": String(c?.itens[0]?.transicao?.tipo === tipo), dados: { tr: tipo }, title: "Clique para ver a prévia ou arraste até a timeline para aplicar" }, el("span", { class: "st-tr-am" }, el("i", { class: "a" }), el("i", { class: "b" })), el("small", {}, nomeTr(tipo)));
  let ini = null, andou = false;
  b.addEventListener("pointerdown", (ev) => { if (ev.pointerType === "touch") return; ini = [ev.clientX, ev.clientY]; andou = false; b.setPointerCapture(ev.pointerId); });
  b.addEventListener("pointermove", (ev) => { if (!ini) return; if (!andou && Math.hypot(ev.clientX - ini[0], ev.clientY - ini[1]) < 6) return; andou = true; const r = rolagem.getBoundingClientRect(), dentro = ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom; if (!dentro) { mostrarGuia(null); mostrarDica(ev, `Solte na timeline: ${nomeTr(tipo)}`); return; } const t = (ev.clientX - faixasEl.getBoundingClientRect().left) / S.px, c1 = alvoTr(t, 14 / S.px); mostrarGuia(c1 ? c1.t : t); mostrarDica(ev, c1 ? `Aplicar neste corte: ${tempoTxt(c1.t)}` : `Cortar aqui e aplicar: ${tempoTxt(t)}`); });
  const fim = (ev) => { if (!ini) return; ini = null; mostrarGuia(null); mostrarDica(null, ""); if (!andou) return; const r = rolagem.getBoundingClientRect(); if (ev.type === "pointerup" && ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom) usarTransicao(tipo, (ev.clientX - faixasEl.getBoundingClientRect().left) / S.px, 14 / S.px); };
  b.addEventListener("pointerup", fim); b.addEventListener("pointercancel", fim);
  b.addEventListener("click", () => { if (andou) { andou = false; return; } const s = specTransicao(tipo); if (s) verPrevia(s, b); });
  return b;
}
function pTransicoes() {
  const cs = listaCortes(), c = alvoTr(), n = c ? cs.findIndex((x) => x.t === c.t) : -1, atual = c?.itens[0]?.transicao?.tipo;
  const ir = (d) => { const lista = d > 0 ? cs.filter((x) => x.t > S.t + .05) : cs.filter((x) => x.t < S.t - .05).reverse(); if (lista[0]) { pausar(); irPara(lista[0].t); montarPainel(); } };
  const alvo = el("div", { class: "st-tr-alvo", id: "st-tr-alvo" }, el("div", {}, el("strong", {}, c ? `Corte em ${tempoTxt(c.t)}` : `Novo corte em ${tempoTxt(S.t)}`), el("span", {}, c ? `${n + 1} de ${cs.length}, ${atual && atual !== "corte" ? nomeTr(atual) : "sem transição"}` : "O corte é feito ao aplicar a transição")), btn("‹", () => ir(-1), "botao"), btn("›", () => ir(1), "botao"));
  const dur = campo("Duração", { get: () => S.durTr ?? .5, set: (v) => { S.durTr = v; if (c) c.itens.forEach((i) => { if (i.transicao) i.transicao.dur = v; }); }, min: .1, max: 2, step: .05 });
  return [el("h2", {}, "Transições"), alvo, el("p", { class: "dica" }, "Clique para ver a prévia. O vídeo só muda quando você aplicar."), ...GRUPOS_TR.map(([nome, l]) => sec(nome, el("div", { class: "st-tr-grade" }, ...l.map(cartaoTr)))),
    sec("Ajuste", dur, btn("Usar a mesma em todos os cortes", () => { const t = atual && atual !== "corte" ? atual : null; if (!t) { avisar("Aplique uma transição neste corte primeiro"); return; } antes(); const d = S.durTr ?? .5; cs.forEach((x) => x.itens.forEach((i) => { i.transicao = { tipo: t, dur: d }; })); mudou(true); avisar(`${nomeTr(t)} aplicada em ${cs.length} cortes`); }), atual && atual !== "corte" ? btn("Tirar a transição deste corte", () => { antes(); c.itens.forEach((i) => { delete i.transicao; }); mudou(true); }) : null)];
}
/* ---------- Músicas de fundo compostas pelo Clipador, livres de direitos ---------- */
let tocandoMusica = null;
function secMusicas() {
  const lista = el("ul", { class: "st-sons st-musicas" }), packs = el("div", { class: "st-packs", role: "group", "aria-label": "Pack de música" }), repetir = el("input", { type: "checkbox", checked: "" });
  const usar = (s, d) => {
    const m = { id: `som:${s.id}`, tipo: "audio", raiz: "som", rel: s.id, nome: s.nome, dur: d }; S.p.midias[m.id] = m; antes();
    const ini = arred(S.t), fim = repetir.checked ? Math.max(duracao(), ini + 1) : ini + d; let t = ini; const f = faixaLivre("audio", ini, fim - ini), ids = [];
    while (t < fim - .2) { const dur = arred(Math.min(d, fim - t)), i = { id: nid(), tipo: "audio", categoria: "musica", nome: s.nome, midia: m.id, ini: arred(t), dur, entrada: 0, volume: 30 }; f.itens.push(i); ids.push(i.id); t += dur; }
    const ult = f.itens.find((i) => i.id === ids[ids.length - 1]), pri = f.itens.find((i) => i.id === ids[0]); if (ult) ult.fade_out = Math.min(1.5, ult.dur / 2); if (pri) pri.fade_in = .4; if (/^(Áudio|Audio) \d+$/.test(f.nome)) f.nome = "Música";
    S.sel = new Set(ids.slice(0, 1)); mudou(true); montarCabecas(); avisar(`Música ${s.nome} colocada no fundo`);
  };
  const ouvir = (s, b) => { const mesmo = tocandoMusica?.id === s.id; tocandoMusica?.a.pause(); $$(".st-musicas [data-tocando]").forEach((x) => { x.removeAttribute("data-tocando"); x.textContent = "Ouvir"; }); tocandoMusica = null; if (mesmo) return; const a = new Audio(`/sons/${s.id}.wav`); b.textContent = "Carregando"; a.addEventListener("playing", () => { b.textContent = "Parar"; b.dataset.tocando = "1"; }, { once: true }); a.addEventListener("ended", () => { b.textContent = "Ouvir"; b.removeAttribute("data-tocando"); }); a.play().catch(() => { b.textContent = "Ouvir"; }); tocandoMusica = { id: s.id, a }; };
  let atual = "";
  const mostrar = async () => {
    const r = await api("GET", `/api/sons?${new URLSearchParams({ q: "musica" })}`), todas = r.sons.filter((s) => s.categoria.startsWith("Música: "));
    const nomes = [...new Set(todas.map((s) => s.categoria.slice(8)))];
    packs.replaceChildren(...["", ...nomes].map((n) => el("button", { type: "button", "aria-pressed": String(n === atual), onclick: () => { atual = n; mostrar(); } }, n || "Todas")));
    lista.replaceChildren(...todas.filter((s) => !atual || s.categoria.slice(8) === atual).map((s) => cartaoSom(s, true, async (x) => { try { usar(x, await durSom(x.id)); } catch { avisar("Não foi possível preparar a música."); } })));
  };
  mostrar().catch(() => lista.replaceChildren(el("li", {}, "Não foi possível carregar as músicas.")));
  return sec("Músicas de fundo", el("p", { class: "dica" }, "Compostas pelo próprio Clipador: sem direitos autorais, pode postar e monetizar."), packs, el("label", { class: "marcar" }, repetir, el("span", {}, "Repetir até o fim do vídeo")), lista);
}
/* ---------- Sons como no CapCut: ouvir, adicionar com + ou arrastar para a timeline ---------- */
let somTocando = null, somArrastado = null;
function ouvirSom(id, b) {
  const mesmo = somTocando?.id === id; somTocando?.a.pause(); $$("#st-painel [data-tocando]").forEach((x) => { x.removeAttribute("data-tocando"); x.setAttribute("aria-label", "Ouvir"); }); somTocando = null; if (mesmo) return;
  const a = new Audio(`/sons/${id}.wav`); b.dataset.carregando = "1"; a.addEventListener("playing", () => { delete b.dataset.carregando; b.dataset.tocando = "1"; b.setAttribute("aria-label", "Parar"); }, { once: true });
  a.addEventListener("ended", () => { b.removeAttribute("data-tocando"); somTocando = null; }); a.play().catch((e) => { delete b.dataset.carregando; console.warn("som", e.name, e.message); }); somTocando = { id, a };
}
const durSom = (id) => new Promise((ok, falha) => { const a = new Audio(`/sons/${id}.wav`); a.preload = "metadata"; a.addEventListener("loadedmetadata", () => ok(a.duration), { once: true }); a.addEventListener("error", falha, { once: true }); });
async function porSom(s, musica, ini, faixa) {
  let d; try { d = await durSom(s.id); } catch { avisar("Não foi possível preparar o som."); return; }
  const m = { id: `som:${s.id}`, tipo: "audio", raiz: "som", rel: s.id, nome: s.nome, dur: d }; S.p.midias[m.id] = m; antes();
  const livre = (f, a, b) => f && f.tipo === "audio" && !f.travada && !f.itens.some((x) => x.ini < b && x.ini + x.dur > a);
  const f = livre(faixa, ini, ini + d) ? faixa : faixaLivre("audio", ini, d), item = { id: nid(), tipo: "audio", categoria: musica ? "musica" : "efeito", nome: s.nome, midia: m.id, ini: arred(ini), dur: arred(d), entrada: 0, volume: musica ? 30 : 70, ...(musica ? { fade_in: .4, fade_out: Math.min(1.5, d / 2) } : {}) };
  f.itens.push(item); S.sel = new Set([item.id]); mudou(true); montarCabecas(); avisar(`${s.nome} na timeline em ${tempoTxt(ini)}`);
}
function cartaoSom(s, musica, extra) {
  const tocar = el("button", { class: "st-som-tocar", type: "button", "aria-label": "Ouvir", title: "Ouvir", onclick: (ev) => { ev.stopPropagation(); ouvirSom(s.id, tocar); } });
  const mais = el("button", { class: "st-som-mais", type: "button", "aria-label": `Adicionar ${s.nome} na agulha`, title: "Adicionar na agulha", onclick: (ev) => { ev.stopPropagation(); extra ? extra(s) : porSom(s, musica, S.t); } }, "+");
  const n = el("li", { class: "st-som", draggable: "true", title: "Arraste para a timeline", dados: { cat: s.categoria } }, tocar, el("div", {}, el("strong", {}, s.nome), el("span", {}, musica ? s.categoria.slice(8) : s.categoria)), mais);
  n.addEventListener("dragstart", (ev) => { somArrastado = { s, musica }; ev.dataTransfer.setData("text/plain", s.nome); ev.dataTransfer.effectAllowed = "copy"; n.dataset.arrastando = "1"; });
  n.addEventListener("dragend", () => { delete n.dataset.arrastando; somArrastado = null; fimArraste(); });
  return n;
}
{ // a timeline recebe os sons arrastados
  const linha = el("div", { class: "st-som-alvo", hidden: "" }); document.body.append(linha);
  const ponto = (ev) => { const r = faixasEl.getBoundingClientRect(), t = lim((ev.clientX - r.left) / S.px, 0, duracao() + 30), cab = [...$$("#st-cabecas .st-cab")].find((c) => { const b = c.getBoundingClientRect(); return ev.clientY >= b.top && ev.clientY < b.bottom; }); return { t: arred(t), faixa: cab ? S.p.faixas[+cab.dataset.ci] : null }; };
  rolagem.addEventListener("dragover", (ev) => { if (!somArrastado) return; ev.preventDefault(); ev.dataTransfer.dropEffect = "copy"; const { t } = ponto(ev), r = rolagem.getBoundingClientRect(), x = faixasEl.getBoundingClientRect().left + t * S.px;
    Object.assign(linha.style, { left: `${x}px`, top: `${r.top}px`, height: `${r.height}px` }); linha.dataset.t = tempoTxt(t); linha.hidden = false; });
  rolagem.addEventListener("dragleave", (ev) => { if (!rolagem.contains(ev.relatedTarget)) linha.hidden = true; });
  rolagem.addEventListener("drop", (ev) => { if (!somArrastado) return; ev.preventDefault(); linha.hidden = true; const { t, faixa } = ponto(ev), { s, musica } = somArrastado; somArrastado = null; porSom(s, musica, t, faixa); });
  window.fimArraste = () => { linha.hidden = true; };
}
function fimArraste() { window.fimArraste?.(); }
function pSons() {
  const aba = S.abaSons || "efeitos", abas = el("div", { class: "st-sons-abas", role: "tablist" }, ...[["efeitos", "Efeitos sonoros"], ["musicas", "Músicas"]].map(([v, t]) => el("button", { type: "button", role: "tab", "aria-selected": String(v === aba), onclick: () => { S.abaSons = v; $("#st-painel").dataset.p = ""; montarPainel(); } }, t)));
  const dica = el("p", { class: "dica" }, "Clique em ▶ para ouvir. Use + ou arraste para a timeline.");
  if (aba === "musicas") return [el("h2", {}, "Sons"), abas, dica, secMusicas()];
  const lista = el("ul", { class: "st-sons" }), busca = el("input", { type: "search", placeholder: "Buscar: tiro, boing, explosão…", "aria-label": "Buscar som" }), chips = el("div", { class: "st-packs", role: "group", "aria-label": "Categoria" });
  let cat = S.catSom || "";
  const achar_ = async () => { const r = await api("GET", `/api/sons?${new URLSearchParams({ q: busca.value, categoria: cat })}`), cats = r.categorias.filter((c) => !c.startsWith("Música: "));
    chips.replaceChildren(...["", ...cats].map((c) => el("button", { type: "button", "aria-pressed": String(c === cat), onclick: () => { cat = S.catSom = c; achar_(); } }, c || "Todos")));
    const l = r.sons.filter((x) => !x.categoria.startsWith("Música: ")).slice(0, 120); lista.replaceChildren(...(l.length ? l.map((x) => cartaoSom(x, false)) : [el("li", { class: "dica" }, "Nenhum som encontrado.")])); };
  let tm; busca.addEventListener("input", () => { clearTimeout(tm); tm = setTimeout(achar_, 200); }); achar_();
  const inp = el("input", { type: "file", accept: "audio/*", hidden: "" }); inp.addEventListener("change", async () => { const a = inp.files[0]; if (!a) return; const r = await fetch(`/api/sons?nome=${encodeURIComponent(a.name)}`, { method: "POST", body: a }), d = await r.json(); r.ok ? (cat = S.catSom = "Meus sons", achar_()) : avisar(d.erro); });
  const suger = btn("Sugerir sons para este vídeo", async () => { try { const { sons } = await api("POST", `/api/estudio/${S.tipo}/${S.id}/sugerir-sons`, { projeto: S.p }), nov = sons.filter((s) => !itens().some(([, i]) => i.tipo === "audio" && Math.abs(i.ini - s.t) < 1)); if (!nov.length) { avisar("Os sons sugeridos já estão no vídeo"); return; } antes(); for (const s of nov) { const a = new Audio(`/sons/${s.som}.wav`); await new Promise((r) => a.addEventListener("loadedmetadata", r, { once: true })); const mid = `som:${s.som}`; S.p.midias[mid] ||= { id: mid, tipo: "audio", raiz: "som", rel: s.som, nome: s.som.replace(/_/g, " "), dur: a.duration }; faixaLivre("audio", s.t, a.duration).itens.push({ id: nid(), tipo: "audio", categoria: "efeito", nome: S.p.midias[mid].nome, midia: mid, ini: s.t, dur: arred(a.duration), entrada: 0, volume: Math.round(s.volume * 100) }); } mudou(); montarCabecas(); avisar(`${nov.length} sons adicionados`); } catch (e) { avisar(e.message); } }, "botao destaque");
  return [el("h2", {}, "Sons"), abas, el("div", { class: "st-botoes" }, suger, btn("Enviar som", () => inp.click())), inp, busca, chips, dica, lista];
}
const faixaCena = (id) => { const l = itens().filter(([, i]) => i.cena === id).map(([, i]) => i); return l.length ? [Math.min(...l.map((i) => i.ini)), Math.max(...l.map((i) => i.ini + i.dur))] : null; };
function moverCena(n, d) {
  const lista = S.p.cenas.filter((c) => faixaCena(c.id)).sort((a, b) => faixaCena(a.id)[0] - faixaCena(b.id)[0]), m = n + d; if (m < 0 || m >= lista.length) return; antes();
  const [p, s] = d > 0 ? [lista[n], lista[m]] : [lista[m], lista[n]], [a0, a1] = faixaCena(p.id), [b0, b1] = faixaCena(s.id);
  itens().forEach(([, i]) => { if (i.cena === p.id) i.ini = arred(i.ini + (b1 - a1)); else if (i.cena === s.id) i.ini = arred(i.ini - (b0 - a0)); }); mudou(true);
}
function pCenas() {
  const lista = S.p.cenas.filter((c) => faixaCena(c.id)).sort((a, b) => faixaCena(a.id)[0] - faixaCena(b.id)[0]);
  return [el("h2", {}, "Cenas"), el("p", { class: "dica" }, "Cada cena guarda seus próprios elementos. Mude uma sem afetar as outras."), el("ul", { class: "st-lista" }, ...lista.map((c, n) => { const [a, b] = faixaCena(c.id);
    const refazerB = btn("IA", () => trabalho("cena", { projeto: S.p, cena: c.id }, refazerB, () => avisar("Cena refeita pela IA")));
    refazerB.title = "Refazer zooms e legendas só desta cena";
    return el("li", {}, el("div", { onclick: () => { irPara(a); S.sel = new Set(itens().filter(([, i]) => i.cena === c.id).map(([, i]) => i.id)); selecaoMudou(); }, style: "cursor:pointer" }, el("strong", {}, c.nome), el("span", {}, `${tempoTxt(a)}, ${tempoTxt(b - a)}`)), btn("▲", () => moverCena(n, -1)), btn("▼", () => moverCena(n, 1)), refazerB, btn("×", () => cortarTempo([[a, b]]).catch((e) => avisar(e.message)))); }))];
}
function pIa() {
  const lista = el("ul", { class: "st-lista" }), marcados = new Set(S.sug.map((s) => s.id));
  const pintarL = () => lista.replaceChildren(...S.sug.map((s) => { const c = el("input", { type: "checkbox", "aria-label": s.titulo }); c.checked = marcados.has(s.id); c.addEventListener("change", () => (c.checked ? marcados.add(s.id) : marcados.delete(s.id))); return el("li", { class: "st-sug" }, c, el("div", { onclick: () => irPara(s.t), style: "cursor:pointer" }, el("strong", {}, s.titulo)), el("p", {}, s.detalhe)); }));
  const analisar = btn("Analisar o vídeo", async () => { analisar.disabled = true; analisar.textContent = "Analisando…"; try { S.sug = (await api("POST", `/api/estudio/${S.tipo}/${S.id}/analisar`, { projeto: S.p })).sugestoes; marcados.clear(); S.sug.forEach((s) => marcados.add(s.id)); pintarL(); if (!S.sug.length) avisar("Nenhum problema encontrado"); } catch (e) { avisar(e.message); } analisar.disabled = false; analisar.textContent = "Analisar o vídeo"; }, "botao destaque");
  pintarL();
  return [el("h2", {}, "Assistente de IA"), el("p", { class: "dica" }, "Procura zooms errados, legendas sobre rostos, pausas, ritmo e efeitos fora da fala. Nada muda até você aplicar."), analisar, lista,
    btn("Aplicar as marcadas", async () => { const l = S.sug.filter((s) => marcados.has(s.id)); if (!l.length) return; try { const r = await api("POST", `/api/estudio/${S.tipo}/${S.id}/aplicar`, { projeto: S.p, sugestoes: l }); antes(); S.p = r.projeto; S.sug = S.sug.filter((s) => !marcados.has(s.id)); mudou(true); montarCabecas(); avisar("Correções aplicadas"); } catch (e) { avisar(e.message); } }),
    btn("Voltar à edição original da IA", (ev) => confirmar(ev.currentTarget, "Descartar minhas mudanças", async () => { const r = await api("POST", `/api/estudio/${S.tipo}/${S.id}/restaurar`, {}); antes(); S.p = r.projeto; S.sel.clear(); mudou(true); montarCabecas(); }), "botao perigo")];
}
function pGlobal() {
  const G = S.p.global, L = () => G.legenda, por = (k, v) => { L()[k] = v; itens().forEach(([, i]) => { if (i.tipo === "legenda" && i.estilo) delete i.estilo[k]; }); };
  const vol = (k, r) => campo(r, { get: () => G[k] ?? 100, set: (v) => { G[k] = v; }, max: 200 }), trans = el("select", { "aria-label": "Transição" }, ...TRANS.map(([a, b]) => el("option", { value: a }, b))), dur = el("input", { type: "number", value: ".4", step: ".05", min: ".1", "aria-label": "Duração da transição" }), nome = el("input", { type: "text", placeholder: "Nome do preset", "aria-label": "Nome do preset" }), lista = el("ul", { class: "st-lista" });
  const conteudo = () => ({ legenda: L(), volume_fala: G.volume_fala, volume_musica: G.volume_musica, volume_efeitos: G.volume_efeitos, zoom_forca: G.zoom_forca, filtro: G.filtro, transicao: G.transicao });
  const padTrans = (t) => { itens().forEach(([f, i]) => { if (f.tipo === "video" && ["video", "imagem"].includes(i.tipo) && i.ini > .05 && !i.mudo) i.transicao = t; }); };
  const pintarP = (l) => lista.replaceChildren(...l.map((p) => el("li", {}, el("div", {}, el("strong", {}, p.nome)), btn("Usar", () => { antes(); Object.assign(G, clonar(p.global)); itens().forEach(([, i]) => { if (i.tipo === "legenda") i.estilo = {}; }); if (p.global.transicao) padTrans(p.global.transicao); mudou(true); }), btn("×", async () => pintarP(await api("DELETE", `/api/estudio/presets/${p.id}`))))));
  api("GET", "/api/estudio/presets").then(pintarP).catch(() => {});
  return [el("h2", {}, "Ajustes do vídeo inteiro"), sec("Todas as legendas", escolha("Fonte", opFontes(), L().fonte, (v) => por("fonte", v)), campo("Tamanho", { get: () => L().tamanho, set: (v) => por("tamanho", v), min: 12, max: 200 }), corCampo("Cor", L().cor, (v) => por("cor", v)), corCampo("Destaque", L().cor_destaque, (v) => por("cor_destaque", v)), escolha("Entrada", ANIM, L().entrada, (v) => por("entrada", v)), escolha("Saída", ANIM, L().saida, (v) => por("saida", v))),
    sec("Todos os textos", corCampo("Cor", "#FFFFFF", (v) => itens().forEach(([, i]) => { if (i.tipo === "texto") (i.estilo ||= {}).cor = v; })), escolha("Fonte", opFontes(), "Poppins-Bold", (v) => itens().forEach(([, i]) => { if (i.tipo === "texto") (i.estilo ||= {}).fonte = v; }))),
    sec("Volume", vol("volume_fala", "Fala"), vol("volume_musica", "Música"), vol("volume_efeitos", "Efeitos")), sec("Zoom e movimento", campo("Força", { get: () => G.zoom_forca ?? 100, set: (v) => { G.zoom_forca = v; }, max: 200 })),
    sec("Cor", escolha("Filtro", S.filtros.map((f) => [f.id, f.nome]), G.filtro?.nome || "nenhum", (v) => { G.filtro = v === "nenhum" ? null : { nome: v, forca: G.filtro?.forca ?? 100 }; })),
    sec("Transições", trans, linha("Duração", dur), btn("Usar em todas as cenas", () => { antes(); G.transicao = { tipo: trans.value, dur: +dur.value || .4 }; padTrans(G.transicao); mudou(); avisar("Transições padronizadas"); })),
    sec("Presets", nome, btn("Salvar preset", async () => { try { pintarP(await api("POST", "/api/estudio/presets", { nome: nome.value, global: conteudo() })); nome.value = ""; } catch (e) { avisar(e.message); } }), lista)];
}

/* ---------- Capas ---------- */
function pintarCapa() {
  if (!S.capa) return; g.setTransform(S.escTela, 0, 0, S.escTela, 0, 0); g.filter = "none"; g.globalAlpha = 1; g.fillStyle = S.capa.fundo || "#000"; g.fillRect(0, 0, S.capa.largura, S.capa.altura); S.caixas.clear();
  for (const c of S.capa.camadas) { if (c.oculta) continue; const e = c.escala ?? 1, bw = (c.w ?? 100) * e, bh = (c.h ?? 100) * e, a = c.ajustes || {};
    if (c.tipo === "texto") { S.caixas.set(c.id, desenharTexto(c.texto || "", { ...PAD_EST, ...(c.estilo || {}) }, c.x, c.y, e, c.rot || 0, (c.opac ?? 100) / 100, null)); continue; }
    S.caixas.set(c.id, { x: c.x, y: c.y, w: bw, h: bh, rot: c.rot || 0 }); g.save(); g.translate(c.x, c.y); g.rotate((c.rot || 0) * Math.PI / 180); g.globalAlpha = (c.opac ?? 100) / 100;
    if (c.tipo === "imagem") { if (c.borda) { g.fillStyle = c.borda_cor || "#fff"; g.fillRect(-bw / 2 - c.borda, -bh / 2 - c.borda, bw + c.borda * 2, bh + c.borda * 2); } const im = elImagem(c.midia.rel, c.midia), [cl, ct, cr, cb] = [c.cl || 0, c.ct || 0, c.cr || 0, c.cb || 0]; g.filter = [a.brilho ? `brightness(${1 + a.brilho / 100})` : "", a.contraste ? `contrast(${1 + a.contraste / 100})` : "", a.saturacao ? `saturate(${1 + a.saturacao / 100})` : ""].join(" ").trim() || "none"; if (im.naturalWidth) g.drawImage(im, cl * im.naturalWidth, ct * im.naturalHeight, (1 - cl - cr) * im.naturalWidth, (1 - ct - cb) * im.naturalHeight, -bw / 2, -bh / 2, bw, bh); }
    else { g.fillStyle = c.cor || "#FFC933"; g.globalAlpha *= (c.cor_opac ?? 100) / 100; g.beginPath(); if (c.forma === "circulo") g.ellipse(0, 0, bw / 2, bh / 2, 0, 0, 7); else g.roundRect(-bw / 2, -bh / 2, bw, bh, c.raio || 0); g.fill(); }
    g.restore(); }
  desenharAlca();
}
function novaCamada(c) { antes(); c.id = nid("k"); S.capa.camadas.push(c); S.sel = new Set([c.id]); mudou(true); }
function apagarCamada() { if (!S.sel.size) return; antes(); S.capa.camadas = S.capa.camadas.filter((c) => !S.sel.has(c.id)); S.sel.clear(); mudou(true); }
function moverCamada(c, d) { const l = S.capa.camadas, n = l.indexOf(c), m = n + d; if (m < 0 || m >= l.length) return; antes(); [l[n], l[m]] = [l[m], l[n]]; mudou(true); }
function camadaImagem(m) { const e = Math.min(1, 640 / (m.lar || 640), 480 / (m.alt || 480)); novaCamada({ tipo: "imagem", nome: m.nome, midia: { raiz: m.raiz, rel: m.rel }, x: 640, y: 360, w: Math.round((m.lar || 640) * e), h: Math.round((m.alt || 480) * e), rot: 0, opac: 100, escala: 1 }); }
function pCamadas() {
  const inp = envioArquivos("image/*", camadaImagem), W = S.capa.largura, H = S.capa.altura;
  return [el("h2", {}, "Camadas"), el("div", { class: "st-botoes" }, btn("Texto", () => novaCamada({ tipo: "texto", nome: "Texto", texto: "SEU TEXTO", x: W / 2, y: H / 2, rot: 0, opac: 100, escala: 1, estilo: { fonte: "Anton", tamanho: 96, cor: "#FFC933", contorno: 8, largura: 1100 } })), btn("Imagem", () => inp.click()), inp, btn("Forma", () => novaCamada({ tipo: "forma", nome: "Forma", forma: "retangulo", cor: "#FFC933", x: W / 2, y: H / 2, w: 420, h: 160, rot: 0, opac: 100, escala: 1 }))),
    corCampo("Fundo", S.capa.fundo, (v) => { S.capa.fundo = v; }), el("ul", { class: "st-lista" }, ...[...S.capa.camadas].reverse().map((c) => el("li", S.sel.has(c.id) ? { dados: { sel: "1" } } : {}, el("div", { style: "cursor:pointer", onclick: () => { S.sel = new Set([c.id]); selecaoMudou(); pedirPintura(); } }, el("strong", {}, c.tipo === "texto" ? c.texto.slice(0, 26) : c.nome), el("span", {}, { texto: "Texto", imagem: "Imagem", forma: "Forma" }[c.tipo])), btn("▲", () => moverCamada(c, 1)), btn("▼", () => moverCamada(c, -1)), btn(c.oculta ? "Ver" : "Ocultar", () => { antes(); c.oculta = !c.oculta; mudou(true); }))))];
}
function pModelos() {
  const nome = el("input", { type: "text", placeholder: "Nome do modelo", "aria-label": "Nome do modelo" }), lista = el("ul", { class: "st-lista" });
  const pintarM = (l) => lista.replaceChildren(...l.map((m) => el("li", {}, el("div", {}, el("strong", {}, m.nome)), btn("Usar", async () => { const r = await api("POST", "/api/estudio/modelos-capa/aplicar", { modelo: m.capa, capa: S.capa }); antes(); S.capa = r; S.sel.clear(); mudou(true); }), btn("×", async () => pintarM(await api("DELETE", `/api/estudio/modelos-capa/${m.id}`))))));
  api("GET", "/api/estudio/modelos-capa").then(pintarM).catch(() => {});
  return [el("h2", {}, "Modelos de capa"), el("p", { class: "dica" }, "Guarde este visual e use em outros vídeos. O fundo, o rosto e os textos de cada vídeo são mantidos."), nome, btn("Salvar como modelo", async () => { try { pintarM(await api("POST", "/api/estudio/modelos-capa", { nome: nome.value, capa: S.capa })); nome.value = ""; avisar("Modelo salvo"); } catch (e) { avisar(e.message); } }, "botao destaque"), lista];
}
function inspetorCapa(box) {
  const c = S.capa.camadas.find((x) => S.sel.has(x.id)); if (!c) { box.replaceChildren(el("h2", {}, "Capa"), el("p", { class: "dica" }, "Clique em um elemento da capa para mover, redimensionar e mudar o estilo.")); return; }
  const n = (k, r, min, max, step = 1, pad = 0) => campo(r, { get: () => c[k] ?? pad, set: (v) => { c[k] = v; }, min, max, step }), W = S.capa.largura, H = S.capa.altura, aj = (k, r) => campo(r, { get: () => c.ajustes?.[k] ?? 0, set: (v) => { (c.ajustes ||= {})[k] = v; }, min: -100, max: 100 });
  const b = [el("h2", {}, c.nome || "Camada"), sec("Posição", n("x", "X", -200, W + 200), n("y", "Y", -200, H + 200), n("escala", "Escala", .1, 5, .01, 1), n("rot", "Rotação", -180, 180), n("opac", "Opacidade", 0, 100, 1, 100), c.tipo !== "texto" ? n("w", "Largura", 10, W * 2) : null, c.tipo !== "texto" ? n("h", "Altura", 10, H * 2) : null),
    el("div", { class: "st-botoes" }, btn("Duplicar", () => { const d = clonar(c); d.x += 24; d.y += 24; novaCamada(d); }), btn("Apagar", apagarCamada, "botao perigo"))];
  if (c.tipo === "texto") { const t = el("textarea", { "aria-label": "Texto" }); t.value = c.texto; t.addEventListener("input", () => { c.texto = t.value; mudou(); pintarCapa(); }); t.addEventListener("focus", antes, { once: true }); b.push(sec("Texto", t), ...controlesEstilo(() => ({ ...PAD_EST, ...(c.estilo || {}) }), (k, v) => { (c.estilo ||= {})[k] = v; })); }
  else if (c.tipo === "imagem") { const inp = envioArquivos("image/*", (m) => { antes(); c.midia = { raiz: m.raiz, rel: m.rel }; mudou(true); }); b.push(sec("Imagem", btn("Trocar imagem", () => inp.click()), inp, n("cl", "Cortar esq.", 0, .9, .01), n("cr", "Cortar dir.", 0, .9, .01), n("ct", "Cortar topo", 0, .9, .01), n("cb", "Cortar base", 0, .9, .01)), sec("Efeitos", aj("brilho", "Brilho"), aj("contraste", "Contraste"), aj("saturacao", "Saturação"), n("borda", "Borda", 0, 40), corCampo("Cor borda", c.borda_cor, (v) => { c.borda_cor = v; }), marca("Sombra", c.sombra, (v) => { c.sombra = v; }))); }
  else b.push(sec("Forma", escolha("Tipo", [["retangulo", "Retângulo"], ["circulo", "Círculo"]], c.forma, (v) => { c.forma = v; }), corCampo("Cor", c.cor, (v) => { c.cor = v; }), n("cor_opac", "Opacidade", 0, 100, 1, 100), n("raio", "Arredondar", 0, 200), n("borda", "Borda", 0, 40), corCampo("Cor borda", c.borda_cor, (v) => { c.borda_cor = v; })));
  box.replaceChildren(...b);
}
async function trocarModo(modo) {
  if (modo === S.modo) return; pausar();
  if (modo === "capa" && !S.capa) { try { S.capa = await api("GET", `/api/estudio/${S.tipo}/${S.id}/capa`); } catch (e) { avisar(e.message); return; } }
  S.modo = modo; S.sel.clear(); $("#st-mesa").dataset.modo = modo; $("#st-m-video").setAttribute("aria-pressed", String(modo === "video")); $("#st-m-capa").setAttribute("aria-pressed", String(modo === "capa")); $("#st-exportar").textContent = modo === "capa" ? "Exportar capa" : "Exportar";
  exato.hidden = true; botoes(); montarRail(); montarPainel(); montarInspetor(); ajustarTela(); pedirPintura(); pedirExato(); if (modo === "video") desenharLinha();
}
$("#st-m-video").addEventListener("click", () => trocarModo("video")); $("#st-m-capa").addEventListener("click", () => trocarModo("capa"));

/* ---------- Exportar ---------- */
$("#st-exportar").addEventListener("click", () => {
  const ops = cap() ? [["1280", "1280 × 720", "Tamanho do YouTube"], ["1920", "1920 × 1080", "Alta definição"], ["3840", "3840 × 2160", "4K"]] : [["720", "720p", "Mais rápido"], ["1080", "1080p", "Recomendado"], ["1440", "1440p", "Quadros maiores"], ["2160", "4K", "Só vale a pena se o vídeo original for 4K"]];
  $("#st-dx-t").textContent = cap() ? "Exportar capa" : "Exportar vídeo"; $("#st-res").replaceChildren(...ops.map(([v, a, b], n) => el("label", {}, Object.assign(el("input", { type: "radio", name: "st-res", value: v }), { checked: n === (cap() ? 0 : 1) }), el("strong", {}, a), el("span", { class: "dica" }, b))));
  const orig = Object.values(S.p.midias).filter((m) => m.tipo === "video" && m.alt).sort((a, b) => b.alt - a.alt)[0], baixa = orig && Math.min(orig.lar, orig.alt) < 1080;
  $("#st-dx-nota").textContent = cap() ? "A capa também passa a ser usada neste vídeo." : `${orig ? `A live foi gravada em ${orig.lar} × ${orig.alt}. ` : ""}${baixa ? "A transmissão não chegou em Full HD, então o vídeo sai em 1080p, mas sem ganhar detalhes novos. " : ""}O arquivo final substitui o vídeo atual na agenda.`; $("#st-dlg-exportar").showModal();
});
$("#st-form-exportar").addEventListener("submit", async (ev) => {
  const v = +$("#st-res input:checked").value;
  try {
    if (cap()) { const r = await api("POST", `/api/estudio/${S.tipo}/${S.id}/capa/exportar`, { capa: S.capa, largura: v }); avisar(`Capa exportada em ${r.largura} × ${r.altura}`); const a = el("a", { href: r.url, download: "capa.jpg" }); a.click(); return; }
    await salvar(); await api("POST", `/api/estudio/${S.tipo}/${S.id}/exportar`, { projeto: S.p, altura: v }); acompanharExport();
  } catch (e) { avisar(e.message); }
});
let tempoExp;
function acompanharExport() {
  clearTimeout(tempoExp); const box = $("#st-progresso"), acao = $("#st-prog-acao"); box.hidden = false; acao.textContent = "Cancelar"; $("#st-exportar").disabled = true;
  acao.onclick = () => api("POST", `/api/estudio/${S.tipo}/${S.id}/exportar/cancelar`, {}).catch(() => {});
  const ver = async () => { try { const r = await api("GET", `/api/estudio/${S.tipo}/${S.id}/exportar`); $("#st-prog").value = r.progresso || 0; $("#st-prog-txt").textContent = `${r.etapa || "Exportando"} (${r.progresso || 0}%)`;
    if (["fila", "gerando"].includes(r.estado)) { tempoExp = setTimeout(ver, 1000); return; } $("#st-exportar").disabled = false;
    if (r.estado === "pronto") { avisar("Vídeo exportado"); acao.textContent = "Ver resultado"; acao.onclick = () => { box.hidden = true; S.tipo === "corte" ? abrirEditor(S.id) : abrirLongo(S.id); }; }
    else { $("#st-prog-txt").textContent = r.erro || r.etapa; acao.textContent = "Fechar"; acao.onclick = () => (box.hidden = true); } } catch { tempoExp = setTimeout(ver, 2000); } };
  ver();
}

/* ---------- Escolher e abrir ---------- */
let pagEscolha = 1, tipoEscolha = "corte", sinalEscolha = "";
function renderEscolha() {
  const termo = $("#tl-busca").value.trim().toLocaleLowerCase("pt-BR"), base = tipoEscolha === "corte" ? estado.cortes.filter((c) => c.status === "pronto").map((c) => ({ id: c.id, nome: c.gancho || "Corte", canal: c.canal, dur: c.duracao, capa: `/cortes/${c.id}/capa.jpg?v=${c.versao || 0}` })) : estado.longos.filter((v) => v.status === "pronto").map((v) => ({ id: v.id, nome: v.titulo, canal: v.canal, dur: v.duracao, capa: `/longos/${v.id}/capa.jpg?v=${v.versao || 0}` }));
  const lista = termo ? base.filter((v) => `${v.nome} ${v.canal}`.toLocaleLowerCase("pt-BR").includes(termo)) : base, paginas = Math.max(1, Math.ceil(lista.length / 24)); pagEscolha = lim(pagEscolha, 1, paginas);
  const parte = lista.slice((pagEscolha - 1) * 24, pagEscolha * 24), sinal = JSON.stringify([tipoEscolha, pagEscolha, lista.length, parte.map((v) => [v.id, v.nome, v.capa])]); if (sinal === sinalEscolha) return; sinalEscolha = sinal;
  $("#tl-lista").dataset.tipo = tipoEscolha; $("#tl-lista").replaceChildren(...parte.map((v) => el("button", { class: "tl-cartao", type: "button", onclick: () => abrirTimeline(tipoEscolha, v.id) }, el("img", { src: v.capa, alt: "", loading: "lazy" }), el("strong", {}, v.nome), el("span", {}, `${v.canal || "Live"}, ${relogio(v.dur || 0)}`))));
  const vazio = $("#tl-vazio"); vazio.hidden = lista.length > 0; vazio.textContent = termo ? "Nenhum vídeo com esse nome." : tipoEscolha === "corte" ? "Os Shorts prontos aparecem aqui." : "Os vídeos longos prontos aparecem aqui.";
  montarPaginas($("#tl-paginacao"), pagEscolha, paginas, (n) => { pagEscolha = n; renderEscolha(); scrollTo(0, 0); });
}
$$("#tl-tipos button").forEach((b) => b.addEventListener("click", () => { tipoEscolha = b.dataset.tipo; pagEscolha = 1; $$("#tl-tipos button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); renderEscolha(); }));
$("#tl-busca").addEventListener("input", () => { pagEscolha = 1; renderEscolha(); });
async function abrirTimeline(tipo, id) {
  abrirAba("editor"); $("#tl-escolha").hidden = true; $("#st-mesa").hidden = false; $("#st-nome").textContent = "Preparando o projeto…";
  try {
    if (!S.fontes.length) [S.fontes, S.filtros] = await Promise.all([api("GET", "/api/estudio/fontes"), api("GET", "/api/filtros")]);
    const r = await api("GET", `/api/estudio/${tipo}/${id}`);
    videos.forEach((v) => { v.pause(); v.removeAttribute("src"); v.load(); }); videos.clear(); imagens.clear(); buffers.clear();
    Object.assign(S, { aberto: true, tipo, id, p: r.projeto, capa: null, modo: "video", sel: new Set(), t: 0, tocando: false, sujo: false, sug: [], h: { video: { d: [], r: [] }, capa: { d: [], r: [] } }, painel: "midia" });
    const m = $("#st-mesa"); m.dataset.modo = "video"; $("#st-m-video").setAttribute("aria-pressed", "true"); $("#st-m-capa").setAttribute("aria-pressed", "false"); $("#st-exportar").textContent = "Exportar"; $("#st-exportar").disabled = false; $("#st-progresso").hidden = true;
    $("#st-nome").textContent = S.p.titulo; $("#st-salvo").textContent = "Projeto salvo";
    botoes(); montarRail(); montarPainel(); montarInspetor(); montarCabecas(); ajustarTela(); requestAnimationFrame(() => { ajustarZoom(); pedirExato(); });
    if (["fila", "gerando"].includes(r.exportacao?.estado)) acompanharExport();
  } catch (e) { avisar(e.message); $("#st-mesa").hidden = true; $("#tl-escolha").hidden = false; }
}
function fechar() { pausar(); S.aberto = false; videos.forEach((v) => { v.pause(); v.removeAttribute("src"); v.load(); }); videos.clear(); $("#st-mesa").hidden = true; $("#tl-escolha").hidden = false; sinalEscolha = ""; renderEscolha(); }
$("#st-voltar").addEventListener("click", async () => { await salvar(); fechar(); });
window.abrirTimeline = abrirTimeline; window.pausarEditor = pausar;
window.renderEditor = () => { if (!S.aberto && !$("#aba-editor").hidden) renderEscolha(); };
window.__es = { S, irPara, duracao, itens, achar, mudou, antes, salvar, dividir };
})();
