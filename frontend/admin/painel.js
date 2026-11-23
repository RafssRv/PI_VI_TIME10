// painel do administrador: Dashboard de Vendas + Monitoramento de Atendimentos ao Vivo
// (o projeto roda sem biblioteca externa, 100% nativo para funcionar sem internet).

const ATUALIZAR_A_CADA_MS = 30000;
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

// andamento do pedido: um passo por vez, cancelar só antes de sair para entrega (igual ao backend)
const PROXIMA_ACAO = {
  aberto: { status: "em_preparo", rotulo: "Começar preparo" },
  em_preparo: { status: "saiu_entrega", rotulo: "Saiu para entrega" },
  saiu_entrega: { status: "entregue", rotulo: "Marcar entregue" }
};
const PODE_CANCELAR = new Set(["aberto", "em_preparo"]);

// ---------- formatacao basica ----------
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

function tetoDoEixo(maximo) {
  if (!(maximo > 0)) return 1;
  const potencia = 10 ** Math.floor(Math.log10(maximo));
  const passo = [1, 2, 2.5, 5, 10].find((p) => p * potencia >= maximo);
  return passo * potencia;
}

// ---------- graficos svg (dashboard) ----------
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

// cartão de cada pedido que a cozinha e a entrega ainda precisam tocar
function htmlDoAndamento(pedidos) {
  if (!pedidos.length) return `<p class="vazio">Nenhum pedido esperando preparo ou entrega.</p>`;
  return pedidos.map((p) => {
    const proxima = PROXIMA_ACAO[p.status];
    const pagamento = (PAGAMENTOS[p.forma_pagamento || "nao_informado"] || p.forma_pagamento) +
      (p.troco_para ? ` · troco para ${formatarDinheiro(p.troco_para)}` : "");
    const itens = p.itens.map((i) => `<li>${escapar(i.quantidade)}× ${escapar(i.produto)}${
      i.observacao ? `<small>${escapar(i.observacao)}</small>` : ""}</li>`).join("");
    return `
      <article class="pedido-andamento" data-pedido="${escapar(p.id)}">
        <header>
          <span class="pedido-id">#${escapar(p.id)} · ${escapar(formatarQuando(p.criado_em))}</span>
          <span class="selo ${escapar(p.status)}">${escapar(STATUS[p.status] || p.status)}</span>
        </header>
        <strong>${escapar(p.cliente)}</strong>
        <ul>${itens}</ul>
        <p class="entrega">${escapar(p.endereco_entrega || "endereço a confirmar")}<br>${escapar(pagamento)} · ${escapar(formatarDinheiro(p.total))}</p>
        <div class="acoes">
          ${proxima ? `<button type="button" class="avancar" data-status="${proxima.status}">${proxima.rotulo}</button>` : ""}
          ${PODE_CANCELAR.has(p.status) ? `<button type="button" class="cancelar" data-status="cancelado">Cancelar</button>` : ""}
        </div>
      </article>`;
  }).join("");
}

// ========================================================
// CONTROLE DO PAINEL: DASHBOARD E MONITOR
// ========================================================
function iniciarPainel(documento, janela) {
  const $ = (id) => documento.getElementById(id);
  const secaoDashboard = $("secao-dashboard");
  const secaoMonitor = $("secao-monitor");
  const btnAbaDashboard = $("aba-btn-dashboard");
  const btnAbaMonitor = $("aba-btn-monitor");
  const controlesPeriodo = $("controles-periodo");
  const aviso = $("aviso");
  const dica = $("dica");

  let abaAtiva = "dashboard";
  let dias = Number(janela.localStorage?.getItem("painel-dias") ?? 30);
  if (![7, 30, 90, 0].includes(dias)) dias = 30;
  let pedindoDashboard = null;

  // Alternar abas
  function alternarAba(aba) {
    abaAtiva = aba;
    if (aba === "dashboard") {
      btnAbaDashboard.classList.add("ativa");
      btnAbaDashboard.setAttribute("aria-selected", "true");
      btnAbaMonitor.classList.remove("ativa");
      btnAbaMonitor.setAttribute("aria-selected", "false");
      secaoDashboard.hidden = false;
      secaoMonitor.hidden = true;
      controlesPeriodo.hidden = false;
    } else {
      btnAbaMonitor.classList.add("ativa");
      btnAbaMonitor.setAttribute("aria-selected", "true");
      btnAbaDashboard.classList.remove("ativa");
      btnAbaDashboard.setAttribute("aria-selected", "false");
      secaoMonitor.hidden = false;
      secaoDashboard.hidden = true;
      controlesPeriodo.hidden = true;
    }
  }

  btnAbaDashboard?.addEventListener("click", () => alternarAba("dashboard"));
  btnAbaMonitor?.addEventListener("click", () => alternarAba("monitor"));

  // ---------- 1. DASHBOARD ----------
  const botoesPeriodo = Array.from(documento.querySelectorAll(".periodos button"));
  function marcarPeriodo() {
    botoesPeriodo.forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.dias) === dias)));
  }

  function mostrarAviso(texto) {
    aviso.textContent = texto;
    aviso.hidden = !texto;
  }

  function desenharDashboard(dados) {
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

  async function carregarDashboard() {
    if (pedindoDashboard) pedindoDashboard.abort();
    const controle = new AbortController();
    pedindoDashboard = controle;
    secaoDashboard.setAttribute("aria-busy", "true");
    try {
      const resposta = await fetch(`/api/admin/painel?dias=${dias}`, { signal: controle.signal, cache: "no-store" });
      if (resposta.status === 404) throw new Error("O painel só está disponível com AMBIENTE=dev.");
      if (resposta.status === 503) throw new Error("Não consegui consultar o banco de dados.");
      if (!resposta.ok) throw new Error("O servidor não conseguiu montar o painel.");
      desenharDashboard(await resposta.json());
      mostrarAviso("");
    } catch (erro) {
      if (erro.name === "AbortError") return;
      mostrarAviso(erro instanceof TypeError ? "Não consegui falar com o servidor backend." : erro.message);
      $("atualizado").textContent = "sem conexão";
    } finally {
      if (pedindoDashboard === controle) {
        pedindoDashboard = null;
        secaoDashboard.classList.remove("carregando");
        secaoDashboard.setAttribute("aria-busy", "false");
      }
    }
  }

  // ---------- PEDIDOS EM ANDAMENTO ----------
  const emAndamento = $("em-andamento");

  async function carregarEmAndamento() {
    try {
      const resposta = await fetch("/api/admin/pedidos/andamento", { cache: "no-store" });
      if (!resposta.ok) throw new Error("Não consegui ler os pedidos em andamento.");
      const dados = await resposta.json();
      emAndamento.innerHTML = htmlDoAndamento(dados.pedidos);
      const n = dados.pedidos.length;
      $("andamento-contador").textContent = n ? `${n} ${n === 1 ? "pedido" : "pedidos"}` : "";
    } catch (erro) {
      mostrarAviso(erro instanceof TypeError ? "Não consegui falar com o servidor backend." : erro.message);
    }
  }

  emAndamento?.addEventListener("click", async (evento) => {
    const botao = evento.target.closest("button[data-status]");
    if (!botao) return;
    const cartao = botao.closest("[data-pedido]");
    const id = cartao.dataset.pedido;
    if (botao.dataset.status === "cancelado" && !janela.confirm(`Cancelar o pedido #${id}?`)) return;
    cartao.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const resposta = await fetch(`/api/admin/pedidos/${encodeURIComponent(id)}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: botao.dataset.status })
      });
      // 409: outra tela já mudou o pedido; a lista nova mostra o status certo
      if (resposta.status === 409) mostrarAviso(`O pedido #${id} já tinha mudado de status. A lista foi atualizada.`);
      else if (!resposta.ok) throw new Error("Não consegui mudar o status do pedido.");
    } catch (erro) {
      mostrarAviso(erro instanceof TypeError ? "Não consegui falar com o servidor backend." : erro.message);
    }
    await carregarEmAndamento();
    carregarDashboard();
  });

  botoesPeriodo.forEach((botao) => botao.addEventListener("click", () => {
    dias = Number(botao.dataset.dias);
    janela.localStorage?.setItem("painel-dias", String(dias));
    marcarPeriodo();
    carregarDashboard();
  }));

  // Tooltip
  documento.addEventListener("mousemove", (evento) => {
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
  documento.addEventListener("mouseleave", () => { dica.hidden = true; });

  marcarPeriodo();
  carregarDashboard();
  carregarEmAndamento();
  janela.setInterval(() => {
    if (documento.visibilityState !== "hidden" && abaAtiva === "dashboard") {
      carregarDashboard();
      carregarEmAndamento();
    }
  }, ATUALIZAR_A_CADA_MS);

  // ---------- 2. MONITORAMENTO AO VIVO (WEBSOCKET) ----------
  let socketMonitor = null;
  const chamadasAtivasMap = new Map();
  let historicoChamadasList = [];

  const monitorBolinha = $("monitor-bolinha");
  const monitorStatusTexto = $("monitor-status-texto");
  const statQtdAtivas = $("stat-qtd-ativas");
  const statQtdHistorico = $("stat-qtd-historico");
  const badgeAtivas = $("badge-ativas");
  const pulsoAtivas = $("pulso-ativas");
  const containerAtivas = $("container-chamadas-ativas");
  const containerHistorico = $("container-historico-atendimentos");

  function atualizarBadgesAtivas() {
    const total = chamadasAtivasMap.size;
    statQtdAtivas.textContent = total;
    if (total > 0) {
      badgeAtivas.textContent = total;
      badgeAtivas.hidden = false;
      pulsoAtivas.hidden = false;
    } else {
      badgeAtivas.hidden = true;
      pulsoAtivas.hidden = true;
    }
  }

  function renderizarChamadasAtivas() {
    if (chamadasAtivasMap.size === 0) {
      containerAtivas.innerHTML = `
        <div class="vazio-monitor">
          <span class="icone-vazio">🎧</span>
          <p>Nenhuma chamada acontecendo no momento.</p>
          <small class="fraco">Quando um cliente iniciar a ligação pelo navegador, ela aparecerá aqui em tempo real com transcrição e latências.</small>
        </div>`;
      atualizarBadgesAtivas();
      return;
    }

    const cards = Array.from(chamadasAtivasMap.values()).map((ch) => {
      const etapa = ch.etapa || "ouvindo";
      const m = ch.metricas_turno || {};
      const latWhisper = m.whisper_ms ? `${m.whisper_ms} ms` : "—";
      const latLlm = m.llm_ms ? `${m.llm_ms} ms` : "—";
      const latPiper = m.piper_ms ? `${m.piper_ms} ms` : "—";
      const latTotal = m.total_ms ? `${(m.total_ms / 1000).toFixed(1)} s` : "—";

      // Renderizar transcrições recentes
      const dialogos = (ch.transcricoes || []).map((t) => `
        <div class="msg-linha ${t.quem}">
          <span class="msg-autor">${t.quem === "cliente" ? "Cliente" : "Atendente IA"}</span>
          ${escapar(t.texto)}
        </div>
      `).join("") || `<p class="fraco" style="text-align:center;padding:10px;">Aguardando falas...</p>`;

      // Renderizar itens do pedido se houver
      let comandaHtml = "";
      if (ch.comanda && ch.comanda.itens && ch.comanda.itens.length > 0) {
        const itensStr = ch.comanda.itens.map((i) => `${i.quantidade}x ${i.produto}`).join(", ");
        comandaHtml = `
          <div class="chamada-comanda-resumo">
            🛒 <strong>Carrinho em montagem:</strong> ${escapar(itensStr)} | Total: <strong>${formatarDinheiro(ch.comanda.total || 0)}</strong>
          </div>`;
      }

      return `
        <article class="card-chamada-ativa" id="card-ch-${ch.id}">
          <div class="chamada-cabecalho">
            <div>
              <span class="chamada-id-titulo">Chamada #${ch.id.slice(0, 8)}</span>
              <span class="selo ${etapa}" style="margin-left:8px;">${etapa.toUpperCase()}</span>
            </div>
            <span class="chamada-duracao">Turno: <strong>#${ch.turno_atual || 0}</strong></span>
          </div>

          <div class="pipeline-status-etapas">
            <div class="etapa-item ${etapa === 'ouvindo' ? 'ativa' : ''}">1. Ouvindo</div>
            <div class="etapa-item ${etapa === 'transcrevendo' ? 'ativa' : ''}">2. Whisper</div>
            <div class="etapa-item ${etapa === 'pensando' ? 'ativa' : ''}">3. Llama</div>
            <div class="etapa-item ${etapa === 'respondendo' ? 'ativa' : ''}">4. Piper</div>
          </div>

          <div class="metricas-barra-latencias">
            <div class="metrica-chip"><span>Whisper (STT)</span><strong>${latWhisper}</strong></div>
            <div class="metrica-chip"><span>Llama 3.2 (LLM)</span><strong>${latLlm}</strong></div>
            <div class="metrica-chip"><span>Piper (TTS)</span><strong>${latPiper}</strong></div>
            <div class="metrica-chip destaque-total"><span>Total do Turno</span><strong>${latTotal}</strong></div>
          </div>

          <div class="dialogo-ao-vivo">
            ${dialogos}
          </div>

          ${comandaHtml}
        </article>`;
    });

    containerAtivas.innerHTML = cards.join("");
    atualizarBadgesAtivas();

    // Rola as caixas de diálogo para baixo
    containerAtivas.querySelectorAll(".dialogo-ao-vivo").forEach((el) => {
      el.scrollTop = el.scrollHeight;
    });
  }

  function renderizarHistorico() {
    statQtdHistorico.textContent = historicoChamadasList.length;
    if (historicoChamadasList.length === 0) {
      containerHistorico.innerHTML = `<div class="vazio-monitor"><p>Nenhuma chamada recente registrada.</p></div>`;
      return;
    }

    containerHistorico.innerHTML = historicoChamadasList.slice(0, 15).map((ch) => {
      const hora = ch.fim ? formatarQuando(ch.fim) : (ch.inicio ? formatarQuando(ch.inicio) : "—");
      const pedidoBadge = ch.pedido_id
        ? `<span class="hist-pedido-criado">✓ Pedido #${ch.pedido_id} gravado</span>`
        : `<span class="fraco">Sem pedido gravado</span>`;

      return `
        <div class="item-historico-chamada">
          <div class="hist-topo">
            <span class="hist-id">Chamada #${ch.id.slice(0, 8)}</span>
            <span class="fraco">${hora}</span>
          </div>
          <div class="hist-corpo">
            <span>Turnos realizados: <strong>${ch.turno_atual || 0}</strong></span> · ${pedidoBadge}
          </div>
        </div>`;
    }).join("");
  }

  function conectarWebSocketMonitor() {
    const protocolo = janela.location.protocol === "https:" ? "wss:" : "ws:";
    const urlWS = `${protocolo}//${janela.location.host}/api/admin/ws/monitor`;

    monitorBolinha.className = "bolinha desconectado";
    monitorStatusTexto.textContent = "Conectando ao canal em tempo real...";

    try {
      socketMonitor = new WebSocket(urlWS);
    } catch (e) {
      monitorStatusTexto.textContent = "Falha ao iniciar conexão WebSocket.";
      return;
    }

    socketMonitor.onopen = () => {
      monitorBolinha.className = "bolinha conectado";
      monitorStatusTexto.textContent = "Monitoramento ao vivo conectado";
    };

    socketMonitor.onmessage = (evento) => {
      let msg = null;
      try {
        msg = JSON.parse(evento.data);
      } catch (e) {
        return;
      }

      if (msg.tipo === "snapshot") {
        chamadasAtivasMap.clear();
        (msg.ativas || []).forEach((ch) => chamadasAtivasMap.set(ch.id, ch));
        historicoChamadasList = msg.historico || [];
        renderizarChamadasAtivas();
        renderizarHistorico();
      } else if (msg.tipo === "chamada_iniciada") {
        chamadasAtivasMap.set(msg.chamada.id, msg.chamada);
        renderizarChamadasAtivas();
      } else if (msg.tipo === "etapa_atualizada") {
        if (chamadasAtivasMap.has(msg.chamada_id)) {
          const ch = chamadasAtivasMap.get(msg.chamada_id);
          ch.etapa = msg.etapa;
          ch.turno_atual = msg.turno;
          renderizarChamadasAtivas();
        }
      } else if (msg.tipo === "transcricao") {
        if (chamadasAtivasMap.has(msg.chamada_id)) {
          const ch = chamadasAtivasMap.get(msg.chamada_id);
          ch.transcricoes = ch.transcricoes || [];
          ch.transcricoes.push(msg.registro);
          renderizarChamadasAtivas();
        }
      } else if (msg.tipo === "metricas_turno") {
        if (chamadasAtivasMap.has(msg.chamada_id)) {
          const ch = chamadasAtivasMap.get(msg.chamada_id);
          ch.metricas_turno = msg.metricas;
          renderizarChamadasAtivas();
        }
      } else if (msg.tipo === "comanda_atualizada") {
        if (chamadasAtivasMap.has(msg.chamada_id)) {
          const ch = chamadasAtivasMap.get(msg.chamada_id);
          ch.comanda = msg.comanda;
          renderizarChamadasAtivas();
        }
      } else if (msg.tipo === "chamada_encerrada") {
        chamadasAtivasMap.delete(msg.chamada.id);
        // a ligação gravou um pedido: ele já aparece para a cozinha sem esperar a próxima atualização
        if (msg.chamada.pedido_id) carregarEmAndamento();
        historicoChamadasList.unshift(msg.chamada);
        renderizarChamadasAtivas();
        renderizarHistorico();
      }
    };

    socketMonitor.onclose = () => {
      monitorBolinha.className = "bolinha desconectado";
      monitorStatusTexto.textContent = "Desconectado. Tentando reconectar em 5s...";
      setTimeout(conectarWebSocketMonitor, 5000);
    };

    socketMonitor.onerror = () => {
      socketMonitor.close();
    };
  }

  conectarWebSocketMonitor();
}

if (typeof document !== "undefined" && document.getElementById("secao-dashboard")) {
  iniciarPainel(document, window);
}
