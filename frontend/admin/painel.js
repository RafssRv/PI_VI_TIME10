// painel do administrador: le /api/admin/painel e desenha tudo em SVG/HTML, sem biblioteca
// (o projeto roda sem internet). as funcoes de cima sao puras e testadas em tests/frontend.

const ATUALIZAR_A_CADA_MS = 30000;   // pedido feito na ligacao aparece sozinho durante a apresentacao
const CORES = ["#c8442b", "#d99a2b", "#2e9e61", "#5b5e57", "#8e2a1c", "#9a9d95"];

const PAGAMENTOS = {
  pix: "Pix",
  dinheiro: "Dinheiro",
  cartao_credito: "Cartão de crédito",
  cartao_debito: "Cartão de débito",
  nao_informado: "Não informado"
};

const STATUS = {
  aberto: "Aberto",
  recebido: "Recebido",
  em_preparo: "Em preparo",
  saiu_entrega: "Saiu para entrega",
  entregue: "Entregue",
  concluido: "Concluído",
  cancelado: "Cancelado"
};

// ---------- formatacao ----------
function escapar(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
  })[c]);
}

function formatarDinheiro(valor, compacto) {
  const numero = Number(valor);
  if (!Number.isFinite(numero)) return "—";
  if (compacto && Math.abs(numero) >= 1000) {
    return "R$ " + (numero / 1000).toFixed(1).replace(".", ",").replace(",0", "") + " mil";
  }
  const [inteiro, centavos] = numero.toFixed(2).split(".");
  return `R$ ${inteiro.replace(/\B(?=(\d{3})+(?!\d))/g, ".")},${centavos}`;
}

function formatarNumero(valor) {
  return String(Math.round(Number(valor) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function rotuloPeriodo(dias) {
  return dias ? `vs. ${dias} dias anteriores` : "";
}

// {texto, classe} da variacao contra o periodo anterior
function formatarVariacao(percentual, dias) {
  if (percentual === null || percentual === undefined || !dias) {
    return { texto: dias ? "sem comparação" : "", classe: "neutra" };
  }
  const seta = percentual > 0 ? "▲" : percentual < 0 ? "▼" : "•";
  const classe = percentual > 0 ? "sobe" : percentual < 0 ? "desce" : "neutra";
  const valor = Math.abs(percentual).toFixed(1).replace(".", ",");
  return { texto: `${seta} ${valor}% ${rotuloPeriodo(dias)}`, classe };
}

function formatarDia(iso) {
  const [, mes, dia] = iso.split("-");
  return `${dia}/${mes}`;
}

function formatarQuando(iso) {
  const data = new Date(iso);
  const dia = String(data.getDate()).padStart(2, "0");
  const mes = String(data.getMonth() + 1).padStart(2, "0");
  const hora = String(data.getHours()).padStart(2, "0");
  const minuto = String(data.getMinutes()).padStart(2, "0");
  return `${dia}/${mes} ${hora}:${minuto}`;
}

function capitalizar(texto) {
  return String(texto || "").replace(/^\p{L}/u, (c) => c.toUpperCase());
}

// teto "redondo" pro eixo: 37 -> 40, 812 -> 1000, assim as linhas de grade caem em numeros limpos
function tetoDoEixo(maximo) {
  if (!(maximo > 0)) return 1;
  const potencia = 10 ** Math.floor(Math.log10(maximo));
  const passo = [1, 2, 2.5, 5, 10].find((p) => p * potencia >= maximo);
  return passo * potencia;
}

// ---------- graficos (devolvem string SVG/HTML) ----------
// barras verticais. pontos: [{valor, rotulo, dica}]
function graficoBarras(pontos, opcoes = {}) {
  const largura = opcoes.largura || 640;
  const altura = opcoes.altura || 220;
  const formatarEixo = opcoes.formatarEixo || formatarNumero;
  const margem = { topo: 10, direita: 4, baixo: 24, esquerda: 52 };
  const areaL = largura - margem.esquerda - margem.direita;
  const areaA = altura - margem.topo - margem.baixo;
  const teto = tetoDoEixo(Math.max(0, ...pontos.map((p) => p.valor)));
  const fatia = areaL / Math.max(pontos.length, 1);
  const larguraBarra = Math.max(1, Math.min(fatia * 0.72, 36));
  // no maximo ~10 rotulos no eixo x, senao 90 dias viram um borrao
  const pulo = Math.ceil(pontos.length / 10);

  const partes = [`<svg viewBox="0 0 ${largura} ${altura}" role="img" aria-label="${escapar(opcoes.descricao || "")}">`];
  for (let i = 0; i <= 4; i++) {
    const y = margem.topo + areaA - (areaA * i) / 4;
    partes.push(`<line class="grade-linha" x1="${margem.esquerda}" x2="${largura - margem.direita}" y1="${y}" y2="${y}"/>`);
    partes.push(`<text class="eixo" x="${margem.esquerda - 8}" y="${y + 4}" text-anchor="end">${escapar(formatarEixo((teto * i) / 4))}</text>`);
  }
  pontos.forEach((ponto, i) => {
    const x = margem.esquerda + fatia * i + (fatia - larguraBarra) / 2;
    const h = ponto.valor > 0 ? Math.max(2, (ponto.valor / teto) * areaA) : 2;
    const y = margem.topo + areaA - h;
    const dica = escapar(ponto.dica || "");
    partes.push(`<rect class="alvo" x="${margem.esquerda + fatia * i}" y="${margem.topo}" width="${fatia}" height="${areaA}" data-dica="${dica}"/>`);
    partes.push(`<rect class="barra${ponto.valor > 0 ? "" : " vazia"}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${larguraBarra.toFixed(2)}" height="${h.toFixed(2)}" rx="${Math.min(4, larguraBarra / 2).toFixed(1)}" data-dica="${dica}"/>`);
    if (i % pulo === 0) {
      partes.push(`<text class="eixo" x="${(margem.esquerda + fatia * i + fatia / 2).toFixed(2)}" y="${altura - 6}" text-anchor="middle">${escapar(ponto.rotulo)}</text>`);
    }
  });
  partes.push("</svg>");
  return partes.join("");
}

// rosca com legenda. fatias: [{rotulo, valor, detalhe}]
function graficoRosca(fatias, centro) {
  const total = fatias.reduce((soma, f) => soma + f.valor, 0);
  if (!total) return `<div class="vazio">Sem pedidos neste período.</div>`;
  const raio = 54;
  const circunferencia = 2 * Math.PI * raio;
  let acumulado = 0;
  const arcos = fatias.map((fatia, i) => {
    const tamanho = (fatia.valor / total) * circunferencia;
    const arco = `<circle cx="75" cy="75" r="${raio}" fill="none" stroke="${CORES[i % CORES.length]}" stroke-width="20"
      stroke-dasharray="${tamanho.toFixed(2)} ${(circunferencia - tamanho).toFixed(2)}"
      stroke-dashoffset="${(-acumulado).toFixed(2)}" transform="rotate(-90 75 75)"/>`;
    acumulado += tamanho;
    return arco;
  });
  const legenda = fatias.map((fatia, i) => {
    const pct = Math.round((fatia.valor / total) * 100);
    return `<li><i style="background:${CORES[i % CORES.length]}"></i><span>${escapar(fatia.rotulo)}</span><b>${pct}%</b></li>`;
  });
  return `<svg viewBox="0 0 150 150" role="img" aria-label="Formas de pagamento">${arcos.join("")}
      <text class="centro-valor" x="75" y="78" text-anchor="middle">${escapar(centro.valor)}</text>
      <text class="centro-rotulo" x="75" y="95" text-anchor="middle">${escapar(centro.rotulo)}</text>
    </svg><ul class="legenda">${legenda.join("")}</ul>`;
}

// barras horizontais. linhas: [{nome, valor, texto, detalhe}]
function barrasHorizontais(linhas) {
  if (!linhas.length) return `<li class="vazio">Sem vendas neste período.</li>`;
  const maximo = Math.max(...linhas.map((l) => l.valor), 1);
  return linhas.map((linha, i) => `
    <li>
      <span class="nome" title="${escapar(linha.nome)}">${escapar(linha.nome)}</span>
      <span class="valor">${escapar(linha.texto)}</span>
      <span class="trilho"><span style="width:${((linha.valor / maximo) * 100).toFixed(1)}%;animation-delay:${i * 60}ms"></span></span>
      ${linha.detalhe ? `<span class="detalhe">${escapar(linha.detalhe)}</span>` : ""}
    </li>`).join("");
}

// ---------- tela ----------
function iniciarPainel(documento, janela) {
  const $ = (id) => documento.getElementById(id);
  const painel = $("painel");
  const aviso = $("aviso");
  const dica = $("dica");
  const botoes = Array.from(documento.querySelectorAll(".periodos button"));
  let dias = Number(janela.localStorage?.getItem("painel-dias") ?? 30);
  if (![7, 30, 90, 0].includes(dias)) dias = 30;
  let pedindo = null;

  function marcarPeriodo() {
    botoes.forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.dias) === dias)));
  }

  function mostrarAviso(texto) {
    aviso.textContent = texto;
    aviso.hidden = !texto;
  }

  function desenhar(dados) {
    const r = dados.resumo;
    const d = dados.periodo.dias;
    $("kpi-pedidos").textContent = formatarNumero(r.pedidos);
    $("kpi-itens").textContent = `${formatarNumero(r.itens_vendidos)} itens`;
    $("kpi-faturamento").textContent = formatarDinheiro(r.faturamento);
    $("kpi-ticket").textContent = formatarDinheiro(r.ticket_medio);
    $("kpi-clientes").textContent = formatarNumero(r.clientes);
    $("kpi-novos").textContent = `${formatarNumero(r.clientes_novos)} ${r.clientes_novos === 1 ? "novo" : "novos"} no período`;

    for (const [id, valor] of [["var-pedidos", r.variacao_pedidos], ["var-faturamento", r.variacao_faturamento]]) {
      const variacao = formatarVariacao(valor, d);
      $(id).textContent = variacao.texto;
      $(id).className = "variacao " + variacao.classe;
    }

    const serie = dados.por_dia;
    $("legenda-dias").textContent = serie.length
      ? `${formatarDia(serie[0].data)} a ${formatarDia(serie[serie.length - 1].data)}` : "";
    $("grafico-dias").innerHTML = r.pedidos
      ? graficoBarras(serie.map((p) => ({
        valor: Number(p.faturamento),
        rotulo: formatarDia(p.data),
        dica: `${formatarDia(p.data)}|${formatarDinheiro(p.faturamento)}|${p.pedidos} ${p.pedidos === 1 ? "pedido" : "pedidos"}`
      })), { formatarEixo: (v) => formatarDinheiro(v, true).replace(",00", ""), descricao: "Faturamento por dia" })
      : `<div class="vazio">Nenhum pedido neste período.</div>`;

    $("grafico-horas").innerHTML = r.pedidos
      ? graficoBarras(dados.por_hora.map((h) => ({
        valor: h.pedidos,
        rotulo: `${h.hora}h`,
        dica: `${h.hora}h às ${h.hora + 1}h|${h.pedidos} ${h.pedidos === 1 ? "pedido" : "pedidos"}`
      })), { altura: 200, largura: 420, descricao: "Pedidos por horário" })
      : `<div class="vazio">Nenhum pedido neste período.</div>`;

    $("grafico-pagamentos").innerHTML = graficoRosca(
      dados.pagamentos.map((p) => ({ rotulo: PAGAMENTOS[p.forma] || p.forma, valor: p.pedidos })),
      { valor: formatarNumero(r.pedidos), rotulo: r.pedidos === 1 ? "pedido" : "pedidos" });

    $("mais-vendidos").innerHTML = barrasHorizontais(dados.mais_vendidos.map((p) => ({
      nome: p.produto, valor: p.quantidade, texto: formatarNumero(p.quantidade),
      detalhe: formatarDinheiro(p.faturamento)
    })));

    $("categorias").innerHTML = barrasHorizontais(dados.por_categoria.map((c) => ({
      nome: capitalizar(c.categoria), valor: Number(c.faturamento), texto: formatarDinheiro(c.faturamento),
      detalhe: `${formatarNumero(c.quantidade)} unidades`
    })));

    $("ultimos").innerHTML = dados.ultimos_pedidos.length
      ? dados.ultimos_pedidos.map((p) => `
        <tr>
          <td class="pedido-id">#${escapar(p.id)}</td>
          <td>${escapar(formatarQuando(p.criado_em))}</td>
          <td>${escapar(p.cliente)}</td>
          <td class="num">${escapar(p.itens)}</td>
          <td>${escapar(PAGAMENTOS[p.forma_pagamento || "nao_informado"] || p.forma_pagamento)}</td>
          <td><span class="selo ${escapar(p.status)}">${escapar(STATUS[p.status] || p.status)}</span></td>
          <td class="num">${escapar(formatarDinheiro(p.total))}</td>
        </tr>`).join("")
      : `<tr><td colspan="7" class="vazio">Nenhum pedido neste período.</td></tr>`;

    const c = dados.cardapio;
    $("cardapio").innerHTML = `
      <span class="numero">${formatarNumero(c.ativos)}</span>
      <p>produtos disponíveis para o atendente oferecer</p>
      ${c.indisponiveis.length ? `<h3>Indisponíveis (${c.indisponiveis.length})</h3>
        <ul>${c.indisponiveis.map((n) => `<li>${escapar(n)}</li>`).join("")}</ul>` : "<h3>Todos os produtos estão disponíveis.</h3>"}`;

    const hora = new Date(dados.periodo.gerado_em);
    $("atualizado").textContent = `atualizado às ${String(hora.getHours()).padStart(2, "0")}:${String(hora.getMinutes()).padStart(2, "0")}`;
  }

  async function carregar() {
    if (pedindo) pedindo.abort();
    const controle = new AbortController();
    pedindo = controle;
    painel.setAttribute("aria-busy", "true");
    try {
      const resposta = await fetch(`/api/admin/painel?dias=${dias}`, { signal: controle.signal, cache: "no-store" });
      if (resposta.status === 404) throw new Error("O painel só está disponível com AMBIENTE=dev (ainda não tem login).");
      if (resposta.status === 503) throw new Error("Não consegui consultar o banco. Ele está rodando? (npm run banco)");
      if (!resposta.ok) throw new Error("O servidor não conseguiu montar o painel.");
      desenhar(await resposta.json());
      mostrarAviso("");
    } catch (erro) {
      if (erro.name === "AbortError") return;
      mostrarAviso(erro instanceof TypeError ? "Não consegui falar com o servidor. Confira se o backend está rodando (npm run dev)." : erro.message);
      $("atualizado").textContent = "sem conexão";
    } finally {
      if (pedindo === controle) {
        pedindo = null;
        painel.classList.remove("carregando");
        painel.setAttribute("aria-busy", "false");
      }
    }
  }

  botoes.forEach((botao) => botao.addEventListener("click", () => {
    dias = Number(botao.dataset.dias);
    janela.localStorage?.setItem("painel-dias", String(dias));
    marcarPeriodo();
    carregar();
  }));

  // dica das barras: o texto vem em partes separadas por "|" (titulo|linha|linha)
  painel.addEventListener("mousemove", (evento) => {
    const alvo = evento.target.closest ? evento.target.closest("[data-dica]") : null;
    if (!alvo || !alvo.dataset.dica) {
      dica.hidden = true;
      return;
    }
    const [titulo, ...linhas] = alvo.dataset.dica.split("|");
    dica.innerHTML = `<b>${escapar(titulo)}</b>${linhas.map((l) => `<br>${escapar(l)}`).join("")}`;
    dica.style.left = `${evento.clientX}px`;
    dica.style.top = `${evento.clientY}px`;
    dica.hidden = false;
  });
  painel.addEventListener("mouseleave", () => { dica.hidden = true; });

  marcarPeriodo();
  carregar();
  janela.setInterval(() => {
    if (documento.visibilityState !== "hidden") carregar();
  }, ATUALIZAR_A_CADA_MS);
  documento.addEventListener("visibilitychange", () => {
    if (documento.visibilityState === "visible") carregar();
  });
}

if (typeof document !== "undefined" && document.getElementById("painel")) {
  iniciarPainel(document, window);
}
