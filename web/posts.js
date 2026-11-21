"use strict";
/* Posts de frase: as frases fortes das lives viram posts com o rosto de quem falou. */
(() => {
const P = { pasta: "", formato: "feed", prints: 2, fonte: "dmsans", pb: false, assinatura: "", lista: { cortes: [], frases: [], fontes: [] }, buscando: false, parar: false, aberta: null };
try { Object.assign(P, JSON.parse(localStorage.getItem("posts-opcoes") || "{}"), { lista: { cortes: [], frases: [], fontes: [] }, buscando: false, parar: false, aberta: null }); } catch {}
const chave = (f) => `${f.corte}:${f.id}`;
const opcoes = () => ({ formato: P.formato, prints: P.prints, fonte: P.fonte, pb: P.pb, assinatura: P.assinatura });
function guardarOpcoes() { try { localStorage.setItem("posts-opcoes", JSON.stringify(opcoes())); } catch {} }

async function imagemPost(corpo, previa = true) {
  const r = await fetch(previa ? "/api/posts/previa" : "/api/posts/arte", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).erro || "Não foi possível desenhar o post.");
  return { blob: await r.blob(), nome: decodeURIComponent((r.headers.get("Content-Disposition") || "").split("''")[1] || "post.png") };
}
function baixarBlob(blob, nome) { const url = URL.createObjectURL(blob); el("a", { href: url, download: nome }).click(); setTimeout(() => URL.revokeObjectURL(url), 5000); }

/* ---------- Lista ---------- */
function pastas() {
  const sel = $("#ps-pasta"), lista = estado?.postagem?.pastas || [], atual = P.pasta;
  const chaveL = JSON.stringify(lista.map((p) => p.id));
  if (sel.dataset.chave !== chaveL) {
    sel.dataset.chave = chaveL;
    sel.replaceChildren(el("option", { value: "" }, "Todas as pastas"), ...lista.map((p) => el("option", { value: p.id }, `${p.canal}${p.titulo ? `: ${p.titulo}` : ""} (${p.cortes})`)));
  }
  sel.value = lista.some((p) => p.id === atual) ? atual : "";
}
async function carregar() {
  try { P.lista = await api("GET", `/api/posts?pasta=${encodeURIComponent(P.pasta)}`); } catch (e) { avisar(e.message); return; }
  const fs = $("#ps-fonte");
  if (!fs.options.length) { fs.replaceChildren(...P.lista.fontes.map((f) => el("option", { value: f.id }, f.nome))); }
  fs.value = P.fonte; desenharGrade();
}
const fila = [], vistos = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { vistos.unobserve(e.target); fila.push(e.target); puxar(); } }), { rootMargin: "300px" });
let ativos = 0;
async function puxar() { // no máximo três desenhos ao mesmo tempo
  while (ativos < 3 && fila.length) {
    const img = fila.shift(); ativos++;
    const f = P.lista.frases.find((x) => chave(x) === img.dataset.k);
    if (f) imagemPost({ corte: f.corte, frase: f.id, ...opcoes() }).then(({ blob }) => { img.src = URL.createObjectURL(blob); img.classList.add("carregada"); }).catch(() => img.replaceWith(el("span", { class: "ps-sem" }, "Sem prévia"))).finally(() => { ativos--; puxar(); });
    else { ativos--; }
  }
}
function desenharGrade() {
  const lista = P.lista.frases, grade = $("#ps-grade");
  $("#ps-baixar").disabled = !lista.some((f) => f.escolhida);
  $("#ps-baixar").textContent = `Baixar escolhidas${lista.filter((f) => f.escolhida).length ? ` (${lista.filter((f) => f.escolhida).length})` : ""}`;
  const semFrases = P.lista.cortes.filter((c) => !c.pronto).length;
  $("#ps-vazio").hidden = lista.length > 0;
  $("#ps-vazio").textContent = P.lista.cortes.length ? `Ainda não há frases aqui. Clique em Encontrar frases: ${semFrases} cortes para ler.` : "Os posts aparecem quando houver cortes prontos nesta pasta.";
  grade.replaceChildren(...lista.map((f) => {
    const img = el("img", { alt: f.texto, dados: { k: chave(f) }, class: `ps-img ${P.formato}` }), marca = el("input", { type: "checkbox", "aria-label": "Entra no pacote" });
    marca.checked = !!f.escolhida;
    marca.addEventListener("click", (ev) => ev.stopPropagation());
    marca.addEventListener("change", async () => { f.escolhida = marca.checked; desenharGrade(); try { await api("POST", "/api/posts/salvar", { corte: f.corte, frase: f.id, escolhida: marca.checked }); } catch (e) { avisar(e.message); } });
    vistos.observe(img);
    return el("article", { class: "ps-cartao", dados: { escolhida: f.escolhida ? "1" : "0" } },
      el("button", { class: "ps-abrir", type: "button", onclick: () => abrir(f) }, el("div", { class: `ps-quadro ${P.formato}` }, img), el("p", {}, f.texto)),
      el("label", { class: "marcar ps-marca" }, marca, el("span", {}, f.propria ? "Sua frase" : f.canal)));
  }));
}
async function buscar() {
  if (P.buscando) { P.parar = true; return; }
  const faltam = P.lista.cortes.filter((c) => !c.pronto);
  if (!faltam.length) { avisar("Todas as frases desta pasta já foram encontradas"); return; }
  P.buscando = true; P.parar = false; const b = $("#ps-buscar"), st = $("#ps-status"); b.textContent = "Parar"; st.hidden = false;
  let n = 0;
  for (const c of faltam) {
    if (P.parar) break;
    st.textContent = `Lendo o corte ${++n} de ${faltam.length}: ${c.gancho || c.id}`;
    try { await api("POST", "/api/posts/gerar", { corte: c.id, pasta: P.pasta }); } catch (e) { console.warn("posts", e.message); }
    if (n % 3 === 0 || n === faltam.length) await carregar();
  }
  P.buscando = false; b.textContent = "Encontrar frases"; st.hidden = true; await carregar();
  avisar(`${P.lista.frases.length} frases prontas para virar post`);
}

/* ---------- Uma frase ---------- */
const dlg = $("#ps-janela");
let tempoPrevia, seqPrevia = 0, tempoSalvar;
async function abrir(f) {
  try {
    const d = await api("GET", `/api/posts/${f.corte}/${f.id}?n=${P.prints}`);
    P.aberta = { f, partes: d.partes, prints: d.prints, opcoes: d.opcoes, parte: 0 };
  } catch (e) { avisar(e.message); return; }
  $("#ps-origem").textContent = f.propria ? "Frase escrita por você" : `${f.canal}${f.original ? "" : ""}`;
  $("#ps-original").textContent = f.original && f.original !== f.texto ? `Como foi falado: “${f.original}”` : "";
  $("#ps-legenda").value = f.legenda || f.texto; $("#ps-escolher").checked = !!f.escolhida;
  montarControles(); montarPartes(); montarPrints(); previa(); if (!dlg.open) dlg.showModal();
}
function montarControles() { // as mesmas opções da página, dentro da janela
  const grupo = (rot, itens, atual, fn) => el("div", { class: "filtros", role: "group", "aria-label": rot }, ...itens.map(([v, t]) => el("button", { type: "button", "aria-pressed": String(v === atual), onclick: () => fn(v) }, t)));
  const fonte = el("select", { "aria-label": "Fonte" }, ...P.lista.fontes.map((f) => el("option", { value: f.id }, f.nome))); fonte.value = P.fonte;
  fonte.addEventListener("change", () => { P.fonte = fonte.value; mudouOpcao(); });
  const pb = el("input", { type: "checkbox" }); pb.checked = P.pb; pb.addEventListener("change", () => { P.pb = pb.checked; mudouOpcao(); });
  $("#ps-controles").replaceChildren(grupo("Formato", [["feed", "Feed 4:5"], ["stories", "Stories 9:16"]], P.formato, (v) => { P.formato = v; mudouOpcao(); montarControles(); }),
    grupo("Prints", [["1", "1"], ["2", "2"], ["3", "3 prints"]], String(P.prints), (v) => { P.prints = +v; mudouOpcao(); }), el("label", { class: "ps-campo" }, "Fonte", fonte), el("label", { class: "marcar" }, pb, el("span", {}, "P&B")));
}
function montarPartes() {
  const a = P.aberta;
  $("#ps-partes").replaceChildren(...a.partes.map((t, k) => { const c = el("textarea", { rows: "2", "aria-label": `Texto do print ${k + 1}` }); c.value = t; c.addEventListener("input", () => { a.partes[k] = c.value; previa(); salvarDepois(); }); return c; }));
}
function montarPrints() {
  const a = P.aberta, url = (pid) => `/posts/${a.f.corte}/${pid}_mini.jpg`;
  $("#ps-escolhidos").replaceChildren(...a.prints.map((pid, k) => el("button", { type: "button", class: "ps-mini", "aria-pressed": String(k === a.parte), title: `Print ${k + 1}`, onclick: () => { a.parte = k; montarPrints(); } }, el("img", { src: url(pid), alt: `Print ${k + 1}` }), el("b", {}, String(k + 1)))));
  $("#ps-quadros").replaceChildren(...a.opcoes.map((pid) => el("button", { type: "button", class: "ps-mini", "aria-pressed": String(a.prints[a.parte] === pid), onclick: () => { a.prints[a.parte] = pid; montarPrints(); previa(); salvarDepois(); } }, el("img", { src: url(pid), alt: "Quadro do vídeo", loading: "lazy" }))));
}
function corpoAberto() { const a = P.aberta; return { corte: a.f.corte, frase: a.f.id, ...opcoes(), partes: a.partes, prints_ids: a.prints, nome: a.f.texto.slice(0, 40) }; }
function previa() {
  clearTimeout(tempoPrevia); $("#ps-carregando").hidden = false;
  tempoPrevia = setTimeout(async () => {
    const n = ++seqPrevia;
    try { const { blob } = await imagemPost(corpoAberto()); if (n !== seqPrevia) return; const img = $("#ps-imagem"); URL.revokeObjectURL(img.src); img.src = URL.createObjectURL(blob); img.className = P.formato; } catch (e) { avisar(e.message); }
    if (n === seqPrevia) $("#ps-carregando").hidden = true;
  }, 280);
}
function salvarDepois() {
  clearTimeout(tempoSalvar);
  tempoSalvar = setTimeout(() => { const a = P.aberta; if (!a) return; api("POST", "/api/posts/salvar", { corte: a.f.corte, frase: a.f.id, partes: a.partes, prints: a.prints, legenda: $("#ps-legenda").value }).then(() => { const img = $(`#ps-grade img[data-k="${chave(a.f)}"]`); if (img) { img.classList.remove("carregada"); fila.push(img); puxar(); } }).catch((e) => avisar(e.message)); }, 600);
}
$("#ps-legenda").addEventListener("input", salvarDepois);
$("#ps-copiar").addEventListener("click", async () => { try { await navigator.clipboard.writeText($("#ps-legenda").value); avisar("Legenda copiada"); } catch { $("#ps-legenda").select(); } });
$("#ps-escolher").addEventListener("change", async (ev) => { const a = P.aberta; a.f.escolhida = ev.target.checked; await api("POST", "/api/posts/salvar", { corte: a.f.corte, frase: a.f.id, escolhida: a.f.escolhida }).catch((e) => avisar(e.message)); desenharGrade(); });
$("#ps-png").addEventListener("click", async () => { try { const { blob, nome } = await imagemPost(corpoAberto(), false); baixarBlob(blob, nome); } catch (e) { avisar(e.message); } });
$("#ps-apagar").addEventListener("click", async () => { const a = P.aberta; try { await api("POST", "/api/posts/salvar", { corte: a.f.corte, frase: a.f.id, apagar: true }); dlg.close(); await carregar(); } catch (e) { avisar(e.message); } });
dlg.addEventListener("close", () => { if (P.aberta) { clearTimeout(tempoSalvar); const a = P.aberta; api("POST", "/api/posts/salvar", { corte: a.f.corte, frase: a.f.id, partes: a.partes, prints: a.prints, legenda: $("#ps-legenda").value }).catch(() => {}); } P.aberta = null; });
$$("#ps-janela [data-fechar], #ps-dlg-minha [data-fechar]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

/* ---------- Opções que valem para todos ---------- */
function marcarOpcoes() {
  $$("[data-formato]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.formato === P.formato)));
  $$("[data-prints]").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.prints === P.prints)));
  $("#ps-pb").checked = P.pb; $("#ps-assinatura").value = P.assinatura || "";
}
function mudouOpcao(redesenhar = true) { guardarOpcoes(); marcarOpcoes(); if (redesenhar) desenharGrade(); if (P.aberta) { if (P.aberta.partes.length !== P.prints) abrir(P.aberta.f); else previa(); } }
$$("[data-formato]").forEach((b) => b.addEventListener("click", () => { P.formato = b.dataset.formato; mudouOpcao(); }));
$$("[data-prints]").forEach((b) => b.addEventListener("click", () => { P.prints = +b.dataset.prints; mudouOpcao(); }));
$("#ps-fonte").addEventListener("change", (ev) => { P.fonte = ev.target.value; mudouOpcao(); });
$("#ps-pb").addEventListener("change", (ev) => { P.pb = ev.target.checked; mudouOpcao(); });
let tempoAss; $("#ps-assinatura").addEventListener("input", (ev) => { P.assinatura = ev.target.value.trim(); clearTimeout(tempoAss); tempoAss = setTimeout(() => mudouOpcao(), 500); });
$("#ps-pasta").addEventListener("change", (ev) => { P.pasta = ev.target.value; guardarOpcoes(); carregar(); });
$("#ps-buscar").addEventListener("click", buscar);
$("#ps-baixar").addEventListener("click", async (ev) => {
  const b = ev.currentTarget, itens = P.lista.frases.filter((f) => f.escolhida).map((f) => ({ corte: f.corte, frase: f.id, ...opcoes() }));
  if (!itens.length) return; b.disabled = true; const t = b.textContent; b.textContent = "Preparando…";
  try { const r = await fetch("/api/posts/pacote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ itens }) }); if (!r.ok) throw new Error((await r.json()).erro); baixarBlob(await r.blob(), "posts-de-frase.zip"); avisar(`${itens.length} posts baixados, com as legendas em legendas.txt`); }
  catch (e) { avisar(e.message); } finally { b.disabled = false; b.textContent = t; }
});
$("#ps-minha").addEventListener("click", () => {
  const cortes = P.lista.cortes; if (!cortes.length) { avisar("Os rostos saem dos cortes: espere o primeiro corte ficar pronto"); return; }
  $("#ps-m-corte").replaceChildren(...cortes.map((c) => el("option", { value: c.id }, `${c.canal}: ${c.gancho || c.id}`))); $("#ps-m-texto").value = ""; $("#ps-dlg-minha").showModal();
});
$("#ps-form-minha").addEventListener("submit", async (ev) => {
  ev.preventDefault(); const corte = $("#ps-m-corte").value, texto = $("#ps-m-texto").value;
  try { const nova = await api("POST", "/api/posts/minha", { corte, texto }); $("#ps-dlg-minha").close(); await carregar(); const f = P.lista.frases.find((x) => x.id === nova.id && x.corte === corte); if (f) abrir(f); } catch (e) { avisar(e.message); }
});

window.abrirPosts = () => { pastas(); marcarOpcoes(); carregar(); };
if (location.hash === "#posts") window.abrirPosts();
})();
