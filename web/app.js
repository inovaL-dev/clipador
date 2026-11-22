"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const STATUS = { gravando: "Ao vivo", aguardando: "Offline", verificando: "Procurando", conectando: "Conectando", reconectando: "Reconectando", encerrado: "Encerrada", erro: "Com problema" };
const LAYOUTS = { pip: "Jogo em tela cheia com a câmera em cima", dividido: "Câmera em cima e jogo embaixo", tela_cheia: "Só a câmera", inteiro: "Tela inteira" };
const ETAPAS = [["capturando", "Guardando o trecho"], ["transcrevendo", "Transcrevendo"], ["enquadrando", "Enquadrando"], ["editando", "Montando o vídeo"]];
const FINAIS = new Set(["pronto", "erro"]);

let estado = null;
let filtro = "postar";
const cartoes = new Map();
const faixas = new Map();

function el(tag, props = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "dados") Object.assign(n.dataset, v);
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) n.setAttribute(k, v);
  }
  n.append(...filhos.filter((f) => f !== null && f !== undefined));
  return n;
}

async function api(metodo, url, corpo) {
  const r = await fetch(url, { method: metodo, headers: corpo ? { "Content-Type": "application/json" } : {}, body: corpo ? JSON.stringify(corpo) : undefined });
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(dados.erro || "Não foi possível concluir. Tente de novo.");
  return dados;
}

let toastTempo;
function avisar(texto) {
  const t = $("#toast");
  t.textContent = texto;
  t.dataset.visivel = "true";
  clearTimeout(toastTempo);
  toastTempo = setTimeout(() => (t.dataset.visivel = "false"), 3200);
}

const duasCasas = (n) => String(Math.floor(n)).padStart(2, "0");
function relogio(s) {
  s = Math.max(0, s || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${duasCasas(m)}:${duasCasas(s % 60)}` : `${m}:${duasCasas(s % 60)}`;
}
const horaDe = (t) => new Date(t * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
function haQuanto(t) {
  const m = Math.floor((estado.agora - t) / 60);
  if (m < 1) return "agora mesmo";
  if (m < 60) return `há ${m} min`;
  const h = Math.floor(m / 60);
  return h < 24 ? `há ${h} h` : new Date(t * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

/* ---------- Lives ---------- */
const CORES_GRAFICO = [
  ["corte", "Virou corte", "Momento forte que gerou um corte"],
  ["streamer", "Reação do streamer", "A voz ou o rosto do streamer foi o sinal mais forte"],
  ["chat", "Chat agitado", "O chat foi o sinal mais forte, ou o momento estava calmo"],
  ["jogo", "Ação no jogo", "O movimento na tela foi o sinal mais forte"],
];
function legendaGrafico() {
  return el("ul", { class: "legenda-grafico", "aria-label": "O que significa cada cor do gráfico" },
    ...CORES_GRAFICO.map(([cor, nome, ajuda]) => el("li", { title: ajuda }, el("i", { class: `cor-${cor}`, "aria-hidden": "true" }), nome)),
    el("li", { title: "A barra precisa passar desta linha para virar corte" }, el("i", { class: "cor-linha", "aria-hidden": "true" }), "Nota para cortar"),
    el("li", { title: "Clique na seta para abrir o corte" }, el("i", { class: "cor-seta", "aria-hidden": "true" }), "Corte feito"));
}

function criarFaixa(c) {
  const canvas = el("canvas", { role: "img" });
  const info = el("span", {}), limite = el("span", { class: "sismo-auto" });
  const nome = el("h3"), sub = el("p"), selo = el("span", { class: "selo" });
  const chat = el("ul", { class: "chat-vivo", "aria-label": "Chat da live" });
  const cortar = el("button", { class: "botao principal", type: "button", onclick: async () => {
    cortar.disabled = true;
    try { await api("POST", `/api/canais/${c.id}/cortar`); avisar("Corte iniciado"); }
    catch (e) { avisar(e.message); }
    setTimeout(() => (cortar.disabled = false), 2500);
  } }, "Cortar agora", el("kbd", { class: "atalho", title: "Atalho: tecla C" }, "C"));
  const camera = el("button", { class: "botao", type: "button", onclick: () => abrirCamera({ canal: c.id }) }, "Câmera");
  const parar = el("button", { class: "botao fantasma", type: "button", onclick: () => confirmar(parar, "Confirmar", async () => {
    await api("DELETE", `/api/canais/${c.id}`);
    avisar("Live removida");
    atualizar();
  }) }, "Parar");
  const n = el("article", { class: "live" },
    el("header", { class: "live-topo" }, selo, el("div", { class: "live-nome" }, nome, sub), el("div", { class: "live-acoes" }, cortar, camera, parar)),
    el("div", { class: "live-corpo" }, el("div", { class: "sismo" }, canvas, legendaGrafico(), el("p", { class: "sismo-info" }, info, limite)), chat));
  canvas.addEventListener("click", (ev) => {
    const r = canvas.getBoundingClientRect();
    const item = faixas.get(c.id).pontoEm(ev.clientX - r.left);
    if (item?.corte) abrirEditor(item.corte);
  });
  const faixa = { n, canvas, info, limite, nome, sub, selo, chat, cortar, dados: c, pontoEm: () => null };
  new ResizeObserver(() => desenhar(faixa)).observe(canvas);
  faixas.set(c.id, faixa);
  return faixa;
}

function desenhar(f) {
  const c = f.dados, cv = f.canvas, dpr = window.devicePixelRatio || 1;
  const L = cv.clientWidth, A = cv.clientHeight;
  if (!L || !A) return;
  cv.width = L * dpr; cv.height = A * dpr;
  const g = cv.getContext("2d");
  g.scale(dpr, dpr);
  const css = getComputedStyle(document.documentElement);
  const cor = (v) => css.getPropertyValue(v).trim();
  const slots = Math.max(24, Math.min(90, Math.floor(L / 8)));
  const serie = c.serie.slice(-slots);
  const topo = 16, base = A - 1;
  const maior = 100;
  const y = (v) => base - (v / maior) * (base - topo);
  const passo = L / slots, largura = Math.max(2, passo - 2);

  g.fillStyle = cor("--fio");
  g.fillRect(0, base, L, 1);
  const pontos = [];
  serie.forEach((p, i) => {
    const x = L - (serie.length - i) * passo + 1;
    const nota = p.nota || 0;
    const altura = Math.max(2, base - y(nota));
    g.fillStyle = p.corte || p.pico ? cor("--corte") : (p.jogo || 0) > Math.max(p.streamer || 0, p.chat || 0) ? cor("--sinal-jogo") : (p.streamer || 0) > (p.chat || 0) ? cor("--pronto") : cor("--sinal-chat");
    g.beginPath();
    if (g.roundRect) g.roundRect(x, base - altura, largura, altura, [Math.min(3, largura / 2), Math.min(3, largura / 2), 0, 0]); else g.rect(x, base - altura, largura, altura);
    g.fill();
    if (p.corte) {
      g.beginPath();
      g.moveTo(x + largura / 2 - 5, 2); g.lineTo(x + largura / 2 + 5, 2); g.lineTo(x + largura / 2, 10);
      g.closePath(); g.fill();
    }
    pontos.push({ x, corte: p.corte });
  });
  if (c.limite && !c.aquecendo) {
    g.strokeStyle = cor("--giz-medio");
    g.setLineDash([4, 5]);
    g.beginPath(); g.moveTo(0, Math.round(y(c.limite)) + .5); g.lineTo(L, Math.round(y(c.limite)) + .5); g.stroke();
    g.setLineDash([]);
  }
  f.pontoEm = (px) => pontos.find((p) => p.corte && Math.abs(p.x - px) <= Math.max(passo, 12));
  cv.style.cursor = pontos.some((p) => p.corte) ? "pointer" : "default";
}

function atualizarFaixa(c) {
  const f = faixas.get(c.id) || criarFaixa(c);
  f.dados = c;
  f.n.dataset.status = c.status;
  f.selo.textContent = c.status === "gravando" ? `Ao vivo ${relogio(c.gravado)}` : STATUS[c.status] || c.status;
  f.nome.textContent = c.nome;
  f.sub.textContent = c.status === "gravando" ? `${c.nome_plataforma}${c.titulo ? `: ${c.titulo}` : ""}` : `${c.nome_plataforma}. ${c.mensagem}`;
  f.sub.title = f.sub.textContent;
  f.cortar.disabled = c.status !== "gravando";
  let info = "A força dos momentos aparece quando a live abrir";
  let limite = "";
  if (c.status === "gravando") {
    if (c.aquecendo) info = "Aprendendo o ritmo da live";
    else {
      info = "";
      const fonte = c.sinal === "audio" ? "chat indisponível" : `chat ${c.nota.chat}`;
      f.info.replaceChildren(el("b", {}, `Momento ${c.nota.nota} de 100`), `: streamer ${c.nota.streamer}, ${fonte}, jogo ${c.nota.jogo}. Corta em ${c.limite}`);
    }
    limite = c.proximo_auto === null ? "Cortando só por reação do streamer e do chat" : `Cortando por reação. Melhor momento em até ${relogio(c.proximo_auto)}`;
  }
  if (info) f.info.textContent = info;
  f.limite.textContent = limite;
  f.canvas.setAttribute("aria-label", `Força do momento na live de ${c.nome}: ${c.nota.nota} de 100`);
  const linhas = c.ultimas.slice(-8).map((m) => el("li", { title: m.texto }, el("b", {}, m.autor || "chat"), m.texto));
  f.chat.replaceChildren(...(linhas.length ? linhas : [el("li", { class: "vazio" }, c.status === "gravando" ? "Aguardando mensagens do chat" : "O chat aparece aqui durante a live")]));
  desenhar(f);
  return f;
}

function renderLives() {
  const area = $("#lives");
  const ids = new Set(estado.canais.map((c) => c.id));
  for (const [id, f] of faixas) if (!ids.has(id)) { f.n.remove(); faixas.delete(id); }
  estado.canais.forEach((c, i) => {
    const f = atualizarFaixa(c);
    if (area.children[i] !== f.n) area.insertBefore(f.n, area.children[i] || null);
  });
}

/* ---------- Agora ---------- */
let assinaturaEventos = "";
function renderAgora() {
  const leg = estado.sistema.legenda, aviso = $("#aviso-legenda");
  aviso.hidden = leg.estado === "pronto" && !leg.aviso;
  aviso.textContent = leg.aviso ? leg.aviso : leg.estado === "carregando"
    ? "Preparando a legenda automática. Na primeira vez, o download pode levar alguns minutos. Os cortes continuam sendo editados."
    : "A legenda automática não abriu. Os cortes saem sem texto até você reabrir o programa com internet.";
  const emAndamento = estado.cortes.filter((c) => !FINAIS.has(c.status)).reverse();
  $("#fila").replaceChildren(...emAndamento.map((c) => el("li", {}, el("b", {}, c.canal), el("span", {}, c.etapa))));
  const assinatura = estado.eventos.length + ":" + (estado.eventos[0]?.t || 0);
  if (assinatura === assinaturaEventos) return;
  assinaturaEventos = assinatura;
  const lista = $("#eventos"), rolagem = lista.scrollTop;
  // Quem está lendo o histórico não perde o lugar quando chega um evento novo.
  const ancora = rolagem > 0 ? [...lista.children].find((li) => li.offsetTop + li.offsetHeight > lista.offsetTop + rolagem) : null;
  const folga = ancora ? ancora.offsetTop - lista.offsetTop - rolagem : 0;
  const marca = ancora?.dataset.t;
  lista.replaceChildren(...estado.eventos.map((e) =>
    el("li", { dados: { tipo: e.tipo, t: e.t } }, el("time", {}, horaDe(e.t)), el("span", {}, e.texto))));
  const mesmo = marca ? [...lista.children].find((li) => li.dataset.t === marca) : null;
  lista.scrollTop = mesmo ? mesmo.offsetTop - lista.offsetTop - folga : rolagem;
}

/* ---------- Cortes ---------- */
/* ---------- Seleção de vários cortes ---------- */
let modoSelecao = false, listaFiltrada = [];
const marcados = new Set();
const selecionavel = () => true;  // os que ainda estão em edição também: apagar cancela a edição
function atualizarBarraSelecao() {
  const visiveis = [...cartoes.entries()].filter(([id]) => listaFiltrada.some((c) => c.id === id && selecionavel(c)));
  const n = marcados.size, todos = listaFiltrada.filter(selecionavel).length;
  $("#sel-total").textContent = n ? `${n} ${n === 1 ? "selecionado" : "selecionados"}` : "Nenhum selecionado";
  $("#sel-apagar").disabled = $("#sel-postado").disabled = !n;
  $("#sel-apagar").textContent = n ? `Apagar ${n}` : "Apagar";
  $("#sel-todos").textContent = n === todos && todos ? "Tirar a seleção" : `Selecionar todos os ${todos}`;
  $("#sel-todos").hidden = !todos;
  const pg = $("#sel-pagina");
  pg.checked = visiveis.length > 0 && visiveis.every(([id]) => marcados.has(id));
  pg.indeterminate = !pg.checked && visiveis.some(([id]) => marcados.has(id));
  visiveis.forEach(([id, item]) => { item.n.classList.toggle("marcado", marcados.has(id)); const cx = item.n.querySelector(".sel-caixa"); if (cx) cx.checked = marcados.has(id); });
}
function alternarSelecao(ligar) {
  modoSelecao = ligar; if (!ligar) marcados.clear();
  $("#barra-selecao").hidden = !ligar; $("#selecionar-cortes").setAttribute("aria-pressed", String(ligar));
  $("#grade").classList.toggle("selecionando", ligar);
  cartoes.forEach((item) => { item.sinal = ""; }); renderCortes(); atualizarBarraSelecao();
}
function marcar(c, sim) { if (!selecionavel(c)) return; if (sim) marcados.add(c.id); else marcados.delete(c.id); atualizarBarraSelecao(); }
$("#selecionar-cortes").addEventListener("click", () => alternarSelecao(!modoSelecao));
$("#sel-sair").addEventListener("click", () => alternarSelecao(false));
$("#sel-pagina").addEventListener("change", (ev) => {
  [...cartoes.keys()].forEach((id) => { const c = listaFiltrada.find((x) => x.id === id); if (c && selecionavel(c)) { if (ev.target.checked) marcados.add(id); else marcados.delete(id); } });
  atualizarBarraSelecao();
});
$("#sel-todos").addEventListener("click", () => {
  const todos = listaFiltrada.filter(selecionavel);
  if (marcados.size === todos.length) marcados.clear(); else todos.forEach((c) => marcados.add(c.id));
  atualizarBarraSelecao();
});
$("#sel-apagar").addEventListener("click", (ev) => confirmar(ev.currentTarget, `Apagar ${marcados.size} de vez`, async () => {
  try {
    const r = await api("POST", "/api/cortes/apagar", { ids: [...marcados] });
    avisar(`${r.apagados} ${r.apagados === 1 ? "corte apagado" : "cortes apagados"}`);
    marcados.clear(); await atualizar(); atualizarBarraSelecao();
  } catch (e) { avisar(e.message); }
}));
$("#cancelar-edicoes").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Cancelar todas", async () => {
  try {
    const r = await api("POST", "/api/cortes/cancelar-edicoes", {});
    avisar(r.total ? `${r.total} ${r.total === 1 ? "edição cancelada" : "edições canceladas"}` : "Nada estava sendo editado");
    await atualizar();
  } catch (e) { avisar(e.message); }
}));
$("#sel-postado").addEventListener("click", async () => {
  try { const r = await api("POST", "/api/cortes/postados", { ids: [...marcados], postado: true }); avisar(`${r.total} ${r.total === 1 ? "corte marcado" : "cortes marcados"} como postado`); marcados.clear(); await atualizar(); atualizarBarraSelecao(); }
  catch (e) { avisar(e.message); }
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && modoSelecao && !document.querySelector("dialog[open]")) alternarSelecao(false); });

function cartao(c) {
  const poster = el("div", { class: "poster" });
  if (modoSelecao && selecionavel(c)) {
    const caixa = el("input", { type: "checkbox", class: "sel-caixa", "aria-label": `Selecionar ${c.gancho || "corte"}` });
    caixa.checked = marcados.has(c.id);
    caixa.addEventListener("click", (ev) => { ev.stopPropagation(); marcar(c, caixa.checked); });
    poster.append(caixa);
  }
  if (c.status === "pronto") {
    poster.append(el("img", { src: `/cortes/${c.id}/capa.jpg?v=${c.versao || 0}`, alt: "", loading: "lazy" }),
      el("span", { class: "poster-reacao" }, c.postado ? "Postado" : c.reacao_rotulo),
      el("span", { class: "poster-dur" }, relogio(c.duracao)));
    if (c.potencial) poster.append(seloPotencial(c.potencial));
  } else if (c.status === "erro") {
    poster.append(el("div", { class: "falhou" }, c.erro || "Não foi possível editar este corte."));
  } else {
    const atual = c.status === "fila" ? -1 : ETAPAS.findIndex(([k]) => k === c.status);
    const passou = c.status === "fila" ? 1 : atual;
    poster.append(el("ol", { class: "etapas" }, ...ETAPAS.map(([, nome], i) =>
      el("li", { dados: { estado: i < passou ? "feito" : i === atual ? "atual" : "" } }, nome))),
      c.status === "fila" && c.na_fila ? el("span", { class: "na-fila" }, c.na_fila === 1 ? "Próximo a ser editado" : `${c.na_fila}º na fila de edição`) : null,
      el("span", { class: "bs-assistir" }, "Assistir a edição"));
  }
  const titulo = c.gancho || (c.status === "erro" ? "Corte com problema" : c.motivo);
  return el("button", { class: "corte", type: "button", dados: { postado: String(!!c.postado) }, disabled: c.status === "pronto" ? null : undefined,
    onclick: () => { if (modoSelecao) { if (selecionavel(c)) marcar(c, !marcados.has(c.id)); return; } if (c.status === "pronto") abrirEditor(c.id); else if (c.status === "erro") removerFalho(c); else abrirBastidores(c.id); } },
    poster, el("h3", {}, titulo), el("p", {}, `${c.canal}, ${haQuanto(c.criado)}`));
}

const NOMES_IDEIA = { padrao: "Seu estilo", react: "React com câmera dinâmica" };
const NIVEL_POTENCIAL = { alto: "Alto", medio: "Médio", baixo: "Baixo" };
function seloPotencial(p) {
  return el("span", { class: "poster-potencial", dados: { nivel: p.nivel }, title: `Potencial de viralizar: ${p.nota}% (${NIVEL_POTENCIAL[p.nivel] || ""})` },
    `${p.nota}%`);
}
function mostrarPotencial(c) {
  const caixa = $("#ed-potencial"), p = c.potencial;
  caixa.hidden = !p;
  if (!p) return;
  caixa.dataset.nivel = p.nivel;
  $("#ed-pot-nota").textContent = `${p.nota}%`;
  $("#ed-pot-anel").style.setProperty("--pct", p.nota);
  $("#ed-pot-nivel").textContent = `${NIVEL_POTENCIAL[p.nivel]}${p.dicas?.length ? ` · ${p.dicas.length} ${p.dicas.length === 1 ? "dica" : "dicas"} para melhorar` : ""}`;
  $("#ed-pot-partes").replaceChildren(...p.partes.map((x) => el("li", {},
    el("span", { class: "pp-nome" }, x.nome),
    el("span", { class: "pp-barra", style: `--v:${Math.max(0, x.pontos) / x.maximo}`, dados: { negativo: String(x.pontos < 0) } }),
    el("b", {}, x.nome === "No seu canal" ? `${x.pontos > 0 ? "+" : ""}${x.pontos}` : `${x.pontos}/${x.maximo}`),
    el("small", {}, x.texto))));
  const mh = c.melhorado;
  $("#ed-pot-melhorado").hidden = !mh;
  if (mh) $("#ed-pot-melhorado").textContent = [
    mh.mudancas?.length ? `${mh.auto ? "Melhorado sozinho" : "Melhorado"}: de ${mh.antes}% para ${mh.depois}% (${mh.mudancas.join(", ")}).` : "",
    mh.montagem ? "Este momento também virou um Short de cenas emendadas com as cenas mais fortes da mesma live. Ele está em Montagens." : "",
    mh.limite || ""].filter(Boolean).join(" ");
  $("#ed-melhorar").hidden = !(p.nota < 90 && !c.projeto_exportado && !c.montagem);
  $("#ed-pot-dicas").replaceChildren(...(p.dicas || []).map((d) => el("li", {}, d)));
}

let falhoMarcado = null;
async function removerFalho(c) {
  if (falhoMarcado !== c.id) {
    falhoMarcado = c.id;
    avisar("Clique de novo para remover este corte com problema");
    setTimeout(() => { if (falhoMarcado === c.id) falhoMarcado = null; }, 3500);
    return;
  }
  falhoMarcado = null;
  try { await api("DELETE", `/api/cortes/${c.id}`); avisar("Corte com problema removido"); atualizar(); }
  catch (e) { avisar(e.message); }
}

let paginaCortes = 1;
function desenharPaginas(caixa, atual, total, ir) {
  const seta = (rotulo, destino, ativo) => { const b = el("button", { class: "botao fantasma", type: "button", onclick: () => ir(destino) }, rotulo); b.disabled = !ativo; return b; };
  caixa.replaceChildren(seta("Anterior", atual - 1, atual > 1), ...numerosPagina(atual, total).map((n) => n === "…" ? el("span", { "aria-hidden": "true" }, "…")
    : el("button", { class: "pagina", type: "button", "aria-label": `Página ${n}`, "aria-current": n === atual ? "page" : undefined, onclick: () => ir(n) }, String(n))), seta("Próxima", atual + 1, atual < total));
}
function montarPaginas(nav, atual, total, ir) {
  nav.hidden = total < 2; desenharPaginas($("[data-paginas]", nav), atual, total, ir);
}
function renderCortes() {
  renderFiltrosPasta();
  const emEdicao = estado.cortes.filter((c) => !FINAIS.has(c.status)).length;
  const btCancelar = $("#cancelar-edicoes");
  btCancelar.hidden = !emEdicao;
  if (btCancelar.dataset.confirmar !== "true") btCancelar.textContent = `Cancelar ${emEdicao} ${emEdicao === 1 ? "edição" : "edições"}`;
  const pastaVista = $("#filtro-pasta").value;
  const prontos = pastaVista ? estado.cortes.filter((c) => c.pasta === pastaVista) : estado.cortes;
  const postados = prontos.filter((c) => c.postado);
  const postar = prontos.filter((c) => !c.postado);
  $("#n-postar").textContent = postar.length; $("#n-postados").textContent = postados.length; $("#n-todos").textContent = prontos.length;
  const montagens = prontos.filter((c) => c.montagem);
  $("#n-montagens").textContent = montagens.length;
  let todos = filtro === "postar" ? postar : filtro === "postados" ? postados : filtro === "montagens" ? montagens : prontos;
  if ($("#ordem-cortes").value === "potencial") todos = [...todos].sort((a, b) => (b.potencial?.nota ?? -1) - (a.potencial?.nota ?? -1));
  listaFiltrada = todos;
  [...marcados].forEach((id) => { if (!todos.some((c) => c.id === id)) marcados.delete(id); });
  const porPagina = +$("#cortes-por-pagina").value, paginas = Math.max(1, Math.ceil(todos.length / porPagina));
  paginaCortes = Math.min(paginaCortes, paginas);
  const inicioPagina = (paginaCortes - 1) * porPagina, lista = todos.slice(inicioPagina, inicioPagina + porPagina);
  const nav = $("#cortes-paginacao");
  nav.hidden = todos.length <= 12;
  $("#cortes-contagem").textContent = todos.length ? `Mostrando ${inicioPagina + 1} a ${inicioPagina + lista.length} de ${todos.length}` : "";
  const sinalPaginas = `${paginaCortes}/${paginas}`;
  if (nav.dataset.sinal !== sinalPaginas) { nav.dataset.sinal = sinalPaginas; desenharPaginas($("#cortes-paginas"), paginaCortes, paginas, (n) => { paginaCortes = n; renderCortes(); $("#aba-cortes").scrollIntoView(); }); }
  const grade = $("#grade");
  const vivos = new Set(lista.map((c) => c.id));
  for (const [id, item] of cartoes) if (!vivos.has(id)) { item.n.remove(); cartoes.delete(id); }
  const minuto = Math.floor(estado.agora / 60);
  lista.forEach((c, i) => {
    const sinal = [c.status, c.versao, c.postado, c.gancho, c.erro, c.potencial?.nota, c.na_fila, minuto, modoSelecao].join("|");
    let item = cartoes.get(c.id);
    if (!item || item.sinal !== sinal) {
      const novo = cartao(c);
      if (item) item.n.replaceWith(novo);
      item = { n: novo, sinal };
      cartoes.set(c.id, item);
    }
    if (grade.children[i] !== item.n) grade.insertBefore(item.n, grade.children[i] || null);
  });
  if (modoSelecao) atualizarBarraSelecao();
  const vazio = $("#sem-cortes");
  vazio.hidden = todos.length > 0;
  vazio.textContent = filtro === "montagens" ? "Clique em Criar montagem para juntar os melhores momentos em um só vídeo." : filtro === "postados" ? "Os cortes marcados como postados ficam aqui."
    : estado.canais.some((c) => c.status === "gravando") ? "O primeiro corte aparece quando o chat explodir. Se quiser, use Cortar agora."
    : "Os cortes aparecem aqui assim que uma live estiver no ar.";
}

/* ---------- Montagem com várias cenas ---------- */
function pastasDaMontagem() {
  const contagem = new Map();
  estado.cortes.forEach((c) => { if (c.status === "pronto" && !c.montagem && c.pasta) contagem.set(c.pasta, (contagem.get(c.pasta) || 0) + 1); });
  return [...contagem.entries()].map(([id, n]) => ({ id, n, nome: estado.cortes.find((c) => c.pasta === id)?.canal || "Live" }));
}
$("#abrir-montagem").addEventListener("click", () => {
  const lista = pastasDaMontagem(), sel = $("#mt-pasta");
  sel.replaceChildren(...lista.map((p) => el("option", { value: p.id }, `${p.nome}: ${p.n} ${p.n === 1 ? "corte" : "cortes"}`)));
  if (lista.some((p) => p.id === $("#filtro-pasta").value)) sel.value = $("#filtro-pasta").value;
  $("#mt-cenas").value = String(estado.config.montagem_cenas || 4); $("#mt-erro").hidden = true; $("#janela-montagem").showModal();
});
$("#form-montagem").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try { await api("POST", "/api/montagens", { pasta: $("#mt-pasta").value, cenas: +$("#mt-cenas").value, emendado: $('#form-montagem input[name="mt-tipo"]:checked')?.value === "emendado" }); $("#janela-montagem").close(); avisar("A montagem começou"); atualizar(); }
  catch (e) { $("#mt-erro").textContent = e.message; $("#mt-erro").hidden = false; }
});

$("#cortes-por-pagina").addEventListener("change", () => { paginaCortes = 1; renderCortes(); });
try { $("#ordem-cortes").value = localStorage.getItem("clipador.ordem") || "recentes"; } catch {}
$("#ordem-cortes").addEventListener("change", (e) => { try { localStorage.setItem("clipador.ordem", e.target.value); } catch {} paginaCortes = 1; renderCortes(); });
$("#filtro-pasta").addEventListener("change", () => { paginaCortes = 1; });
$$("#aba-cortes .filtros button").forEach((b) => b.addEventListener("click", () => {
  filtro = b.dataset.filtro; paginaCortes = 1;
  $$("#aba-cortes .filtros button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  if (estado) renderCortes();
}));

/* ---------- Aviso de versão nova ---------- */
const CHAVE_IGNORADA = "clipador-atualizacao-ignorada";
function versaoIgnorada() { try { return localStorage.getItem(CHAVE_IGNORADA); } catch { return null; } }
function renderAtualizacao() {
  const nova = estado.atualizacao?.nova, caixa = $("#av-atualizacao"), mostrar = Boolean(nova) && versaoIgnorada() !== nova.versao;
  if (caixa.hidden === !mostrar && caixa.dataset.versao === (nova?.versao || "")) return;
  caixa.hidden = !mostrar; caixa.dataset.versao = nova?.versao || "";
  if (!nova) return;
  $("#av-titulo").textContent = `Nova versão ${nova.versao} disponível`;
  $("#av-notas").replaceChildren(...nova.notas.map((n) => el("li", {}, n)));
}
$("#av-depois").addEventListener("click", () => { try { localStorage.setItem(CHAVE_IGNORADA, $("#av-atualizacao").dataset.versao); } catch {} $("#av-atualizacao").hidden = true; });
$("#av-baixar").addEventListener("click", async () => {
  try { await api("POST", "/api/atualizacao/abrir"); $("#av-dica").textContent = "Quando o download terminar, feche o Clipador e abra o instalador."; $("#av-baixar").textContent = "Baixar de novo"; }
  catch (e) { avisar(e.message); }
});
$("#aj-atualizar").addEventListener("click", async (ev) => {
  const b = ev.currentTarget; b.disabled = true; b.textContent = "Procurando";
  try {
    const a = await api("POST", "/api/atualizacao/verificar");
    if (a.nova) { try { localStorage.removeItem(CHAVE_IGNORADA); } catch {} estado.atualizacao = a; $("#janela-ajustes").close(); renderAtualizacao(); }
    else avisar(a.erro ? "Não foi possível procurar agora. Confira a internet." : `Você já está na versão mais recente, ${a.atual}.`);
  } catch (e) { avisar(e.message); }
  b.disabled = false; b.textContent = "Procurar atualizações";
});

// Uma parte da tela com problema não derruba as outras, e o erro vai para o registro do programa.
const errosAvisados = new Set();
function avisarErroTela(onde, e) {
  const msg = `${onde}: ${e?.message || e}`; console.error(msg, e);
  if (errosAvisados.has(msg) || errosAvisados.size > 20) return; errosAvisados.add(msg);
  fetch("/api/programa/erro", { method: "POST", body: JSON.stringify({ msg, pilha: String(e?.stack || "").slice(0, 1500), versao: document.documentElement.dataset.versao || "" }) }).catch(() => {});
}
addEventListener("error", (ev) => avisarErroTela("janela", ev.error || ev.message));
addEventListener("unhandledrejection", (ev) => avisarErroTela("promessa", ev.reason));
function seguro(nome, fn) { try { fn(); } catch (e) { avisarErroTela(nome, e); } }
function renderTudo() {
  seguro("atualizacao", renderAtualizacao);
  const temAlgo = estado.canais.length > 0 || estado.cortes.length > 0;
  document.body.dataset.vazio = String(!temAlgo);
  document.body.dataset.noAr = String(estado.canais.some((c) => c.status === "gravando"));
  $("#mesa").hidden = estado.canais.length === 0;
  const aoVivo = estado.canais.filter((c) => c.status === "gravando").length;
  const ativos = estado.canais.filter((c) => c.status !== "encerrado").length, cabe = estado.sistema.lives_recomendadas || 4;
  $("#lives").classList.toggle("lives-grade", estado.canais.length >= 2);
  $("#lives-capacidade").hidden = ativos < 2;
  $("#lives-capacidade").textContent = ativos > cabe
    ? `Acompanhando ${ativos} lives. Este computador aguenta bem até ${cabe} ao mesmo tempo; com mais, os cortes podem demorar a ficar prontos. Os momentos mais fortes são editados primeiro.`
    : `Acompanhando ${ativos} lives ao mesmo tempo (este computador aguenta bem até ${cabe}). Os momentos mais fortes de todas são editados primeiro.`;
  $("#lives-capacidade").dataset.alerta = String(ativos > cabe);
  const edicao = estado.cortes.filter((c) => !FINAIS.has(c.status)).length;
  $("#resumo").textContent = !temAlgo ? "" : [aoVivo ? `${aoVivo} ${aoVivo > 1 ? "lives" : "live"} no ar` : "Nenhuma live no ar", edicao ? `${edicao} em edição` : null].filter(Boolean).join(", ");
  $("#n-vivo").textContent = aoVivo || "";
  $("#n-cortes").textContent = estado.cortes.filter((c) => !c.postado).length || "";
  for (const [nome, fn] of [["lives", renderLives], ["agora", renderAgora], ["cortes", renderCortes], ["recentes", renderRecentes], ["postagem", renderPostagem], ["longos", renderLongos]]) seguro(nome, fn);
  if (typeof renderEditor === "function") seguro("editor", renderEditor);
}

// Só avisa "sem conexão" quando o programa deixa de responder de verdade (várias tentativas seguidas),
// e nunca dispara um pedido novo enquanto o anterior ainda está a caminho.
let pedindoEstado = false, ultimoOk = Date.now();
function conferirConexao() { if (Date.now() - ultimoOk > 30000) { document.body.dataset.semConexao = "1"; $("#resumo").textContent = "Sem resposta do programa. Se continuar assim, feche e abra o Clipador; as gravações seguem salvas."; } }
async function atualizar() {
  conferirConexao(); if (pedindoEstado) return; pedindoEstado = true;
  const parar = new AbortController(), relogio = setTimeout(() => parar.abort(), 12000);
  try {
    const r = await fetch("/api/estado", { signal: parar.signal, cache: "no-store" }); if (!r.ok) throw new Error(`HTTP ${r.status}`);
    estado = await r.json(); ultimoOk = Date.now(); document.body.removeAttribute("data-sem-conexao");
  } catch { conferirConexao(); return; } finally { clearTimeout(relogio); pedindoEstado = false; }
  renderTudo();
}
setInterval(() => { if (!document.hidden) atualizar(); }, 1000);
// Avisa o programa que a tela está viva. Quando a janela vai para trás ou é minimizada, avisa na hora,
// para o programa nunca confundir uma tela em espera com uma tela travada.
const sinalTela = () => fetch("/api/programa/sinal", { method: "POST", body: JSON.stringify({ visivel: !document.hidden }), keepalive: true }).catch(() => {});
setInterval(sinalTela, 10000); document.addEventListener("visibilitychange", sinalTela); addEventListener("focus", sinalTela); sinalTela();
document.addEventListener("visibilitychange", () => { if (!document.hidden) atualizar(); });

function confirmar(botao, rotulo, acao) {
  if (botao.dataset.confirmar === "true") {
    botao.dataset.confirmar = "false";
    acao().catch((e) => avisar(e.message));
    return;
  }
  const original = botao.textContent;
  botao.dataset.confirmar = "true";
  botao.textContent = rotulo;
  setTimeout(() => { botao.dataset.confirmar = "false"; botao.textContent = original; }, 3500);
}

/* Um ou vários links, separados por espaço, vírgula, ponto e vírgula ou quebra de linha. */
function separarLinks(texto) {
  return [...new Set(texto.split(/[\s,;]+/).map((x) => x.trim()).filter((x) => /\.|^@/.test(x)))];
}
$("#link").addEventListener("input", () => { const n = separarLinks($("#link").value).length; $("#link-enviar").textContent = n > 1 ? `Acompanhar ${n} lives` : "Acompanhar live"; });
$("#form-link").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const campo = $("#link"), erro = $("#erro-link");
  erro.hidden = true;
  const links = separarLinks(campo.value);
  if (!links.length) { erro.textContent = "Cole o link de uma live para começar."; erro.hidden = false; campo.focus(); return; }
  try {
    if (links.length === 1) { await api("POST", "/api/canais", { link: links[0], programar: $("#link-programar").checked }); avisar("Live adicionada"); campo.value = ""; }
    else {
      const r = await api("POST", "/api/canais", { links, programar: $("#link-programar").checked });
      const n = r.adicionadas.length;
      avisar(n ? `${n} ${n === 1 ? "live adicionada" : "lives adicionadas"}: ${r.adicionadas.map((x) => x.nome).join(", ")}` : "Nenhuma live nova");
      campo.value = r.erros.map((x) => x.link).join(" ");
      if (r.erros.length) { erro.textContent = r.erros.map((x) => `${x.link}: ${x.erro}`).join(" "); erro.hidden = false; }
    }
    $("#link-programar").checked = false; atualizar();
  } catch (e) { erro.textContent = e.message; erro.hidden = false; campo.focus(); }
});

/* ---------- Editor de corte ---------- */
let corteAberto = null, vigia = null;

function marcarAlterado() {}

function preencherEditor(c) {
  $("#ed-salvar").hidden = !!c.projeto_exportado;
  corteAberto = c;
  $("#ed-titulo").textContent = c.canal;
  $("#ed-meta").textContent = `${c.nome_plataforma}, ${relogio(c.duracao)} de vídeo. ${c.motivo}.${c.ideia ? ` Ideia em teste: ${c.ideia_nome || NOMES_IDEIA[c.ideia] || c.ideia}.` : ""}`;
  $("#ed-camera-bloco").hidden = c.plano?.layout !== "dividido";
  $("#ed-abertura").value = c.estilo?.abertura === undefined ? "" : String(c.estilo.abertura === true || c.estilo.abertura === "true");
  $("#ed-camera-dinamica").value = c.estilo?.camera_dinamica === undefined ? "" : String(c.estilo.camera_dinamica === true || c.estilo.camera_dinamica === "true");
  $("#ed-gancho").value = c.gancho || "";
  $("#ed-post").value = c.post || "";
  $("#ed-estilo-legenda").value = c.estilo?.legenda || ""; $("#ed-estilo-gancho").value = c.estilo?.gancho || "";
  $("#ed-layout").textContent = LAYOUTS[c.layout] || "Automático";
  mostrarPotencial(c);
  const minimo = estado?.postagem?.config?.potencial_minimo || 0, nota = c.potencial?.nota;
  const abaixo = minimo && nota != null && nota < minimo && !c.postado;
  $("#ed-abaixo").hidden = !abaixo;
  if (abaixo) {
    $("#ed-abaixo-texto").textContent = c.forcar_postagem ? `Liberado para a agenda, mesmo abaixo de ${minimo}%.` : `Fora da agenda: o mínimo da postagem é ${minimo}%.`;
    $("#ed-forcar").textContent = c.forcar_postagem ? "Tirar da agenda" : "Postar mesmo assim";
  }
  $("#ed-baixar").href = `/cortes/${c.id}/corte.mp4?baixar=1`;
  $("#ed-postado").textContent = c.postado ? "Voltar para postar" : "Marcar como postado";
  const video = $("#ed-video");
  video.src = `/cortes/${c.id}/corte.mp4?v=${c.versao || 0}`;
  video.poster = `/cortes/${c.id}/capa.jpg?v=${c.versao || 0}`;
  $("#ed-linhas").replaceChildren(...(c.grupos || []).map((g, i) => {
    const texto = g.palavras.map((p) => p.p).join(" ");
    return el("li", { dados: { ini: g.ini, fim: g.fim } },
      el("button", { type: "button", "aria-label": `Ir para ${relogio(g.ini)}`, onclick: () => { video.currentTime = g.ini; video.play(); } }, relogio(g.ini)),
      el("input", { value: texto, "aria-label": `Linha ${i + 1} da legenda`, oninput: marcarAlterado }));
  }));
  if (!c.grupos?.length) $("#ed-linhas").replaceChildren(el("li", { class: "dica" }, "Nenhuma fala foi reconhecida neste trecho."));
}

async function abrirEditor(id) {
  try {
    const c = await api("GET", `/api/cortes/${id}`);
    preencherEditor(c);
    $("#ed-refazendo").hidden = FINAIS.has(c.status);
    $("#editor").showModal();
    if (!FINAIS.has(c.status)) acompanharRefazer(id);
  } catch (e) { avisar(e.message); }
}

function acompanharRefazer(id) {
  clearInterval(vigia);
  $("#ed-refazendo").hidden = false;
  vigia = setInterval(async () => {
    const c = await api("GET", `/api/cortes/${id}`).catch(() => null);
    if (!c) return;
    $("#ed-refazendo-texto").textContent = { fila: "Na fila de edição", enquadrando: "Enquadrando a câmera", editando: "Montando o vídeo" }[c.status] || "Refazendo o vídeo";
    if (!FINAIS.has(c.status)) return;
    clearInterval(vigia);
    $("#ed-refazendo").hidden = true;
    if (corteAberto?.id === id) preencherEditor(c);
    avisar(c.status === "pronto" ? "Vídeo atualizado" : c.erro || "Não foi possível refazer o vídeo");
  }, 800);
}

$("#ed-video").addEventListener("timeupdate", (ev) => {
  const t = ev.target.currentTime;
  $$("#ed-linhas li[data-ini]").forEach((l) => { l.dataset.ativa = String(t >= +l.dataset.ini && t < +l.dataset.fim + .3); });
});
$("#ed-gancho").addEventListener("input", marcarAlterado);

$("#ed-post").addEventListener("change", async () => {
  await api("PATCH", `/api/cortes/${corteAberto.id}`, { post: $("#ed-post").value }).catch((e) => avisar(e.message));
});
$("#ed-copiar").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#ed-post").value); avisar("Texto copiado"); }
  catch { $("#ed-post").select(); document.execCommand("copy"); avisar("Texto copiado"); }
});
$("#ed-postado").addEventListener("click", async () => {
  const novo = !corteAberto.postado;
  try {
    const c = await api("PATCH", `/api/cortes/${corteAberto.id}`, { postado: novo });
    corteAberto.postado = c.postado;
    $("#ed-postado").textContent = c.postado ? "Voltar para postar" : "Marcar como postado";
    avisar(c.postado ? "Marcado como postado" : "Voltou para a lista de postagem");
    atualizar();
  } catch (e) { avisar(e.message); }
});
$("#ed-salvar").addEventListener("click", async () => {
  const grupos = $$("#ed-linhas li[data-ini] input").map((i) => ({ texto: i.value }));
  try {
    await api("PATCH", `/api/cortes/${corteAberto.id}`, { gancho: $("#ed-gancho").value, post: $("#ed-post").value, grupos, refazer: true, estilo: { legenda: $("#ed-estilo-legenda").value, gancho: $("#ed-estilo-gancho").value, ...($("#ed-camera-bloco").hidden || !$("#ed-camera-dinamica").value ? {} : { camera_dinamica: $("#ed-camera-dinamica").value }),
    ...($("#ed-abertura").value ? { abertura: $("#ed-abertura").value } : {}) } });
    acompanharRefazer(corteAberto.id);
  } catch (e) { avisar(e.message); }
});
$("#ed-excluir").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Confirmar exclusão", async () => {
  await api("DELETE", `/api/cortes/${corteAberto.id}`);
  $("#editor").close();
  avisar("Corte excluído");
  atualizar();
}));
$("#ed-enquadrar").addEventListener("click", () => abrirCamera({ corte: corteAberto }));
$("#ed-melhorar").addEventListener("click", async (ev) => {
  const b = ev.currentTarget; b.disabled = true; b.textContent = "Testando outras versões…";
  try {
    const r = await api("POST", `/api/cortes/${corteAberto.id}/melhorar`);
    if (r.melhorou) { avisar(`Potencial de ${r.antes}% para ${r.depois}%. Refazendo o vídeo`); acompanharRefazer(corteAberto.id); }
    else avisar(r.mensagem);
  } catch (e) { avisar(e.message); }
  b.disabled = false; b.textContent = "Melhorar o potencial sozinho";
});
$("#ed-forcar").addEventListener("click", async () => {
  const liberar = !corteAberto.forcar_postagem;
  try { await api("PATCH", `/api/cortes/${corteAberto.id}`, { forcar_postagem: liberar }); corteAberto.forcar_postagem = liberar; const minimo = estado?.postagem?.config?.potencial_minimo || 0;
    $("#ed-abaixo-texto").textContent = liberar ? `Liberado para a agenda, mesmo abaixo de ${minimo}%.` : `Fora da agenda: o mínimo da postagem é ${minimo}%.`; $("#ed-forcar").textContent = liberar ? "Tirar da agenda" : "Postar mesmo assim"; avisar(liberar ? "Este corte entra na agenda" : "Este corte saiu da agenda"); atualizar(); }
  catch (e) { avisar(e.message); }
});
$("#ed-bastidores").addEventListener("click", () => { const c = corteAberto.id; $("#editor").close(); abrirBastidores(c, true); });
$("#editor").addEventListener("close", () => { clearInterval(vigia); $("#ed-video").pause(); $("#ed-video").removeAttribute("src"); $("#ed-video").load(); corteAberto = null; });

$$("[data-fechar]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

/* ---------- Enquadramento ---------- */
let alvoCamera = null, area = [0.02, 0.62, 0.26, 0.34];

function posicionarMarcador() {
  const m = $("#marcador");
  m.style.left = `${area[0] * 100}%`; m.style.top = `${area[1] * 100}%`;
  m.style.width = `${area[2] * 100}%`; m.style.height = `${area[3] * 100}%`;
}

function modoCamera() { return $('#form-camera input[name="modo"]:checked')?.value || "auto"; }

function sincronizarModo() {
  const modo = modoCamera(), marcar = modo === "dividido" && !$("#cam-quadro").hidden;
  $("#marcador").hidden = !marcar;
  $("#cam-dica").textContent = marcar ? "Arraste o quadro amarelo até a câmera do streamer. Puxe os cantos para ajustar o tamanho."
    : modo === "auto" ? "Cada corte procura a câmera sozinho." : "";
}
$$('#form-camera input[name="modo"]').forEach((r) => r.addEventListener("change", sincronizarModo));

function abrirCamera(alvo) {
  alvoCamera = alvo;
  let ajuste, src;
  if (alvo.canal) {
    const c = estado.canais.find((x) => x.id === alvo.canal);
    ajuste = c?.camera; src = `/api/canais/${alvo.canal}/quadro.jpg?t=${Date.now()}`;
    $("#cam-sub").textContent = `Vale para os próximos cortes de ${c?.nome}.`;
  } else {
    ajuste = alvo.corte.ajuste_camera; src = `/cortes/${alvo.corte.id}/quadro.jpg?v=${alvo.corte.versao || 0}`;
    if (alvo.corte.plano?.moldura) ajuste = { modo: ajuste?.modo || "auto", rect: ajuste?.rect || alvo.corte.plano.moldura };
    $("#cam-sub").textContent = "Vale só para este corte.";
  }
  area = ajuste?.rect ? [...ajuste.rect] : [0.02, 0.62, 0.26, 0.34];
  const radio = $(`#form-camera input[value="${ajuste?.modo || "auto"}"]`);
  if (radio) radio.checked = true;
  const img = $("#cam-quadro");
  img.hidden = false; $("#palco-vazio").hidden = true;
  img.onerror = () => { img.hidden = true; $("#palco-vazio").hidden = false; sincronizarModo(); };
  img.onload = () => { $("#palco").style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`; };
  img.src = src;
  posicionarMarcador(); sincronizarModo();
  $("#janela-camera").showModal();
}

(function arrastar() {
  const palco = $("#palco"), m = $("#marcador");
  let inicio = null;
  const limitar = (v, a, b) => Math.min(b, Math.max(a, v));
  m.addEventListener("pointerdown", (ev) => {
    ev.preventDefault(); m.setPointerCapture(ev.pointerId);
    inicio = { x: ev.clientX, y: ev.clientY, area: [...area], alca: ev.target.dataset.alca || null };
  });
  m.addEventListener("pointermove", (ev) => {
    if (!inicio) return;
    const r = palco.getBoundingClientRect();
    const dx = (ev.clientX - inicio.x) / r.width, dy = (ev.clientY - inicio.y) / r.height;
    let [x, y, w, h] = inicio.area;
    const MIN = 0.06;
    if (!inicio.alca) { x = limitar(x + dx, 0, 1 - w); y = limitar(y + dy, 0, 1 - h); }
    else {
      if (inicio.alca.includes("w")) { const nx = limitar(x + dx, 0, x + w - MIN); w += x - nx; x = nx; }
      if (inicio.alca.includes("e")) w = limitar(w + dx, MIN, 1 - x);
      if (inicio.alca.includes("n")) { const ny = limitar(y + dy, 0, y + h - MIN); h += y - ny; y = ny; }
      if (inicio.alca.includes("s")) h = limitar(h + dy, MIN, 1 - y);
    }
    area = [x, y, w, h]; posicionarMarcador();
  });
  const soltar = () => (inicio = null);
  m.addEventListener("pointerup", soltar); m.addEventListener("pointercancel", soltar);
  m.addEventListener("keydown", (ev) => {
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[ev.key];
    if (!d) return;
    ev.preventDefault();
    let [x, y, w, h] = area;
    if (ev.shiftKey) { w = limitar(w + d[0] * .01, .06, 1 - x); h = limitar(h + d[1] * .01, .06, 1 - y); }
    else { x = limitar(x + d[0] * .01, 0, 1 - w); y = limitar(y + d[1] * .01, 0, 1 - h); }
    area = [x, y, w, h]; posicionarMarcador();
  });
})();

$("#form-camera").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const modo = modoCamera();
  const ajuste = { modo, rect: modo === "dividido" && !$("#cam-quadro").hidden ? area.map((v) => +v.toFixed(4)) : null };
  try {
    if (alvoCamera.canal) {
      await api("POST", `/api/canais/${alvoCamera.canal}/camera`, ajuste);
      avisar("Enquadramento salvo");
    } else {
      await api("PATCH", `/api/cortes/${alvoCamera.corte.id}`, { camera: ajuste });
      acompanharRefazer(alvoCamera.corte.id);
    }
    $("#janela-camera").close();
    atualizar();
  } catch (e) { avisar(e.message); }
});

/* ---------- Ajustes ---------- */
$("#abrir-ajustes").addEventListener("click", () => {
  const f = $("#form-ajustes"), c = estado?.config;
  if (!c) return;
  f.querySelector(`input[name="sensibilidade"][value="${c.sensibilidade}"]`).checked = true;
  f.duracao_min.value = c.duracao_min; f.duracao_max.value = c.duracao_max;
  f.modelo.value = c.modelo; f.idioma.value = c.idioma; f.vocabulario.value = c.vocabulario || ""; f.melhorar_abaixo.value = String(c.melhorar_abaixo ?? 75); f.desempenho.value = c.desempenho || "auto";
  const dz = estado?.sistema?.desempenho; if (dz) $("#aj-desempenho-dica").textContent = `Este computador: ${dz.nucleos} núcleos e ${dz.memoria_gb} GB de memória. Recomendado: ${dz.recomendado === "leve" ? "leve" : "total"}. No leve, a legenda usa metade dos núcleos e a montagem roda com prioridade baixa: demora mais e esquenta menos. A gravação da live nunca fica mais lenta.`; f.corte_garantido.value = String(c.corte_garantido);
  f.montagem_auto.checked = c.montagem_auto !== false; f.montagem_cenas.value = String(c.montagem_cenas || 3); f.foco_auto.checked = c.foco_auto !== false; f.shorts_emendados.checked = c.shorts_emendados === true;
  $("#aj-erro").hidden = true;
  $("#janela-ajustes").showModal();
});
$("#form-ajustes").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  try {
    await api("POST", "/api/config", { montagem_auto: f.montagem_auto.checked, montagem_cenas: +f.montagem_cenas.value, foco_auto: f.foco_auto.checked, shorts_emendados: f.shorts_emendados.checked, sensibilidade: f.sensibilidade.value, duracao_min: +f.duracao_min.value, duracao_max: +f.duracao_max.value, modelo: f.modelo.value, idioma: f.idioma.value, vocabulario: f.vocabulario.value, melhorar_abaixo: +f.melhorar_abaixo.value, desempenho: f.desempenho.value, corte_garantido: f.corte_garantido.value === "" ? 3 : +f.corte_garantido.value });
    $("#janela-ajustes").close(); avisar("Ajustes salvos"); atualizar();
  } catch (e) { $("#aj-erro").textContent = e.message; $("#aj-erro").hidden = false; }
});

atualizar();


/* ---------- Postagem ---------- */
const NOMES_ESTADO = { fila: "Na fila", enviando: "Enviando", agendado: "Agendado no YouTube", erro: "Falhou" };
let itemAberto = null, assinaturaAgenda = "", horariosEditando = false, paginaAgenda = 1;
const selecionados = new Set();

function abrirAba(aba, rolar = true) {
  $$(".abas button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.aba === aba)));
  history.replaceState(null, "", aba === "vivo" ? location.pathname : `#${aba}`);
  if (rolar) scrollTo(0, 0);
  $("#aba-vivo").hidden = aba !== "vivo";
  $("#aba-cortes").hidden = aba !== "cortes";
  $("#aba-postagem").hidden = aba !== "postagem";
  $("#aba-longos").hidden = aba !== "longos";
  $("#aba-editor").hidden = aba !== "editor";
  $("#aba-posts").hidden = aba !== "posts";
  if (aba === "posts" && typeof abrirPosts === "function") abrirPosts();
  document.body.dataset.aba = aba;
  if (aba !== "editor" && typeof pausarEditor === "function") pausarEditor();
  if (aba === "editor" && estado && typeof renderEditor === "function") renderEditor();
  if (aba === "vivo") faixas.forEach(desenhar);
}
$$(".abas button").forEach((b) => b.addEventListener("click", () => abrirAba(b.dataset.aba)));
$("#ver-cortes").addEventListener("click", () => abrirAba("cortes"));
function abrirSub(nome) {
  $$(".subabas button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.sub === nome)));
  $$("[data-painel]").forEach((p) => (p.hidden = p.dataset.painel !== nome));
}
$$(".subabas button").forEach((b) => b.addEventListener("click", () => abrirSub(b.dataset.sub)));
(function abaInicial() {
  const pedida = new URLSearchParams(location.search).get("aba") || location.hash.slice(1);
  if (["cortes", "postagem", "longos", "editor", "posts"].includes(pedida)) abrirAba(pedida, false);
  if (new URLSearchParams(location.search).get("aba")) abrirSub("canal");
})();

function nomeDia(t) {
  const d = new Date(t * 1000), hoje = new Date(), amanha = new Date(Date.now() + 864e5);
  if (d.toDateString() === hoje.toDateString()) return "Hoje";
  if (d.toDateString() === amanha.toDateString()) return "Amanhã";
  const texto = d.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  return texto[0].toUpperCase() + texto.slice(1);
}

async function acaoItem(id, acao, aviso) {
  try { await api("POST", `/api/postagem/itens/${id}/${acao}`); if (aviso) avisar(aviso); atualizar(); }
  catch (e) { avisar(e.message); }
}

function linhaItem(item, pendentes) {
  const pendente = item.estado === "fila" || item.estado === "erro";
  const posicao = pendentes.indexOf(item.id);
  const detalhe = item.video_antigo && !item.liberado && pendente ? "Já foi enviado antes. Escolha o que fazer no aviso acima" : item.estado === "enviando" ? `Enviando ${item.progresso}%` : item.estado === "erro" ? item.erro || NOMES_ESTADO.erro : `${NOMES_ESTADO[item.estado]}, ${item.canal}`;
  const acoes = [];
  if (item.estado === "erro") acoes.push(el("button", { class: "botao", type: "button", onclick: () => acaoItem(item.id, "tentar") }, "Tentar de novo"));
  if (pendente) {
    const subir = el("button", { class: "botao fantasma", type: "button", "aria-label": `Adiantar ${item.titulo}`, onclick: () => acaoItem(item.id, "subir") }, "Subir");
    const descer = el("button", { class: "botao fantasma", type: "button", "aria-label": `Atrasar ${item.titulo}`, onclick: () => acaoItem(item.id, "descer") }, "Descer");
    subir.disabled = posicao <= 0; descer.disabled = posicao >= pendentes.length - 1;
    acoes.push(subir, descer);
  }
  if (item.video_id) acoes.push(el("a", { class: "botao fantasma", href: `https://studio.youtube.com/video/${item.video_id}/edit`, target: "_blank", rel: "noopener" }, "Abrir no Studio"));
  else if (pendente && item.video_antigo) acoes.push(el("a", { class: "botao fantasma", href: `https://studio.youtube.com/video/${item.video_antigo}/edit`, target: "_blank", rel: "noopener" }, "Ver no canal antigo"));
  const escolha = pendente ? el("input", { type: "checkbox", class: "item-marca", "aria-label": `Selecionar ${item.titulo}`, onchange: (ev) => {
    if (ev.target.checked) selecionados.add(item.id); else selecionados.delete(item.id);
    atualizarSelecao();
  } }) : el("span");
  if (pendente) escolha.checked = selecionados.has(item.id);
  return el("article", { class: "item", dados: { estado: item.estado, id: item.id } }, escolha,
    el("time", { class: "item-hora" }, horaDe(item.quando)),
    el("button", { class: "item-capa", type: "button", "aria-label": `Assistir ${item.titulo}`, onclick: () => abrirItem(item.id) },
      el("img", { src: `/cortes/${item.id}/capa.jpg?v=${item.versao || 0}`, alt: "", loading: "lazy" }), el("i", { "aria-hidden": "true" })),
    el("button", { class: "item-texto", type: "button", onclick: () => abrirItem(item.id) }, el("b", {}, item.titulo), el("span", {}, item.potencial ? `${detalhe} · potencial ${item.potencial}%` : detalhe)),
    el("div", { class: "item-acoes" }, ...acoes));
}

function renderConta(p) {
  const corpo = $("#conta-corpo"), conta = p.conta;
  const chave = JSON.stringify([conta, p.devolviveis]);
  if (corpo.dataset.chave === chave) return;
  corpo.dataset.chave = chave;
  const conectar = async (cliente) => {
    try { const r = await api("POST", "/api/postagem/conta", cliente ? { cliente } : {}); if (r.aberto) avisar("Continue no navegador que abriu"); else location.href = r.url; }
    catch (e) { avisar(e.message); }
  };
  if (conta.conectada) {
    const teste = el("button", { class: "botao", type: "button", onclick: async () => {
      teste.disabled = true; teste.textContent = "Enviando teste";
      try { await api("POST", "/api/postagem/teste"); avisar("Teste enviado como vídeo privado"); }
      catch (e) { avisar(e.message); }
      teste.disabled = false; teste.textContent = "Enviar vídeo de teste";
    } }, "Enviar vídeo de teste");
    const sair = el("button", { class: "botao fantasma", type: "button", onclick: () => confirmar(sair, "Confirmar", async () => { await api("DELETE", "/api/postagem/conta"); avisar("Canal desconectado"); atualizar(); }) }, "Desconectar");
    const blocos = [el("p", { class: "conta-nome" }, conta.canal?.nome || "Canal conectado"), el("div", { class: "conta-botoes" }, teste, sair)];
    if (p.devolviveis > 0) {
      const nome = p.devolviveis === 1 ? "o vídeo do canal antigo" : `os ${p.devolviveis} vídeos do canal antigo`;
      const voltar = el("button", { class: "botao", type: "button", onclick: () => confirmar(voltar, "Confirmar", async () => {
        try { const r = await api("POST", "/api/postagem/agendados/voltar"); avisar(r.total === 1 ? "1 vídeo voltou para a fila" : `${r.total} vídeos voltaram para a fila`); atualizar(); }
        catch (e) { avisar(e.message); }
      }) }, `Trazer ${nome} para a fila`);
      blocos.push(el("p", { class: "dica" }, "Trocou de canal? Apague esses vídeos no canal antigo antes, senão eles também saem lá."), voltar);
    }
    corpo.replaceChildren(...blocos);
    return;
  }
  const arquivo = el("input", { type: "file", accept: ".json,application/json", "aria-label": "Arquivo de credencial do Google Cloud" });
  const botao = el("button", { class: "botao principal", type: "button", onclick: async () => {
    const escolhido = arquivo.files[0];
    if (!escolhido && !conta.tem_cliente) { avisar("Escolha o arquivo de credencial baixado do Google Cloud."); return; }
    conectar(escolhido ? await escolhido.text() : null);
  } }, "Conectar canal");
  const link = (url, txt) => el("a", { href: url, target: "_blank", rel: "noopener" }, txt);
  const passo = (titulo, ...texto) => el("li", {}, el("b", {}, titulo), el("span", {}, ...texto));
  const guia = el("details", { class: "yt-guia", open: conta.tem_cliente ? undefined : "" }, el("summary", {}, "Como conectar sua conta do YouTube"),
    el("ol", {},
      passo("Crie um projeto no Google", "Entre no ", link("https://console.cloud.google.com/projectcreate", "Google Cloud"), " com a conta do seu canal, dê o nome Clipador e clique em Criar."),
      passo("Ative a API do YouTube", "Abra a ", link("https://console.cloud.google.com/apis/library/youtube.googleapis.com", "YouTube Data API v3"), " e clique em Ativar."),
      passo("Configure o acesso", "Na ", link("https://console.cloud.google.com/auth/overview", "Plataforma de autenticação"), " clique em Começar, escolha Externo e conclua. Em Público-alvo, clique em Publicar app para a conexão não expirar em 7 dias."),
      passo("Baixe a credencial", "Em ", link("https://console.cloud.google.com/auth/clients", "Clientes"), ", clique em Criar cliente, escolha App para computador e depois Baixar JSON. Não envie esse arquivo para ninguém."),
      passo("Conecte aqui", "Escolha o arquivo baixado abaixo e clique em Conectar canal. Entre com a conta do canal e permita o acesso. Se aparecer \"app não verificado\", clique em Avançado e continue."),
      passo("Ligue o envio automático", "Enquanto o YouTube não aprova a auditoria, os vídeos sobem como privados. Peça a ", link("https://support.google.com/youtube/contact/yt_api_form", "auditoria da API"), " e, depois de aprovada, marque as duas opções em Envio automático.")));
  const escolha = el("label", { class: "yt-arquivo" }, el("span", {}, conta.tem_cliente ? "Credencial salva. Se quiser, escolha outra:" : "Arquivo de credencial (.json)"), arquivo);
  corpo.replaceChildren(guia, escolha, botao);
}

function linhaHorario(valor) {
  const campo = el("input", { type: "time", value: valor, "aria-label": "Horário de postagem", oninput: () => (horariosEditando = true) });
  const linha = el("div", { class: "horario" }, campo,
    el("button", { type: "button", "aria-label": `Remover horário ${valor}`, onclick: () => { horariosEditando = true; linha.remove(); } }, "×"));
  return linha;
}

function renderPostagem() {
  const p = estado.postagem;
  $("#n-postagem").textContent = p.total_fila || "";
  renderConta(p);
  $("#post-auditoria").checked = p.config.auditoria;
  if (document.activeElement !== $("#post-potencial")) $("#post-potencial").value = String(p.config.potencial_minimo ?? 85);
  $("#post-melhores").checked = p.config.melhores_primeiro !== false;
  $("#post-fora").textContent = p.config.potencial_minimo ? (p.abaixo_minimo ? `${p.abaixo_minimo} ${p.abaixo_minimo === 1 ? "corte ficou" : "cortes ficaram"} fora da agenda por estar abaixo de ${p.config.potencial_minimo}%. Eles continuam em Cortes, e dá para liberar um a um.` : `Só entram na agenda cortes com potencial de ${p.config.potencial_minimo}% ou mais.`) : "Todos os cortes prontos entram na agenda.";
  $("#post-automatico").checked = p.config.automatico;
  $("#post-automatico").disabled = !p.config.auditoria || !p.conta.conectada;
  if (!horariosEditando) {
    const chave = p.config.horarios.join();
    if ($("#horarios").dataset.chave !== chave) {
      $("#horarios").dataset.chave = chave;
      $("#horarios").replaceChildren(...p.config.horarios.map(linhaHorario));
    }
  }
  const modoAgenda = p.config.modo || "horarios";
  $$('input[name="post-modo"]').forEach((r) => (r.checked = r.value === modoAgenda));
  ["horarios", "dia", "agora"].forEach((m) => ($(`#bloco-${m}`).hidden = m !== modoAgenda));
  if (!$("#bloco-dia").contains(document.activeElement)) {
    $("#dia-data").value = p.config.dia_unico || diaLocal(); $("#dia-data").min = diaLocal();
    $("#dia-inicio").value = p.config.janela_inicio; $("#dia-fim").value = p.config.janela_fim;
  }
  if (document.activeElement !== $("#hor-quantos")) $("#hor-quantos").value = p.config.por_horario || 1;
  const ritmo = modoAgenda === "agora" ? "Todos de uma vez" : modoAgenda === "dia" ? `Todos em ${(p.config.dia_unico || diaLocal()).split("-").reverse().slice(0, 2).join("/")}, das ${p.config.janela_inicio} às ${p.config.janela_fim}` : `${p.por_dia} por dia${p.config.por_horario > 1 ? ` (${p.config.por_horario} em cada horário)` : ""}`;
  const modo = p.config.automatico ? "Envio automático ligado" : "Postagem manual pela agenda";
  $("#agenda-resumo").textContent = `${ritmo}, ${p.total_fila} na fila, ${p.agendados} agendados. ${modo}.`;
  const aviso = $("#post-aviso");
  aviso.hidden = !p.aviso; aviso.textContent = p.aviso;
  renderPastas(p);
  const marcadas = p.pastas.filter((x) => x.ativa).length;
  $("#sub-pastas").textContent = p.pastas.length ? `${marcadas} de ${p.pastas.length}` : "";
  $("#sub-canal").hidden = p.conta.conectada;
  const pastaAgenda = $("#agenda-pasta").value;
  const itensVisiveis = pastaAgenda ? p.itens.filter((i) => i.pasta === pastaAgenda) : p.itens;
  $("#post-repetidos").hidden = !p.repetidos;
  $("#post-repetidos-texto").textContent = p.repetidos === 1 ? "1 Short da fila já foi enviado antes a outro canal. Ele não será postado até você decidir." : `${p.repetidos} Shorts da fila já foram enviados antes a outro canal. Eles não serão postados até você decidir.`;
  $("#post-conferencia").hidden = !p.conferencia.quando;
  if (p.conferencia.quando) $("#post-conferencia").textContent = `Fila conferida com o canal às ${horaDe(p.conferencia.quando)}${p.conferencia.tirados ? `. ${p.conferencia.tirados} já postados saíram da fila` : ""}.`;
  const porPagina = +$("#agenda-por-pagina").value, totalPaginas = Math.max(1, Math.ceil(itensVisiveis.length / porPagina));
  paginaAgenda = Math.min(paginaAgenda, totalPaginas);
  const inicioPagina = (paginaAgenda - 1) * porPagina, itensPagina = itensVisiveis.slice(inicioPagina, inicioPagina + porPagina);
  const sinal = JSON.stringify([pastaAgenda, paginaAgenda, porPagina, itensVisiveis.length, itensVisiveis.filter((i) => i.estado === "fila" || i.estado === "erro").map((i) => i.id), itensPagina.map((i) => [i.id, i.quando, i.estado, i.progresso, i.titulo, i.erro, i.liberado])]);
  $("#agenda-vazia").hidden = itensVisiveis.length > 0;
  if (sinal === assinaturaAgenda) return;
  assinaturaAgenda = sinal;
  const pendentes = itensVisiveis.filter((i) => i.estado === "fila" || i.estado === "erro").map((i) => i.id);
  renderPaginacao(itensVisiveis.length, inicioPagina, itensPagina.length, totalPaginas);
  const idsPendentes = new Set(p.itens.filter((i) => i.estado === "fila" || i.estado === "erro").map((i) => i.id));
  [...selecionados].forEach((id) => { if (!idsPendentes.has(id)) selecionados.delete(id); });
  $("#agenda-selecao").hidden = !idsPendentes.size;
  const dias = new Map();
  itensPagina.forEach((i) => { const d = nomeDia(i.quando); if (!dias.has(d)) dias.set(d, []); dias.get(d).push(i); });
  $("#agenda-dias").replaceChildren(...[...dias].map(([dia, itens]) =>
    el("section", { class: "dia" }, el("h2", {}, dia), ...itens.map((i) => linhaItem(i, pendentes)))));
  atualizarSelecao();
}

async function abrirItem(id) {
  const item = await api("GET", `/api/postagem/itens/${id}`).catch((e) => { avisar(e.message); return null; });
  if (!item) return;
  itemAberto = item;
  const pendente = item.estado === "fila" || item.estado === "erro";
  const duracaoItem = estado.postagem.itens.find((i) => i.id === id)?.duracao;
  $("#it-quando").textContent = `${nomeDia(item.quando)} às ${horaDe(item.quando)}, ${relogio(duracaoItem)} de vídeo`;
  $("#it-texto").value = item.titulo; $("#it-desc").value = item.descricao; $("#it-conta").textContent = item.titulo.length;
  $("#it-texto").readOnly = $("#it-desc").readOnly = !pendente;
  $("#it-baixar").href = `/cortes/${id}/corte.mp4?baixar=1`;
  const resumoItem = estado.postagem.itens.find((i) => i.id === id), versao = resumoItem?.versao || 0;
  $("#it-player").poster = `/cortes/${id}/capa.jpg?v=${versao}`; $("#it-player").src = `/cortes/${id}/corte.mp4?v=${versao}`;
  ["#it-salvar", "#it-agendado", "#it-remover", "#it-apagar"].forEach((s) => ($(s).hidden = !pendente));
  $("#it-voltar").hidden = item.estado !== "agendado" || item.canal_envio === estado.postagem.conta.canal?.id;
  $("#it-erro").hidden = true;
  $("#janela-item").showModal();
}
$("#it-texto").addEventListener("input", (e) => ($("#it-conta").textContent = e.target.value.length));
async function copiar(texto, aviso) {
  try { await navigator.clipboard.writeText(texto); avisar(aviso); } catch { avisar("Selecione o texto e copie manualmente"); }
}
$("#it-copiar-titulo").addEventListener("click", () => copiar($("#it-texto").value, "Título copiado"));
$("#it-copiar-desc").addEventListener("click", () => copiar($("#it-desc").value, "Descrição copiada"));
$("#form-item").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await api("PATCH", `/api/postagem/itens/${itemAberto.id}`, { titulo: $("#it-texto").value, descricao: $("#it-desc").value });
    $("#janela-item").close(); avisar("Textos salvos"); atualizar();
  } catch (e) { $("#it-erro").textContent = e.message; $("#it-erro").hidden = false; }
});
$("#it-agendado").addEventListener("click", async () => { await acaoItem(itemAberto.id, "agendado", "Marcado como agendado"); $("#janela-item").close(); });
$("#it-voltar").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Confirmar", async () => { await acaoItem(itemAberto.id, "voltar", "Vídeo voltou para a fila"); $("#janela-item").close(); }));
$("#it-remover").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Confirmar", async () => { await acaoItem(itemAberto.id, "remover", "Vídeo tirado da fila"); $("#janela-item").close(); }));

async function salvarPostagem(dados, aviso) {
  try { await api("POST", "/api/postagem/config", dados); if (aviso) avisar(aviso); }
  catch (e) { avisar(e.message); }
  atualizar();
}
$("#post-potencial").addEventListener("change", (e) => salvarPostagem({ potencial_minimo: +e.target.value }, +e.target.value ? `Agenda só com potencial de ${e.target.value}% ou mais` : "Todos os cortes entram na agenda"));
$("#post-melhores").addEventListener("change", (e) => salvarPostagem({ melhores_primeiro: e.target.checked }));
$("#post-auditoria").addEventListener("change", (e) => salvarPostagem({ auditoria: e.target.checked }));
$("#post-automatico").addEventListener("change", (e) => salvarPostagem({ automatico: e.target.checked }, e.target.checked ? "Envio automático ligado" : "Envio automático desligado"));
function diaLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const dadosDoDia = () => ({ modo: "dia", dia_unico: $("#dia-data").value || diaLocal(), janela_inicio: $("#dia-inicio").value, janela_fim: $("#dia-fim").value });
$$('input[name="post-modo"]').forEach((r) => r.addEventListener("change", () => {
  if (r.value === "dia") salvarPostagem(dadosDoDia(), "Todos os vídeos foram para um único dia");
  else salvarPostagem({ modo: r.value }, r.value === "agora" ? "Todos os vídeos vão sair de uma vez" : "Agenda voltou para os horários");
}));
$("#bloco-dia").addEventListener("submit", (ev) => { ev.preventDefault(); document.activeElement?.blur(); salvarPostagem(dadosDoDia(), "Dia da postagem salvo"); });
$("#hor-mais").addEventListener("click", () => {
  horariosEditando = true; $("#horarios").append(linhaHorario("12:00")); $("#horarios").scrollTop = $("#horarios").scrollHeight;
});
$("#hor-rapido").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const minutos = (t) => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };
  const inicio = minutos($("#hor-inicio").value), fim = minutos($("#hor-fim").value), passo = Number($("#hor-intervalo").value);
  if (fim < inicio) { avisar("O horário final precisa ser depois do inicial."); return; }
  const horarios = [];
  for (let t = inicio; t <= fim; t += passo) horarios.push(`${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`);
  horariosEditando = false; $("#horarios").dataset.chave = "";
  const por_horario = Number($("#hor-quantos").value);
  await salvarPostagem({ horarios, por_horario }, por_horario > 1 ? `${horarios.length} horários com ${por_horario} vídeos em cada` : `${horarios.length} horários por dia salvos`);
});
$("#hor-salvar").addEventListener("click", async () => {
  const horarios = $$("#horarios input").map((i) => i.value).filter(Boolean);
  horariosEditando = false; $("#horarios").dataset.chave = "";
  await salvarPostagem({ horarios, por_horario: Number($("#hor-quantos").value) }, "Horários salvos");
});
if (new URLSearchParams(location.search).get("aba") === "postagem") { abrirAba("postagem"); history.replaceState(null, "", "/"); }


/* ---------- Vídeos longos ---------- */
const ATIVOS_GRAVADA = new Set(["fila", "lendo", "baixando", "chat", "analisando", "cortando"]);
let assinaturaLongos = "", assinaturaGravadas = "", assinaturaSessoes = "", longoAberto = null;

function barra(valor) {
  return el("div", { class: "barra", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(valor || 0) },
    el("span", { style: `width:${valor || 0}%` }));
}

function detalheGravada(g) {
  if (g.status === "erro") return g.erro || "Não foi possível analisar esta gravação.";
  if (g.status === "cancelada") return "Análise cancelada.";
  const partes = [];
  if (g.duracao) partes.push(`${relogio(g.duracao)} de live`);
  if (g.chat === true) partes.push(`${g.mensagens.toLocaleString("pt-BR")} mensagens do chat`);
  if (g.chat === false) partes.push("sem replay do chat, usando voz, rosto e jogo");
  if (g.status === "pronto") partes.push(`${g.feitos} cortes prontos`);
  return partes.join(", ") || "Preparando a análise.";
}

function linhaGravada(g) {
  const ativo = ATIVOS_GRAVADA.has(g.status);
  const acao = el("button", { class: "botao fantasma", type: "button", onclick: () => confirmar(acao, "Confirmar", async () => {
    await api(ativo ? "POST" : "DELETE", ativo ? `/api/gravadas/${g.id}/cancelar` : `/api/gravadas/${g.id}`);
    avisar(ativo ? "Cancelando a análise" : "Análise removida"); atualizar();
  }) }, ativo ? "Cancelar" : "Remover");
  return el("li", { class: "trabalho", dados: { status: g.status } },
    el("div", { class: "trabalho-texto" }, el("b", { title: g.titulo }, g.titulo), el("span", {}, ativo ? `${g.etapa}. ${detalheGravada(g)}` : detalheGravada(g)), g.intencao?.resumo ? el("span", { class: "gr-foco" }, `Foco: ${g.intencao.resumo}`) : null, ativo ? barra(g.progresso) : null), acao);
}

const POR_PAGINA_LONGOS = 12;
let paginaLongos = 1, filtroLongos = "todos";
const enviadoLongo = (v) => v.envio?.estado === "enviado";
function seloLongo(v) {
  const e = v.envio?.estado;
  if (e === "enviado") return el("span", { class: "lo-selo", dados: { tipo: "ok" } }, "No YouTube");
  if (e === "enviando") return el("span", { class: "lo-selo", dados: { tipo: "vai" } }, `Enviando ${v.envio.progresso || 0}%`);
  if (e === "erro") return el("span", { class: "lo-selo", dados: { tipo: "erro" } }, "Falha no envio");
  return el("span", { class: "lo-selo" }, "Não enviado");
}
function cartaoLongo(v) {
  const pronto = v.status === "pronto";
  const capa = el("div", { class: "longo-capa" });
  if (pronto) capa.append(el("img", { src: `/longos/${v.id}/capa.jpg?v=${v.versao}`, alt: "", loading: "lazy" }), el("span", { class: "poster-dur" }, relogio(v.duracao)), seloLongo(v));
  else if (v.status === "erro") capa.append(el("div", { class: "falhou" }, v.erro || "Não foi possível editar este vídeo."));
  else capa.append(el("div", { class: "longo-editando" }, el("span", { class: "giro", "aria-hidden": "true" }), el("b", {}, v.etapa), barra(v.progresso), el("small", {}, `${v.progresso}%`)));
  const n = (v.capitulos || []).length, detalhes = pronto ? [`${n} ${n === 1 ? "capítulo" : "capítulos"}`, v.parte ? `parte ${v.parte}` : null, haQuanto(v.criado)].filter(Boolean).join(", ") : haQuanto(v.criado);
  const conteudo = [capa, el("h3", { title: v.titulo }, v.titulo), el("p", { class: "lo-canal" }, v.canal || "Vídeo enviado"), el("p", {}, detalhes)];
  if (pronto || v.status === "erro") return el("button", { class: "longo", type: "button", onclick: () => abrirLongo(v.id) }, ...conteudo);
  return el("article", { class: "longo" }, ...conteudo);
}

function renderLongos() {
  const longos = estado.longos, gravadas = estado.gravadas, sessoes = estado.sessoes;
  const emEdicao = longos.filter((v) => v.status !== "pronto" && v.status !== "erro").length;
  $("#n-longos").textContent = emEdicao || longos.length || "";
  renderAutoLongo();
  const chaveSessoes = JSON.stringify(sessoes.map((s) => [s.id, s.cortes]));
  if (chaveSessoes !== assinaturaSessoes) {
    assinaturaSessoes = chaveSessoes;
    const atual = $("#lg-sessao").value;
    $("#lg-sessao").replaceChildren(...(sessoes.length ? sessoes.map((s) => el("option", { value: s.id }, `${s.canal}: ${s.cortes} cortes, ${relogio(s.duracao)} de vídeo`)) : [el("option", { value: "" }, "Nenhuma live com cortes prontos")]));
    if (sessoes.some((s) => s.id === atual)) $("#lg-sessao").value = atual;
    $("#lg-criar").disabled = !sessoes.length;
  }
  const chaveGravadas = JSON.stringify(gravadas.map((g) => [g.id, g.status, g.etapa, g.progresso, g.mensagens, g.feitos, g.erro]));
  if (chaveGravadas !== assinaturaGravadas) {
    assinaturaGravadas = chaveGravadas;
    $("#sec-gravadas").hidden = !gravadas.length;
    $("#lista-gravadas").replaceChildren(...gravadas.map(linhaGravada));
  }
  const minuto = Math.floor(estado.agora / 60);
  const busca = $("#lo-busca").value.trim().toLowerCase();
  const chave = JSON.stringify([minuto, filtroLongos, busca, paginaLongos, longos.map((v) => [v.id, v.status, v.etapa, v.progresso, v.titulo, v.versao, v.envio?.estado, v.envio?.progresso])]);
  if (chave !== assinaturaLongos) {
    assinaturaLongos = chave;
    const passa = { todos: () => true, prontos: (v) => v.status === "pronto" && !enviadoLongo(v), enviados: enviadoLongo, editando: (v) => v.status !== "pronto" && v.status !== "erro" }[filtroLongos];
    const vistos = longos.filter((v) => passa(v) && (!busca || `${v.titulo} ${v.canal}`.toLowerCase().includes(busca)));
    const total = Math.max(1, Math.ceil(vistos.length / POR_PAGINA_LONGOS));
    if (paginaLongos > total) paginaLongos = total;
    const prontos = longos.filter((v) => v.status === "pronto"), tempo = prontos.reduce((s, v) => s + (v.duracao || 0), 0);
    $("#lo-total").textContent = longos.length ? `${longos.length} ${longos.length === 1 ? "vídeo" : "vídeos"}, ${relogio(tempo)} no total` : "";
    $("#lo-filtros").hidden = !longos.length; $(".lo-barra .filtro-pasta").hidden = !longos.length;
    const vazio = $("#longos-vazio"); vazio.hidden = vistos.length > 0;
    vazio.textContent = longos.length ? "Nenhum vídeo com esse filtro." : "Crie o primeiro vídeo com os cortes de uma live ou analise uma gravação.";
    $("#grade-longos").replaceChildren(...vistos.slice((paginaLongos - 1) * POR_PAGINA_LONGOS, paginaLongos * POR_PAGINA_LONGOS).map(cartaoLongo));
    const nav = $("#lo-paginacao"), ini = (paginaLongos - 1) * POR_PAGINA_LONGOS;
    $("[data-contagem]", nav).textContent = `${ini + 1} a ${Math.min(vistos.length, ini + POR_PAGINA_LONGOS)} de ${vistos.length}`;
    montarPaginas(nav, paginaLongos, total, (p) => { paginaLongos = p; renderLongos(); $("#videos-titulo").scrollIntoView({ behavior: "smooth", block: "start" }); });
  }
  if (longoAberto) {
    const v = longos.find((x) => x.id === longoAberto.id);
    if (v) { longoAberto = v; textoEnvio(v); }
  }
}

$("#lo-filtros").addEventListener("click", (ev) => { const b = ev.target.closest("button[data-f]"); if (!b) return; filtroLongos = b.dataset.f; paginaLongos = 1; $$("#lo-filtros button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); renderLongos(); });
$("#lo-busca").addEventListener("input", () => { paginaLongos = 1; renderLongos(); });
function textoEnvio(v) {
  const e = v.envio, alvo = $("#jl-envio");
  $("#jl-enviar").disabled = e?.estado === "enviando";
  if (e?.estado === "enviando") alvo.textContent = `Enviando ${e.progresso || 0}%`;
  else if (e?.estado === "enviado") alvo.textContent = e.capa === false ? "Vídeo enviado. Troque a miniatura no YouTube Studio." : "Vídeo enviado ao YouTube.";
  else if (e?.estado === "erro") alvo.textContent = e.erro;
  else alvo.textContent = "Deixe em branco para enviar como privado.";
}

function abrirLongo(id) {
  const v = estado.longos.find((x) => x.id === id);
  if (!v) return;
  longoAberto = v;
  const pronto = v.status === "pronto";
  $("#jl-titulo").textContent = pronto ? "Vídeo longo" : "Vídeo com problema";
  $("#jl-meta").textContent = pronto ? `${relogio(v.duracao)} de vídeo, ${v.capitulos.length} capítulos${v.aviso ? `. ${v.aviso}` : ""}` : v.erro || "";
  $("#jl-nome").value = v.titulo; $("#jl-desc").value = v.descricao; $("#jl-erro").hidden = true; $("#jl-quando").value = "";
  $$(".jl-video, .jl-textos, #jl-baixar, #jl-baixar-capa, #jl-enviar, #jl-timeline, #form-jl button[type=submit]").forEach((n) => (n.hidden = !pronto));
  if (pronto) {
    const player = $("#jl-player");
    player.src = `/longos/${id}/video.mp4?v=${v.versao}`; player.poster = `/longos/${id}/capa.jpg?v=${v.versao}`;
    $("#jl-capa").src = `/longos/${id}/capa.jpg?v=${v.versao}`;
    $("#jl-baixar").href = `/longos/${id}/video.mp4?baixar=1`; $("#jl-baixar-capa").href = `/longos/${id}/capa.jpg?baixar=1`;
    $("#jl-capitulos").replaceChildren(...v.capitulos.map((c) => el("li", {}, el("button", { type: "button", onclick: () => { player.currentTime = c.t; player.play(); } }, el("time", {}, relogio(c.t)), c.titulo))));
    textoEnvio(v);
  }
  $("#janela-longo").showModal();
}

$("#janela-longo").addEventListener("close", () => { const p = $("#jl-player"); p.pause(); p.removeAttribute("src"); p.load(); longoAberto = null; });
$("#jl-copiar-titulo").addEventListener("click", () => copiar($("#jl-nome").value, "Título copiado"));
$("#jl-copiar-desc").addEventListener("click", () => copiar($("#jl-desc").value, "Descrição copiada"));
$("#form-jl").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try { await api("PATCH", `/api/longos/${longoAberto.id}`, { titulo: $("#jl-nome").value, descricao: $("#jl-desc").value }); avisar("Textos salvos"); atualizar(); }
  catch (e) { $("#jl-erro").textContent = e.message; $("#jl-erro").hidden = false; }
});
$("#jl-enviar").addEventListener("click", async () => {
  $("#jl-erro").hidden = true;
  const quando = $("#jl-quando").value ? new Date($("#jl-quando").value).getTime() / 1000 : null;
  try {
    await api("PATCH", `/api/longos/${longoAberto.id}`, { titulo: $("#jl-nome").value, descricao: $("#jl-desc").value });
    await api("POST", `/api/longos/${longoAberto.id}/enviar`, { quando }); avisar("Envio iniciado"); atualizar();
  } catch (e) { $("#jl-erro").textContent = e.message; $("#jl-erro").hidden = false; }
});
$("#jl-excluir").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Confirmar exclusão", async () => {
  await api("DELETE", `/api/longos/${longoAberto.id}`); $("#janela-longo").close(); avisar("Vídeo excluído"); atualizar();
}));
$("#form-longo").addEventListener("submit", async (ev) => {
  ev.preventDefault(); $("#lg-erro").hidden = true;
  try { await api("POST", "/api/longos", { sessao: $("#lg-sessao").value, minutos: +$("#lg-minutos").value }); avisar("Vídeo longo na fila de edição"); atualizar(); }
  catch (e) { $("#lg-erro").textContent = e.message; $("#lg-erro").hidden = false; }
});
/* ---------- Vídeo enviado do computador ---------- */
let videoEscolhido = null, envioAtual = null;
const tamanhoTexto = (b) => b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(1).replace(".", ",")} GB` : `${Math.max(1, Math.round(b / 1024 ** 2))} MB`;
function erroEnvio(texto) { $("#gr-erro").textContent = texto; $("#gr-erro").hidden = !texto; }
function mostrarVideo(arquivo) {
  videoEscolhido = arquivo; const tem = Boolean(arquivo);
  $("#gr-zona").hidden = tem; $("#gr-bloco-link").hidden = tem; $("#gr-escolhido").hidden = !tem; $("#gr-barra").hidden = true; $("#gr-tirar").textContent = "Trocar vídeo";
  $("#gr-qualidade").disabled = tem;
  if (tem) { $("#gr-nome").textContent = arquivo.name; $("#gr-info").textContent = tamanhoTexto(arquivo.size); $("#gr-link").value = ""; } else $("#gr-arquivo").value = "";
}
function escolherVideo(arquivo) { erroEnvio(""); if (arquivo) mostrarVideo(arquivo); }
$("#gr-zona").addEventListener("click", () => $("#gr-arquivo").click());
$("#ir-envio").addEventListener("click", () => { abrirAba("longos"); $("#form-gravada").scrollIntoView({ block: "center" }); $("#gr-arquivo").click(); });
$("#gr-arquivo").addEventListener("change", (ev) => escolherVideo(ev.target.files[0]));
$("#gr-tirar").addEventListener("click", () => { if (envioAtual) envioAtual.abort(); else mostrarVideo(null); });
for (const tipo of ["dragenter", "dragover"]) $("#gr-zona").addEventListener(tipo, (ev) => { ev.preventDefault(); $("#gr-zona").dataset.sobre = "true"; });
for (const tipo of ["dragleave", "drop"]) $("#gr-zona").addEventListener(tipo, () => { delete $("#gr-zona").dataset.sobre; });
$("#gr-zona").addEventListener("drop", (ev) => { ev.preventDefault(); escolherVideo(ev.dataTransfer.files[0]); });
/* Soltar um arquivo fora da área não pode trocar a tela do programa. */
for (const tipo of ["dragover", "drop"]) window.addEventListener(tipo, (ev) => { if (ev.dataTransfer?.types?.includes("Files")) ev.preventDefault(); });
function enviarVideo(arquivo) {
  return new Promise((ok, falha) => {
    const x = new XMLHttpRequest(); envioAtual = x;
    x.open("POST", `/api/gravadas/envio?nome=${encodeURIComponent(arquivo.name)}`);
    x.upload.onprogress = (ev) => { if (!ev.lengthComputable) return; const p = Math.round(ev.loaded / ev.total * 100); $("#gr-barra-v").style.width = `${p}%`; $("#gr-info").textContent = p < 100 ? `Enviando ${p}% de ${tamanhoTexto(ev.total)}` : "Conferindo o vídeo"; };
    x.onload = () => { let d = {}; try { d = JSON.parse(x.responseText); } catch {} x.status < 300 ? ok(d) : falha(new Error(d.erro || "Não foi possível enviar o vídeo.")); };
    x.onerror = () => falha(new Error("O envio foi interrompido. Tente de novo.")); x.onabort = () => falha(new Error(""));
    x.send(arquivo);
  }).finally(() => { envioAtual = null; });
}
const pedidoGravada = () => ({ intencoes: $$("#gr-intencoes input:checked").map((c) => c.value), pedido: $("#gr-pedido").value.trim() });
$("#form-gravada").addEventListener("submit", async (ev) => {
  ev.preventDefault(); erroEnvio("");
  if (videoEscolhido) {
    const b = $("#gr-enviar"); b.disabled = true; $("#gr-barra").hidden = false; $("#gr-barra-v").style.width = "0%"; $("#gr-tirar").textContent = "Cancelar envio";
    try {
      await api("POST", "/api/gravadas/envio/conferir", { nome: videoEscolhido.name, tamanho: videoEscolhido.size });
      const { envio } = await enviarVideo(videoEscolhido);
      await api("POST", "/api/gravadas", { ...pedidoGravada(), envio, momentos: +$("#gr-momentos").value, qualidade: 1080, minutos: +$("#gr-minutos").value, longo: $("#gr-longo").checked, programar: $("#gr-programar").checked });
      mostrarVideo(null); avisar("Vídeo enviado. A análise começou"); atualizar();
    } catch (e) { $("#gr-barra").hidden = true; $("#gr-tirar").textContent = "Trocar vídeo"; $("#gr-info").textContent = tamanhoTexto(videoEscolhido.size); erroEnvio(e.message); }
    b.disabled = false; return;
  }
  if (!$("#gr-link").value.trim()) { erroEnvio("Escolha um vídeo ou cole o link da gravação."); return; }
  try {
    await api("POST", "/api/gravadas", { ...pedidoGravada(), link: $("#gr-link").value, momentos: +$("#gr-momentos").value, qualidade: +$("#gr-qualidade").value, minutos: +$("#gr-minutos").value, longo: $("#gr-longo").checked, programar: $("#gr-programar").checked });
    $("#gr-link").value = ""; avisar("Análise iniciada"); atualizar();
  } catch (e) { $("#gr-erro").textContent = e.message; $("#gr-erro").hidden = false; }
});


/* ---------- Vídeo longo durante a live ---------- */
function renderAutoLongo() {
  const a = estado.longos_auto, ativo = $("#auto-longo-ativo"), minutos = $("#auto-longo-minutos");
  if (document.activeElement !== ativo) ativo.checked = a.ativo;
  if (document.activeElement !== minutos) minutos.value = String(a.minutos);
  const live = a.lives[0], barraAuto = $("#auto-longo-barra");
  barraAuto.hidden = !(a.ativo && live);
  if (!a.ativo) $("#auto-longo-status").textContent = "Desligado. Os vídeos longos só são criados quando você pedir.";
  else if (!live) $("#auto-longo-status").textContent = "Quando uma live estiver no ar, as partes são criadas aqui. Nada é postado sozinho.";
  else {
    const pct = Math.min(100, Math.round(live.acumulado / live.alvo * 100));
    barraAuto.firstElementChild.style.width = `${pct}%`;
    $("#auto-longo-status").textContent = `${live.canal}: parte ${live.parte} com ${relogio(live.acumulado)} de ${relogio(live.alvo)} em cortes. Nada é postado sozinho.`;
  }
}
async function salvarAutoLongo() {
  try { await api("POST", "/api/longos/auto", { ativo: $("#auto-longo-ativo").checked, minutos: +$("#auto-longo-minutos").value }); avisar("Criação automática salva"); atualizar(); }
  catch (e) { avisar(e.message); }
}
$("#auto-longo-ativo").addEventListener("change", salvarAutoLongo);
$("#auto-longo-minutos").addEventListener("change", salvarAutoLongo);

/* ---------- Estilo do vídeo ---------- */
const MODELOS_LEGENDA = [["react", "React", "1 a 3 palavras, amarelas, na divisão da tela"], ["destaque", "Destaque", "Palavra falada colorida"], ["caixa", "Caixa", "Palavra dentro de um bloco"], ["palavra", "Palavra", "Uma palavra por vez, sem maiúsculas"], ["impacto", "Impacto", "Uma palavra grande por vez"], ["neon", "Neon", "Texto com brilho"], ["faixa", "Faixa", "Fundo escuro atrás do texto"], ["classica", "Clássica", "Frase limpa, sem efeito"], ["karaoke", "Karaokê", "As palavras já faladas mudam de cor"], ["hormozi", "Hormozi", "Anton grande, primeira palavra em vermelho"]];
const MODELOS_GANCHO = [["faixa", "Faixa colorida", "Bloco na cor de destaque"], ["preto", "Faixa preta", "Fundo preto e texto colorido"], ["alerta", "Alerta", "Vermelho com texto branco"], ["branco", "Etiqueta branca", "Bloco branco inclinado"], ["contorno", "Contorno", "Letras grandes sem fundo"], ["neon", "Neon", "Letras com brilho"], ["impacto", "Impacto", "Anton com contorno grosso"], ["quadrinho", "Quadrinho", "Bangers inclinado, estilo HQ"], ["manchete", "Manchete", "Bebas Neue em faixa vermelha"], ["gamer", "Gamer", "Russo One com moldura"], ["desenho", "Desenho", "Luckiest Guy com contorno colorido"], ["minimal", "Minimalista", "Limpo, sem fundo"], ["sombra3d", "Sombra 3D", "Sombra dura na cor de destaque"], ["marcador", "Caneta", "Escrito à mão em etiqueta"], ["nenhum", "Sem título", "Não mostra título no vídeo"]];
const CORES_ESTILO = [["amarelo", "#ffc933", "Amarelo"], ["verde", "#39ff88", "Verde"], ["vermelho", "#ff4b5c", "Vermelho"], ["azul", "#38bdf8", "Azul"], ["rosa", "#ff5fcf", "Rosa"], ["laranja", "#ff8a1f", "Laranja"], ["branco", "#ffffff", "Branco"]];
let tempoPrevia = null;

/* Mesmos modelos de nucleo/modelos_legenda.py (e de MODELOS_LEGENDA no editor). */
const MODELOS_LEGENDA_EDITOR = [["viral_amarelo", "Viral amarelo", "Anton branca, palavra falada em amarelo"], ["caixa_verde", "Caixa verde", "Palavra falada dentro de um bloco verde"], ["uma_palavra", "Uma palavra", "Uma palavra por vez, grande"], ["desenho", "Desenho", "Letra de desenho animado, amarela"], ["quadrinho", "Quadrinho", "Balão amarelo de história em quadrinhos"], ["gamer", "Gamer", "Letra de jogo com brilho azul"], ["neon_rosa", "Neon rosa", "Letreiro rosa brilhante"], ["cinema", "Cinema", "Bebas Neue espaçada, sem destaque"], ["terror", "Terror", "Letra de filme de terror, vermelha"], ["faixa_preta", "Faixa preta", "Frase numa faixa preta arredondada"], ["pincel", "Pincel", "Escrita de pincel, palavras fortes em verde"], ["arcade", "Arcade", "Letra de videogame antigo"], ["karaoke_pop", "Karaokê pop", "As palavras já faladas ficam amarelas"], ["karaoke_caixa", "Karaokê caixa", "Palavra falada num bloco verde, letra Inter"], ["alternado", "Alternado", "Uma palavra branca, outra vermelha"], ["frase_em_bloco", "Frase em bloco", "Frase inteira num bloco amarelo"], ["sublinhado", "Sublinhado", "Frase limpa e sublinhada"], ["volumoso", "Volumoso", "Primeira palavra bem maior, com sombra dura"], ["retro_3d", "Retrô 3D", "Letra Bungee com relevo roxo"], ["sem_pontuacao", "Sem pontuação", "Poppins, sem vírgulas nem pontos"]];
const opcaoEstilo = (nome, [valor, titulo, ajuda]) => el("label", { class: "es-opcao" }, el("input", { type: "radio", name: nome, value: valor }), el("span", {}, el("i", { class: "es-amostra", "aria-hidden": "true", dados: { v: valor } }), el("b", {}, titulo), el("small", {}, ajuda)));
const fontesAmostra = new Set();
function fonteAmostra(id) { if (!fontesAmostra.has(id)) { fontesAmostra.add(id); new FontFace(`am-${id}`, `url("/fontes/${id}.ttf")`).load().then((f) => document.fonts.add(f)).catch(() => {}); } return `"am-${id}", "Instrument Sans", sans-serif`; }
function pintarAmostra(n, e, palavras) {
  const d = (txt, cor) => el("em", { style: `color:${cor}` }, txt), cx = e.destaque_caixa;
  const marcada = (k) => { const m = e.destaque, u = palavras.length - 1; if (!m || m === "nenhum") return false; if (m === "primeira") return k === 0; if (m === "falado") return k < u; if (m === "alternadas") return k % 2 === 1; return k === u; };
  n.replaceChildren(...palavras.map((p, k) => marcada(k) ? (cx ? el("em", { style: `background:${e.cor_destaque};color:#141414;padding:0 .2em;border-radius:.15em` }, p) : d(k < palavras.length - 1 ? `${p} ` : p, e.cor_destaque || e.cor)) : document.createTextNode(`${p} `)));
  Object.assign(n.style, { fontFamily: fonteAmostra(e.fonte || "Poppins-Bold"), color: e.cor, textTransform: e.maiusculas === false ? "none" : "uppercase", background: e.fundo ? e.fundo_cor : "", padding: e.fundo ? ".1em .4em" : "",
    WebkitTextStroke: e.contorno ? `${Math.min(3, e.contorno / 4)}px ${e.contorno_cor || "#000"}` : "", textShadow: e.sombra ? `${e.sombra_x ? 2 : 0}px ${Math.min(3, e.sombra_y ?? 2)}px ${e.sombra_blur ? Math.min(8, e.sombra_blur / 2) : 0}px ${e.sombra_cor || "#000"}` : "",
    outline: e.borda ? `2px solid ${e.borda_cor}` : "", transform: e.rot ? `rotate(${e.rot}deg)` : "" });
}
async function amostrasEstilo() {
  const cor = $('#form-estilo input[name="es-cor"]:checked')?.value || "amarelo";
  try { const r = await api("GET", `/api/estilo/amostras?cor=${cor}`);
    if (r.fontes && $("#es-fonte-legenda").options.length < 2) ["#es-fonte-legenda", "#es-fonte-titulo"].forEach((q) => { const s = $(q), v = s.dataset.valor || ""; s.append(...r.fontes.map(([id, nome]) => el("option", { value: id }, nome))); s.value = v; mostrarFonte(s); });
    $$("#es-legendas .es-amostra, #es-legendas-editor .es-amostra").forEach((n) => r.legendas[n.dataset.v] && pintarAmostra(n, r.legendas[n.dataset.v], r.legendas[n.dataset.v].palavra_a_palavra ? ["Olha"] : ["Olha", "isso"]));
    $$("#es-ganchos .es-amostra").forEach((n) => { if (r.titulos[n.dataset.v]) pintarAmostra(n, r.titulos[n.dataset.v], ["Título"]); else n.hidden = true; });
  } catch {}
}
$("#es-legendas").append(...MODELOS_LEGENDA.map((m) => opcaoEstilo("es-legenda", m)));
$("#es-legendas-editor").append(...MODELOS_LEGENDA_EDITOR.map((m) => opcaoEstilo("es-legenda", m)));
function mostrarFonte(sel) { const a = $(`#${sel.id}-amostra`); a.style.fontFamily = sel.value ? fonteAmostra(sel.value) : ""; a.hidden = !sel.value; }
["#es-fonte-legenda", "#es-fonte-titulo"].forEach((q) => $(q).addEventListener("change", (e) => mostrarFonte(e.target)));
$("#es-ganchos").append(...MODELOS_GANCHO.map((m) => opcaoEstilo("es-gancho", m)));
$("#es-cores").addEventListener("change", amostrasEstilo);
$("#es-cores").append(...CORES_ESTILO.map(([valor, cor, nome]) => el("label", { class: "es-cor", title: nome }, el("input", { type: "radio", name: "es-cor", value: valor, "aria-label": nome }), el("span", { style: `background:${cor}` }))));
$("#ed-estilo-legenda").append(el("option", { value: "" }, "Estilo padrão"), ...[...MODELOS_LEGENDA, ...MODELOS_LEGENDA_EDITOR].map(([v, t]) => el("option", { value: v }, t)));
$("#ed-estilo-gancho").append(el("option", { value: "" }, "Estilo padrão"), ...MODELOS_GANCHO.map(([v, t]) => el("option", { value: v }, t)));

function estiloEscolhido() {
  const marcado = (nome) => $(`#form-estilo input[name="${nome}"]:checked`)?.value;
  return { legenda: marcado("es-legenda"), gancho: marcado("es-gancho"), cor: marcado("es-cor"), tamanho: $("#es-tamanho").value, tempo_gancho: +$("#es-tempo").value, filtro: $("#es-filtro").value, sons_auto: $("#es-sons").checked,
    barra_progresso: $("#es-barra").checked, abertura: $("#es-abertura").checked, fonte_legenda: $("#es-fonte-legenda").value, fonte_titulo: $("#es-fonte-titulo").value, arroba: $("#es-arroba").value.trim(), encerramento: $("#es-encerramento").checked,
    texto_fixo: $("#es-fixo").value.trim(), fixo_lugar: $("#es-fixo-lugar").value, fixo_tempo: $("#es-fixo-tempo").value, fixo_cor: $("#es-fixo-cor").value, fixo_tamanho: $("#es-fixo-tamanho").value, ...posicoesEstilo };
}
function atualizarPrevia() {
  clearTimeout(tempoPrevia);
  tempoPrevia = setTimeout(() => {
    const q = new URLSearchParams(estiloEscolhido()).toString();
    $("#es-previa-v").src = `/api/estilo/previa.jpg?${q}&formato=v`;
    $("#es-previa-h").src = `/api/estilo/previa.jpg?${q}&formato=h`;
  }, 180);
}
$("#abrir-estilo").addEventListener("click", () => {
  const e = estado?.config?.estilo;
  if (!e) return;
  [["es-legenda", e.legenda], ["es-gancho", e.gancho], ["es-cor", e.cor]].forEach(([n, v]) => { const r = $(`#form-estilo input[name="${n}"][value="${v}"]`); if (r) r.checked = true; });
  $("#es-filtro").value = e.filtro || "nenhum"; $("#es-sons").checked = e.sons_auto !== false;
  $("#es-barra").checked = e.barra_progresso === true; $("#es-abertura").checked = e.abertura !== false;
  [["#es-fonte-legenda", e.fonte_legenda], ["#es-fonte-titulo", e.fonte_titulo]].forEach(([q, v]) => { const s = $(q); s.dataset.valor = v || ""; s.value = v || ""; mostrarFonte(s); });
  $("#es-arroba").value = e.arroba || ""; $("#es-encerramento").checked = e.encerramento !== false;
  $("#es-fixo").value = e.texto_fixo || ""; $("#es-fixo-lugar").value = e.fixo_lugar || "cima"; $("#es-fixo-tempo").value = e.fixo_tempo || "todo"; $("#es-fixo-cor").value = e.fixo_cor || "branco"; $("#es-fixo-tamanho").value = e.fixo_tamanho || "medio";
  $("#es-tamanho").value = e.tamanho; $("#es-tempo").value = String(e.tempo_gancho); $("#es-erro").hidden = true; amostrasEstilo();
  atualizarPrevia(); $("#janela-estilo").showModal();
});
$("#form-estilo").addEventListener("change", atualizarPrevia);
$("#es-fixo").addEventListener("input", atualizarPrevia);
$("#form-estilo").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try { await api("POST", "/api/config", { estilo: estiloEscolhido() }); $("#janela-estilo").close(); avisar("Estilo salvo para os próximos vídeos"); atualizar(); }
  catch (e) { $("#es-erro").textContent = e.message; $("#es-erro").hidden = false; }
});


/* ---------- Pastas ---------- */
let assinaturaPastas = "", assinaturaFiltros = "";
function nomePasta(p) {
  const dia = new Date(p.desde * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  return `${p.canal}, ${dia}${p.gravada ? ", gravada" : ""}`;
}
function renderFiltrosPasta() {
  const lista = estado.postagem.pastas, chave = JSON.stringify(lista.map((p) => [p.id, p.cortes]));
  if (chave === assinaturaFiltros) return;
  assinaturaFiltros = chave;
  [["#filtro-pasta", "Todas as pastas"], ["#agenda-pasta", "Todas as pastas da agenda"]].forEach(([alvo, todas]) => {
    const campo = $(alvo), atual = campo.value;
    campo.replaceChildren(el("option", { value: "" }, todas), ...lista.map((p) => el("option", { value: p.id }, `${nomePasta(p)} (${p.cortes})`)));
    campo.value = lista.some((p) => p.id === atual) ? atual : "";
  });
}
function renderPastas(p) {
  renderFiltrosPasta();
  const chave = JSON.stringify(p.pastas.map((x) => [x.id, x.ativa, x.cortes, x.na_fila, x.agendados]));
  if (chave === assinaturaPastas) return;
  assinaturaPastas = chave;
  $("#lista-pastas").replaceChildren(...(p.pastas.length ? p.pastas.map((x) => {
    const caixa = el("input", { type: "checkbox", onchange: async () => {
      try { await api("POST", "/api/postagem/pastas", { pasta: x.id, ativa: caixa.checked }); avisar(caixa.checked ? "Pasta na agenda" : "Pasta fora da agenda"); atualizar(); }
      catch (e) { caixa.checked = !caixa.checked; avisar(e.message); }
    } });
    caixa.checked = x.ativa;
    const detalhe = x.ativa ? `${x.na_fila} na fila, ${x.agendados} agendados` : `${x.cortes} cortes guardados, fora da agenda`;
    return el("li", { dados: { ativa: String(x.ativa) } }, el("label", { class: "marcar", title: x.titulo }, caixa, el("span", {}, el("b", {}, nomePasta(x)), el("small", {}, x.titulo ? `${x.titulo}. ${detalhe}` : detalhe))));
  }) : [el("li", { class: "dica" }, "As pastas aparecem quando sair o primeiro corte.")]));
}
$("#filtro-pasta").addEventListener("change", () => { if (estado) renderCortes(); });
$("#agenda-pasta").addEventListener("change", () => { paginaAgenda = 1; if (estado) renderPostagem(); });


/* ---------- Paginação da agenda ---------- */
function irParaPagina(n) {
  paginaAgenda = n; renderPostagem();
  $("#aba-postagem").scrollIntoView({ block: "start" });
}
function numerosPagina(atual, total) {
  const lista = [];
  for (let n = 1; n <= total; n++) if (n === 1 || n === total || Math.abs(n - atual) <= 1) lista.push(n);
  return lista.flatMap((n, i) => (i && n - lista[i - 1] > 1 ? ["…", n] : [n]));
}
function renderPaginacao(total, inicio, naPagina, paginas) {
  $("#agenda-paginacao").hidden = total === 0;
  $("#agenda-contagem").textContent = total ? `Mostrando ${inicio + 1} a ${inicio + naPagina} de ${total}` : "";
  const seta = (rotulo, destino, ativo) => { const b = el("button", { class: "botao fantasma", type: "button", onclick: () => irParaPagina(destino) }, rotulo); b.disabled = !ativo; return b; };
  $("#agenda-paginas").replaceChildren(seta("Anterior", paginaAgenda - 1, paginaAgenda > 1),
    ...numerosPagina(paginaAgenda, paginas).map((n) => n === "…" ? el("span", { "aria-hidden": "true" }, "…")
      : el("button", { class: "pagina", type: "button", "aria-label": `Página ${n}`, "aria-current": n === paginaAgenda ? "page" : undefined, onclick: () => irParaPagina(n) }, String(n))),
    seta("Próxima", paginaAgenda + 1, paginaAgenda < paginas));
}
$("#agenda-por-pagina").addEventListener("change", () => { paginaAgenda = 1; renderPostagem(); });
async function decidirRepetidos(acao, aviso) {
  try { const r = await api("POST", "/api/postagem/repetidos", { acao }); avisar(`${r.total} ${aviso}`); atualizar(); } catch (e) { avisar(e.message); }
}
$("#repetidos-tirar").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Confirmar", () => decidirRepetidos("tirar", "saíram da fila")));
$("#repetidos-manter").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Confirmar", () => decidirRepetidos("manter", "liberados para este canal")));

/* ---------- Arrastar legenda e título ---------- */
const ALCAS_ESTILO = [
  { palco: "v", nome: "Legenda", x: "legenda_x", y: "legenda_y", ancora: "translate(-50%, -100%)", largura: "76%", altura: "13%", lim: [.16, .84, .1, .985] },
  { palco: "v", nome: "Título", x: "gancho_x", y: "gancho_y", ancora: "translate(-50%, 0)", largura: "76%", altura: "9%", gancho: true, lim: [.16, .84, .01, .88] },
  { palco: "h", nome: "Legenda", x: "legenda_hx", y: "legenda_hy", ancora: "translate(-50%, -100%)", largura: "62%", altura: "13%", lim: [.2, .8, .12, .985] },
  { palco: "h", nome: "Título", x: "gancho_hx", y: "gancho_hy", ancora: "translate(0, 0)", largura: "30%", altura: "11%", gancho: true, lim: [0, .7, .01, .86] },
];
let posicoesEstilo = {}, posicoesAuto = {};
const valorPosicao = (chave) => posicoesEstilo[chave] ?? posicoesAuto[chave] ?? .5;
function colocarAlca(a) {
  a.n.style.left = `${valorPosicao(a.x) * 100}%`; a.n.style.top = `${valorPosicao(a.y) * 100}%`;
}
function colocarAlcas() {
  const semTitulo = $('#form-estilo input[name="es-gancho"]:checked')?.value === "nenhum";
  ALCAS_ESTILO.forEach((a) => { colocarAlca(a); a.n.hidden = !!a.gancho && semTitulo; });
}
function moverAlca(a, x, y) {
  const limitar = (v, min, max) => Math.round(Math.min(max, Math.max(min, v)) * 10000) / 10000;
  posicoesEstilo[a.x] = limitar(x, a.lim[0], a.lim[1]); posicoesEstilo[a.y] = limitar(y, a.lim[2], a.lim[3]);
  colocarAlca(a);
}
ALCAS_ESTILO.forEach((a) => {
  const palco = $(`#es-palco-${a.palco}`);
  a.n = el("div", { class: "es-alca", tabindex: "0", role: "button", "aria-label": `${a.nome}. Arraste ou use as setas para mover.`, style: `width:${a.largura};height:${a.altura};transform:${a.ancora}` }, el("span", {}, a.nome));
  palco.append(a.n);
  let inicio = null;
  a.n.addEventListener("pointerdown", (ev) => {
    ev.preventDefault(); a.n.setPointerCapture(ev.pointerId); a.n.focus();
    inicio = { px: ev.clientX, py: ev.clientY, x: valorPosicao(a.x), y: valorPosicao(a.y) }; a.n.dataset.arrastando = "true";
  });
  a.n.addEventListener("pointermove", (ev) => {
    if (!inicio) return;
    const r = palco.getBoundingClientRect();
    moverAlca(a, inicio.x + (ev.clientX - inicio.px) / r.width, inicio.y + (ev.clientY - inicio.py) / r.height);
  });
  const soltar = () => { if (!inicio) return; inicio = null; a.n.dataset.arrastando = "false"; atualizarPrevia(); };
  a.n.addEventListener("pointerup", soltar); a.n.addEventListener("pointercancel", soltar);
  a.n.addEventListener("keydown", (ev) => {
    const d = { ArrowLeft: [-.01, 0], ArrowRight: [.01, 0], ArrowUp: [0, -.01], ArrowDown: [0, .01] }[ev.key];
    if (!d) return;
    ev.preventDefault(); moverAlca(a, valorPosicao(a.x) + d[0], valorPosicao(a.y) + d[1]); atualizarPrevia();
  });
});
$("#es-restaurar").addEventListener("click", () => { posicoesEstilo = {}; colocarAlcas(); atualizarPrevia(); });
$("#form-estilo").addEventListener("change", colocarAlcas);
$("#abrir-estilo").addEventListener("click", async () => {
  const e = estado?.config?.estilo || {};
  posicoesEstilo = Object.fromEntries(ALCAS_ESTILO.flatMap((a) => [a.x, a.y]).filter((k) => e[k] !== null && e[k] !== undefined).map((k) => [k, e[k]]));
  posicoesAuto = await api("GET", "/api/estilo/posicoes").catch(() => ({}));
  colocarAlcas(); atualizarPrevia();
});


/* ---------- Prévia e exclusão de Shorts ---------- */
function marcasDaPagina() { return $$("#agenda-dias .item-marca"); }
function atualizarSelecao() {
  const n = selecionados.size, marcas = marcasDaPagina(), geral = $("#selecionar-pagina");
  $("#selecao-total").textContent = n ? `${n} ${n === 1 ? "selecionado" : "selecionados"}` : "";
  $("#apagar-selecionados").disabled = !n;
  geral.disabled = !marcas.length;
  geral.checked = marcas.length > 0 && marcas.every((m) => m.checked);
  geral.indeterminate = !geral.checked && marcas.some((m) => m.checked);
}
$("#selecionar-pagina").addEventListener("change", (ev) => {
  marcasDaPagina().forEach((m) => {
    m.checked = ev.target.checked;
    const id = m.closest(".item").dataset.id;
    if (m.checked) selecionados.add(id); else selecionados.delete(id);
  });
  atualizarSelecao();
});
async function apagarShorts(ids) {
  const r = await api("POST", "/api/postagem/apagar", { ids });
  ids.forEach((id) => selecionados.delete(id));
  avisar(r.total === 1 ? "1 Short apagado" : `${r.total} Shorts apagados`);
  atualizar();
}
$("#apagar-selecionados").addEventListener("click", (ev) => confirmar(ev.currentTarget, `Apagar ${selecionados.size} de vez`, () => apagarShorts([...selecionados])));
$("#it-apagar").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Apagar de vez", async () => { await apagarShorts([itemAberto.id]); $("#janela-item").close(); }));
$("#janela-item").addEventListener("close", () => { const p = $("#it-player"); p.pause(); p.removeAttribute("src"); p.load(); });


/* ---------- Últimos cortes ---------- */
let assinaturaRecentes = "";
function renderRecentes() {
  const lista = estado.cortes.filter((c) => c.status === "pronto").slice(0, 8);
  const chave = JSON.stringify(lista.map((c) => [c.id, c.versao, c.gancho]));
  $("#recentes").hidden = !lista.length;
  if (chave === assinaturaRecentes) return;
  assinaturaRecentes = chave;
  $("#recentes-lista").replaceChildren(...lista.map((c) => el("button", { class: "recente", type: "button", onclick: () => abrirEditor(c.id) },
    el("img", { src: `/cortes/${c.id}/capa.jpg?v=${c.versao || 0}`, alt: "", loading: "lazy" }), el("span", {}, c.gancho || c.motivo))));
}

/* ---------- Atalhos para o editor ---------- */
$("#ed-timeline").addEventListener("click", () => { const id = corteAberto.id; $("#editor").close(); abrirTimeline("corte", id); });
$("#jl-timeline").addEventListener("click", () => { const id = longoAberto.id; $("#janela-longo").close(); abrirTimeline("longo", id); });
$("#it-timeline").addEventListener("click", () => { const id = itemAberto.corte || itemAberto.id; $("#janela-item").close(); abrirTimeline("corte", id); });

/* ---------- Programa ---------- */
api("GET", "/api/programa").then((p) => { $("#aj-versao").textContent = `Versão ${p.versao}`; $("#aj-encerrar").hidden = !p.pode_encerrar;
  $("#aj-fundo-rot").hidden = !p.disponivel; $("#aj-win-rot").hidden = !p.pode_iniciar_windows; $("#aj-fundo").checked = !!p.segundo_plano; $("#aj-win").checked = !!p.com_windows; }).catch(() => {});
$("#aj-fundo").addEventListener("change", (ev) => api("POST", "/api/programa", { segundo_plano: ev.target.checked }).catch((e) => avisar(e.message)));
$("#aj-win").addEventListener("change", (ev) => api("POST", "/api/programa", { com_windows: ev.target.checked }).catch((e) => avisar(e.message)));
$("#aj-encerrar").addEventListener("click", (ev) => confirmar(ev.currentTarget, "Confirmar", async () => {
  await api("POST", "/api/encerrar", {}).catch(() => {}); document.body.replaceChildren(el("p", { class: "sem-cortes" }, "O Clipador foi fechado. Pode fechar esta aba."));
}));

/* ---------- Aprendizado ---------- */
let tempoAprendizado;
const NOMES_TROCA = { corte: "corte seco", chicote: "chicote", clarao: "clarão", suave: "passagem suave" };
const NOMES_REACAO = { risada: "Risadas", choque: "Choque", hype: "Hype", clipe: "Pedidos de clipe", jogo: "Ação no jogo", streamer: "Reação do streamer", admirado: "Streamer admirado", destaque: "Melhor momento", manual: "Manual" };
const NOMES_PREF = { tamanho: "Tamanho da legenda", cor: "Cor da legenda", cor_destaque: "Cor de destaque", y: "Altura da legenda", maiusculas: "Letras maiúsculas", palavra_a_palavra: "Uma palavra por vez", destaque: "Destaque de palavras", fonte: "Fonte", entrada: "Animação de entrada", saida: "Animação de saída", contorno: "Contorno", zoom_forca: "Força do zoom", volume_efeitos: "Volume dos efeitos", volume_fala: "Volume da fala", volume_musica: "Volume da música" };
const NOMES_FILTRO = { nenhum: "original", noir: "preto e branco", dramatico: "dramático", gamer: "gamer", por_do_sol: "pôr do sol", quente: "quente", frio: "frio", vibrante: "vibrante" };
function raioX(r) {
  const seg = (v) => `${String(v).replace(".", ",")} s`, linha = (titulo, ...corpo) => el("div", { class: "rx-linha" }, el("h4", {}, titulo), el("div", {}, ...corpo));
  const g = r.gancho, c = r.cores, rt = r.ritmo, dur = r.cortes.duracao || 1;
  const paleta = el("div", { class: "rx-paleta", role: "img", "aria-label": "Cores principais do vídeo" }, ...c.paleta.map((p) => { const n = el("span", { title: p.hex }); n.style.background = p.hex; n.style.flexGrow = String(Math.max(.06, p.peso)); return n; }));
  const faixa = el("div", { class: "rx-cortes", role: "img", "aria-label": `${r.cortes.marcas.length} trocas de cena` }, ...r.cortes.marcas.map((m) => { const n = el("i", { title: `${seg(m.t)}: ${NOMES_TROCA[m.tipo] || m.tipo}` }); n.style.left = `${Math.min(100, m.t / dur * 100)}%`; return n; }));
  const fase = rt.partes[0] > rt.partes[2] ? "Mais rápido no começo" : rt.partes[2] > rt.partes[0] ? "Acelera até o final" : "Ritmo constante";
  const tipos = Object.entries(r.cortes.tipos).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${NOMES_TROCA[k] || k}: ${v}`).join(", ");
  return el("details", { class: "rx" }, el("summary", {}, "Ver como o vídeo foi desmontado"),
    linha("Gancho", el("strong", {}, g.tipo_nome), g.fala ? el("q", {}, g.fala) : null, g.primeira_troca != null ? el("small", {}, `Primeira troca de cena em ${seg(g.primeira_troca)}`) : null),
    linha("Ritmo", el("strong", {}, rt.cena_s ? `Uma cena a cada ${seg(rt.cena_s)}` : "Sem trocas de cena"), el("small", {}, `${fase}. ${Math.round(rt.cortes_min)} trocas por minuto.`)),
    linha("Cores", paleta, el("small", {}, `Nos seus vídeos: filtro ${NOMES_FILTRO[c.filtro] || c.filtro} e destaque ${c.cor}`)),
    linha("Cortes", faixa, el("small", {}, tipos || "Plano único")),
    r.chamada ? linha("Final", el("q", {}, r.chamada)) : null);
}
let estiloAtual = null;
function abrirEstilo(m, marca) {
  const lista = pastasDaMontagem().filter((p) => p.n >= 2), sel = $("#ev-pasta"); estiloAtual = m;
  if (!lista.length) { avisar("Você precisa de pelo menos 2 cortes prontos na mesma pasta."); return; }
  sel.replaceChildren(...lista.map((p) => el("option", { value: p.id }, `${p.nome}: ${p.n} cortes`)));
  $("#ev-resumo").textContent = `Usa o estilo ${m.nome} com as suas cenas, o seu texto e a sua marca.`;
  $("#ev-marca").value = marca.nome || ""; $("#ev-chamada").value = marca.chamada || ""; $("#ev-erro").hidden = true; $("#janela-viral").showModal();
}
$("#janela-viral [data-fechar]").addEventListener("click", () => $("#janela-viral").close());
$("#form-viral").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try { await api("POST", "/api/montagens/estilo", { modelo: estiloAtual.id, pasta: $("#ev-pasta").value, gancho: $("#ev-gancho").value, partes: $("#ev-partes").value, marca: $("#ev-marca").value, chamada: $("#ev-chamada").value }); $("#janela-viral").close(); $("#janela-aprendizado").close(); avisar("O vídeo começou a ser criado"); atualizar(); }
  catch (e) { $("#ev-erro").textContent = e.message; $("#ev-erro").hidden = false; }
});
/* Envio dos vídeos de exemplo com barra de progresso */
const mb = (b) => `${(b / 1048576).toLocaleString("pt-BR", { maximumFractionDigits: b < 1048576 * 10 ? 1 : 0 })} MB`;
function enviarUm(a, aoAndar) {
  return new Promise((ok) => {
    const x = new XMLHttpRequest(); x.open("POST", `/api/aprendizado/referencia?nome=${encodeURIComponent(a.name)}`);
    x.upload.onprogress = (ev) => { if (ev.lengthComputable) aoAndar(ev.loaded, ev.total); };
    x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch {} ok(x.status < 300 ? null : j.erro || `Não foi possível enviar ${a.name}.`); };
    x.onerror = () => ok(`Não foi possível enviar ${a.name}.`); x.send(a);
  });
}
let enviandoExemplos = false;
async function enviarExemplos(lista) {
  if (!lista.length || enviandoExemplos) return;
  enviandoExemplos = true; const caixa = $("#ap-envio"), total = lista.reduce((s, a) => s + a.size, 0), erros = []; let feito = 0, inicio = performance.now();
  const pintar = (n, enviado) => { const pct = Math.min(100, Math.round((feito + enviado) / Math.max(1, total) * 100)), seg = (performance.now() - inicio) / 1000, veloc = (feito + enviado) / Math.max(.5, seg), falta = (total - feito - enviado) / Math.max(1, veloc);
    $("#ap-envio-titulo").textContent = lista.length > 1 ? `Enviando vídeo ${n + 1} de ${lista.length}` : "Enviando vídeo"; $("#ap-envio-pct").textContent = `${pct}%`; $("#ap-envio-barra").style.width = `${pct}%`; $("[role=progressbar]", caixa).setAttribute("aria-valuenow", String(pct));
    $("#ap-envio-detalhe").textContent = `${lista[n].name}, ${mb(feito + enviado)} de ${mb(total)}${seg > 2 && falta > 1 ? `, falta cerca de ${falta < 60 ? `${Math.ceil(falta)} s` : `${Math.ceil(falta / 60)} min`}` : ""}`; };
  caixa.hidden = false; caixa.removeAttribute("data-fim");
  for (const [n, a] of lista.entries()) { pintar(n, 0); const erro = await enviarUm(a, (e) => pintar(n, e)); if (erro) erros.push(erro); feito += a.size; }
  enviandoExemplos = false; caixa.dataset.fim = "1"; $("#ap-envio-pct").textContent = "100%"; $("#ap-envio-barra").style.width = "100%";
  $("#ap-envio-titulo").textContent = erros.length ? (erros.length === lista.length ? "O envio falhou" : `${lista.length - erros.length} de ${lista.length} vídeos enviados`) : lista.length > 1 ? `${lista.length} vídeos enviados` : "Vídeo enviado";
  $("#ap-envio-detalhe").textContent = erros.length ? erros.join(" ") : "Agora o Clipador está analisando. Pode fechar esta janela, a análise continua.";
  setTimeout(() => { if (!enviandoExemplos) caixa.hidden = true; }, erros.length ? 12000 : 6000);
  desenharAprendizado().catch(() => {});
}
async function desenharAprendizado() {
  const d = await api("GET", "/api/aprendizado"), p = d.perfil, c = $("#ap-corpo"), t = d.trabalho;
  const chave = (k, rot, dica) => { const n = el("input", { type: "checkbox" }); n.checked = d.ativo[k]; n.addEventListener("change", async () => { await api("POST", "/api/aprendizado", { [k]: n.checked }); desenharAprendizado(); }); return el("label", { class: "marcar" }, n, el("span", {}, el("strong", {}, rot), el("small", {}, dica))); };
  const envio = el("input", { type: "file", accept: "video/*", hidden: "", multiple: "" });
  envio.addEventListener("change", () => { enviarExemplos([...envio.files]); envio.value = ""; });
  const detalhes = (p) => [p.webcam ? "Câmera em cima do jogo" : null, p.palavra_a_palavra ? "Uma palavra por vez na legenda" : null, p.cena_s ? `Cenas de ${String(p.cena_s).replace(".", ",")} segundos` : `${Math.round(p.cortes_min)} trocas por minuto`, p.zooms_min ? `${Math.round(p.zooms_min)} zooms por minuto` : null, p.transicoes?.length ? `Transição: ${NOMES_TROCA[p.transicoes[0]] || p.transicoes[0]}` : null, p.sfx_cortes != null ? `Som em ${Math.round(p.sfx_cortes * 100)}% das trocas` : null].filter(Boolean);
  const cartaoModelo = (m) => {
    const criar = el("button", { class: "botao destaque", type: "button", onclick: () => abrirEstilo(m, d.marca) }, "Criar vídeo neste estilo");
    const nome = el("input", { class: "ap-nome", value: m.nome, maxlength: "50", "aria-label": "Nome do modelo" }); nome.addEventListener("change", async () => { await api("POST", `/api/aprendizado/modelos/${m.id}`, { nome: nome.value }); desenharAprendizado(); });
    const liga = el("input", { type: "checkbox" }); liga.checked = m.ativo; liga.addEventListener("change", async () => { await api("POST", `/api/aprendizado/modelos/${m.id}`, { ativo: liga.checked }); desenharAprendizado(); });
    const fim = m.resultado ? `, ${m.resultado.media.toLocaleString("pt-BR")} visualizações em média` : "";
    const apagar = el("button", { class: "botao fantasma", type: "button", onclick: () => confirmar(apagar, "Confirmar", async () => { await api("DELETE", `/api/aprendizado/modelos/${m.id}`); avisar("Modelo removido"); desenharAprendizado(); }) }, "Remover modelo");
    return el("li", { class: "ap-modelo", dados: { ativo: String(m.ativo) } }, el("div", { class: "ap-modelo-topo" }, nome, el("label", { class: "marcar" }, liga, el("span", {}, "Usar"))),
      el("p", { class: "dica" }, `${m.exemplos.length} ${m.exemplos.length === 1 ? "exemplo" : "exemplos"}, usado em ${m.uso} ${m.uso === 1 ? "corte" : "cortes"}${fim}`), el("p", { class: "ap-traits" }, detalhes(m.perfil).join(", ")), m.raiox ? raioX(m.raiox) : null, criar,
      el("details", {}, el("summary", {}, "Ver exemplos"), el("ul", { class: "ap-lista" }, ...m.exemplos.map((r) => el("li", {}, el("span", {}, r.nome), el("button", { class: "botao fantasma", type: "button", onclick: async () => { await api("DELETE", `/api/aprendizado/referencias/${r.id}`); desenharAprendizado(); } }, "Remover")))), apagar));
  };
  const prefs = [...Object.entries(d.preferencias.legenda), ...Object.entries(d.preferencias.global)].map(([k, v]) => `${NOMES_PREF[k] || k}: ${v === true ? "sim" : v === false ? "não" : v}`), des = d.desempenho, tipos = Object.entries(des.tipos || {}).sort((a, b) => b[1].media - a[1].media);
  const cartaoIdeia = (i) => {
    const liga = el("input", { type: "checkbox" }); liga.checked = i.ligada;
    liga.addEventListener("change", async () => { try { await api("POST", "/api/config", { ideias: { [i.id]: liga.checked } }); await atualizar(); desenharAprendizado(); } catch (e) { avisar(e.message); } });
    const n = (v, um, varios) => `${v} ${v === 1 ? um : varios}`;
    const numeros = i.usos ? `Usada em ${n(i.usos, "corte", "cortes")}: você postou ${i.postados}, apagou ${i.descartados} sem postar e trocou ${i.trocados}.` : "Ainda não foi usada.";
    return el("li", { class: "ap-modelo", dados: { ativo: String(i.ligada) } },
      el("div", { class: "ap-modelo-topo" }, el("b", {}, i.nome), el("label", { class: "marcar" }, liga, el("span", {}, "Testar"))),
      el("p", { class: "dica" }, i.descricao), el("p", { class: "ap-traits" }, numeros),
      i.resultado ? el("p", { class: "dica" }, `${i.resultado.media.toLocaleString("pt-BR")} visualizações em média (${n(i.resultado.n, "Short", "Shorts")})`) : null,
      i.ligada && d.ideias.filter((x) => x.ligada).length > 1 ? el("p", { class: "ap-chance" }, `Aparece em cerca de ${Math.round(i.chance * 100)}% dos próximos cortes`) : null);
  };
  const secaoCorrecoes = el("section", {}, el("h3", {}, "Correções da legenda"),
    el("p", { class: "dica" }, "Quando você corrige uma palavra na legenda de um corte, o Clipador passa a trocar aquele erro sozinho. Palavras comuns, como “mas” e “mais”, só são trocadas depois de você corrigir duas vezes."),
    d.correcoes?.length ? el("ul", { class: "ap-correcoes" }, ...d.correcoes.map((x) => el("li", {},
      el("span", {}, el("s", {}, x.errado), " → ", el("b", {}, x.certo), x.valendo ? null : el("small", {}, " (falta mais uma correção)")),
      (() => { const b = el("button", { type: "button", class: "ap-esquecer" }, "Esquecer"); b.addEventListener("click", async () => { try { await api("POST", "/api/aprendizado", { esquecer_correcao: x.errado }); desenharAprendizado(); } catch (e) { avisar(e.message); } }); return b; })())))
      : el("p", { class: "dica" }, "Nenhuma correção ainda."));
  c.replaceChildren(
    el("section", {}, el("h3", {}, "Ideias em teste"),
      el("p", { class: "dica" }, d.modelos.some((m) => m.ativo) ? "Enquanto houver modelos aprendidos com vídeos de referência, eles decidem o estilo. As ideias voltam a ser testadas se você desligar os modelos." : "Cada corte novo recebe uma destas ideias. O que você posta conta a favor; o que você apaga sem postar ou troca no corte conta contra. Com o YouTube conectado, as visualizações contam ainda mais. A ideia que vai melhor aparece mais, e as outras continuam aparecendo de vez em quando."),
      el("ul", { class: "ap-modelos" }, ...d.ideias.map(cartaoIdeia))),
    secaoCorrecoes,
    el("section", {}, el("h3", {}, "Vídeos de referência"), chave("referencias", "Aprender com estes vídeos", "Envie vídeos que deram certo. O Clipador desmonta o gancho, o ritmo, as cores e os cortes, e salva o estilo. Os vídeos são apagados depois da análise."),
      envio, el("button", { class: "botao destaque", type: "button", onclick: () => envio.click(), }, ["fila", "analisando"].includes(t.estado) ? `Analisando ${t.restantes > 1 ? `${t.restantes} vídeos` : "o vídeo"}…` : "Ensinar com vídeos"), t.erro ? el("p", { class: "erro-campo" }, t.erro) : null,
      d.modelos.length ? el("ul", { class: "ap-modelos" }, ...d.modelos.map(cartaoModelo)) : el("p", { class: "dica" }, "Envie vídeos de estilos diferentes. Cada estilo vira um modelo, e os próximos cortes usam todos eles.")),
    el("section", {}, el("h3", {}, "Suas edições"), chave("edicoes", "Aprender com o que eu mudo no Editor", "Uma mudança vira padrão quando se repete em 2 vídeos exportados."), el("p", { class: "dica" }, `${d.videos_editados} ${d.videos_editados === 1 ? "vídeo editado" : "vídeos editados"}.`), prefs.length ? el("ul", { class: "ap-visto" }, ...prefs.map((x) => el("li", {}, x))) : el("p", { class: "dica" }, "Nenhuma preferência repetida ainda.")),
    el("section", {}, el("h3", {}, "Resultados do canal"), chave("resultados", "Priorizar o que dá mais visualizações", `Compara os Shorts publicados há mais de 2 dias. Cada tipo precisa de ${d.minimo} vídeos.`), tipos.length ? el("ul", { class: "ap-visto" }, ...tipos.map(([k, v]) => el("li", {}, `${NOMES_REACAO[k] || k}: ${v.media.toLocaleString("pt-BR")} visualizações em média (${v.n} ${v.n === 1 ? "vídeo" : "vídeos"})`))) : el("p", { class: "dica" }, "Ainda não há Shorts publicados suficientes para comparar.")),
    el("button", { class: "botao perigo", type: "button", onclick: (ev) => confirmar(ev.currentTarget, "Apagar tudo que aprendeu", async () => { await api("POST", "/api/aprendizado/esquecer", {}); avisar("Aprendizado apagado"); desenharAprendizado(); }) }, "Esquecer tudo"));
  clearTimeout(tempoAprendizado); if (["fila", "analisando"].includes(t.estado) && $("#janela-aprendizado").open) tempoAprendizado = setTimeout(desenharAprendizado, 2000);
}
$("#abrir-aprendizado").addEventListener("click", () => { $("#janela-aprendizado").showModal(); desenharAprendizado().catch((e) => avisar(e.message)); });
$("#janela-aprendizado [data-fechar]").addEventListener("click", () => $("#janela-aprendizado").close());

// Destaca a plataforma reconhecida enquanto o link é digitado
$("#link").addEventListener("input", (ev) => { const v = ev.target.value.toLowerCase(), p = /kick\.com/.test(v) ? "kick" : /twitch\.tv/.test(v) ? "twitch" : /youtu(\.be|be\.com)/.test(v) ? "youtube" : /(^|\/\/|\.)(x|twitter)\.com/.test(v) ? "x" : "";
  $$("#plataformas li").forEach((li) => li.toggleAttribute("data-ativa", li.dataset.p === p)); });

/* Tecla C: corta a live na hora, sem tirar o olho da transmissão. */
document.addEventListener("keydown", (ev) => {
  if (ev.key.toLowerCase() !== "c" || ev.ctrlKey || ev.metaKey || ev.altKey || ev.repeat) return;
  if (ev.target.closest?.("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]") || $("#aba-vivo").hidden) return;
  const gravando = (estado?.canais || []).filter((c) => c.status === "gravando");
  if (!gravando.length) { avisar("Nenhuma live sendo gravada agora"); return; }
  if (gravando.length > 1) { avisar("Com várias lives, use o botão Cortar agora de cada uma"); return; }
  ev.preventDefault();
  api("POST", `/api/canais/${gravando[0].id}/cortar`).then(() => avisar(`Corte iniciado em ${gravando[0].nome}`)).catch((e) => avisar(e.message));
});
