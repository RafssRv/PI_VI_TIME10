// tela de chamada do atendente de voz.
// regra basica do protocolo: binario = audio, texto = json de controle.
// o backend de hoje morre se receber texto (o receive_bytes estoura KeyError), entao a tela
// nasce muda: so manda json depois que o servidor se apresentar com {"tipo":"pronto"}.
//
// ======================= PROTOCOLO DO WEBSOCKET /ws/falar (versao 1) =======================
// toda mensagem de controle é json com a chave "tipo". texto sem "tipo" cai no log e nao
// quebra a tela — é assim que o backend antigo, que responde "chunk guardado no backend!",
// continua funcionando.
//
// ENTRA (servidor -> tela), 9 mensagens:
//  1 {"tipo":"pronto","versao_protocolo":1}
//      primeira e obrigatoria: é ela que tira a tela do modo mudo.
//  2 {"tipo":"estado","etapa":"transcrevendo","turno":3}
//      etapa so pode ser: ouvindo | transcrevendo | pensando | respondendo | ocioso.
//      cada uma reinicia o relogio de 15 s, entao mande uma por etapa e o llama local pode
//      demorar o quanto precisar sem a tela achar que o servidor morreu.
//  3 {"tipo":"transcricao","turno":3,"quem":"cliente","texto":"duas margherita","parcial":true}
//      quem: cliente | atendente. parcial=true vale pros DOIS lados: a tela guarda um balao
//      por lado e vai reescrevendo ele (serve pro streaming de token do ollama).
//      parcial=false fecha o balao daquele lado.
//  4 {"tipo":"audio_resposta","turno":3,"formato":"audio/wav"}
//      é so o AVISO. logo depois venham 1 ou mais FRAMES BINARIOS com os pedacos do arquivo.
//      binario que chega sem esse aviso é ignorado.
//  5 {"tipo":"fim_audio"}
//      fecha os frames num arquivo so e toca. MANDE SEMPRE, mesmo com um frame unico.
//  6 {"tipo":"pedido","turno":3,
//     "cliente":{"nome":"Maria Aparecida","telefone":"19998124477"},
//     "itens":[{"produto":"Pizza Margherita","quantidade":2,"preco_unitario":"39.90",
//               "observacao":"sem cebola"}],
//     "total":"91.80","forma_pagamento":"pix","endereco_entrega":"Rua das Acácias, 120"}
//      o pedido é PLANO: itens/cliente/total/forma_pagamento/endereco_entrega ficam no nivel
//      de cima da mensagem, nao dentro de uma chave "pedido". o item usa os mesmos nomes do
//      banco e a tela calcula o subtotal (preco_unitario x quantidade).
//      forma_pagamento so aceita pix | dinheiro | cartao_credito | cartao_debito (ou null).
//  7 {"tipo":"pedido_salvo","pedido_id":42,"total":"91.80"}
//      TEM QUE VIR ANTES do chamada_encerrada, senao o resumo diz "Pedido não salvo".
//  8 {"tipo":"erro","onde":"transcricao","mensagem":"não entendi","fatal":false}
//      onde so pode ser: captura | audio | transcricao | llm | ollama | sintese | piper.
//      fatal=true derruba a chamada, fatal=false é so uma tarja de aviso.
//  9 {"tipo":"chamada_encerrada","motivo":"pedido_finalizado"}
//
// SAI (tela -> servidor), 5 mensagens + o audio:
//  1 {"tipo":"iniciar_chamada","versao_protocolo":1,"formato_audio":"audio/webm;codecs=opus","chunk_ms":250}
//  2 {"tipo":"fim_da_fala","turno":3,"duracao_ms":2100}   -> o microfone ja foi fechado aqui
//  3 {"tipo":"resposta_tocada","turno":3}                 -> a resposta tocou ate o fim
//  4 {"tipo":"timeout","turno":3}                         -> ninguem respondeu em 15 s
//  5 {"tipo":"encerrar_chamada","motivo":"cliente_desligou"}
//  + FRAMES BINARIOS: pedacos de 250 ms do microfone, so enquanto a tela esta em "ouvindo".
//  o "turno" que a tela manda é so conferencia: pode ecoar ou ignorar.
//
// DINHEIRO: sempre STRING com duas casas, feita com str(Decimal) — nunca float(). float()
// vira 79.8 e 91, que nao é formato de dinheiro. a tela aceita numero por seguranca, mas
// quem manda string nao perde centavo.
// ==========================================================================================

// ---------- constantes ----------
const URL_WEBSOCKET = `ws://${location.hostname}:8000/ws/falar`;
const TAMANHO_CHUNK_MS = 250;       // de quanto em quanto tempo o gravador entrega um pedaco
const VERSAO_PROTOCOLO = 1;
const ESPERA_RESPOSTA_MS = 15000;   // se a resposta nao vier, reabre o microfone sozinho
const ESPERA_SOCKET_MS = 5000;      // tempo pro websocket abrir
const ESPERA_FIM_AUDIO_MS = 800;    // se o servidor esquecer o fim_audio, toca o que chegou
const ESPERA_PEDIDO_SALVO_MS = 1200; // janela pro pedido_salvo atrasado entrar no resumo
const FALA_MAXIMA_MS = 15000;       // fala contínua demais: fecha o turno na marra
const LIMITE_LOG = 200;
const RMS_FALA = 0.05;              // acima disso a gente considera que tem voz
const RMS_SILENCIO = 0.02;          // abaixo disso a gente considera silencio
const MS_PARA_CONFIRMAR_FALA = 300;
const MS_DE_SILENCIO = 1200;

// textos de cada estado da chamada, num lugar so
const ESTADOS = {
  ocioso:      { rotulo: "Chamada não iniciada", sublinha: "clique em LIGAR e fale normalmente", botao: "LIGAR" },
  conectando:  { rotulo: "Chamando…",            sublinha: "abrindo o microfone e a conexão",    botao: "CONECTANDO" },
  ouvindo:     { rotulo: "Pode falar",           sublinha: "seu microfone está ligado",          botao: "DESLIGAR" },
  processando: { rotulo: "Anotando seu pedido…", sublinha: "microfone pausado",                  botao: "DESLIGAR" },
  falando:     { rotulo: "Atendente falando",    sublinha: "seu microfone fica desligado até ele terminar", botao: "DESLIGAR" },
  encerrada:   { rotulo: "Chamada encerrada",    sublinha: "",                                   botao: "LIGAR DE NOVO" },
  erro:        { rotulo: "Não deu certo",        sublinha: "",                                   botao: "TENTAR DE NOVO" }
};

const PAGAMENTOS = {
  pix: "Pix",
  dinheiro: "Dinheiro",
  cartao_credito: "Cartão de crédito",
  cartao_debito: "Cartão de débito"
};

const ESTADOS_EM_CHAMADA = ["conectando", "ouvindo", "processando", "falando"];

// ---------- elementos da tela ----------
const faixaDemo = document.getElementById("faixa-demo");
const botaoSairDemo = document.getElementById("botao-sair-demo");
const timer = document.getElementById("timer");
const bolinha = document.getElementById("bolinha");
const textoStatus = document.getElementById("texto-status");
const tarjaErro = document.getElementById("tarja-erro");
const tarjaErroTexto = document.getElementById("tarja-erro-texto");
const tarjaErroBotao = document.getElementById("tarja-erro-botao");
const barrasMic = document.getElementById("barras-mic");
const legendaNivel = document.getElementById("legenda-nivel");
const rotuloEstado = document.getElementById("rotulo-estado");
const sublinhaEstado = document.getElementById("sublinha-estado");
const conversa = document.getElementById("conversa");
const botaoChamada = document.getElementById("botao-chamada");
const textoBotao = document.getElementById("texto-botao");
const botaoDemo = document.getElementById("botao-demo");
const seloSimulacao = document.getElementById("selo-simulacao");
const comandaCliente = document.getElementById("comanda-cliente");
const comandaItens = document.getElementById("comanda-itens");
const comandaAviso = document.getElementById("comanda-aviso");
const comandaPagamento = document.getElementById("comanda-pagamento");
const comandaEntrega = document.getElementById("comanda-entrega");
const comandaTotal = document.getElementById("comanda-total");
const resumo = document.getElementById("resumo");
const resumoTitulo = document.getElementById("resumo-titulo");
const resumoLinhas = document.getElementById("resumo-linhas");
const resumoCliente = document.getElementById("resumo-cliente");
const resumoItens = document.getElementById("resumo-itens");
const resumoPagamento = document.getElementById("resumo-pagamento");
const resumoEntrega = document.getElementById("resumo-entrega");
const resumoTotal = document.getElementById("resumo-total");
const resumoLigar = document.getElementById("resumo-ligar");
const resumoFechar = document.getElementById("resumo-fechar");
const tempoTurno = document.getElementById("tempo-turno");
const log = document.getElementById("log");
const player = document.getElementById("player");
const audioResposta = document.getElementById("audio-resposta");
const caixasEtapa = [
  null,
  document.getElementById("etapa-1"),
  document.getElementById("etapa-2"),
  document.getElementById("etapa-3"),
  document.getElementById("etapa-4")
];

// ---------- variaveis de controle ----------
let estadoAtual = "ocioso";
let socket = null;
let protocoloNovo = false;     // so vira true quando o backend mandar json com "tipo"
let fechamosOSocket = false;

let gravador = null;
let stream = null;
let pedacos = [];

let contextoAudio = null;
let analisador = null;
let dadosNivel = null;
let loopNivel = 0;

let houveFala = false;
let inicioDaFala = 0;
let inicioDoSilencio = 0;

let turno = 0;
let tempoInicioTurno = 0;
let relogioSeguranca = 0;
let esperandoAudio = false;
let pedacosResposta = [];      // frames binarios do piper ate chegar o fim_audio
let relogioFimAudio = 0;
let formatoRespostaEsperado = "audio/wav";
let urlRespostaAnterior = "";
let idFala = 0;                // numera cada reproducao: so a fala atual reabre o microfone

let intervaloTimer = null;
let segundos = 0;
let duracaoFinal = "00:00";

let ultimoPedido = null;
let pedidoSalvoId = null;
let chavesDosItens = [];       // pra saber quais itens sao novos neste turno
let falaParcial = { cliente: null, atendente: null };   // um balao em reconhecimento por lado
let erroEhFatal = false;

let modoDemo = false;
let geracaoDemo = 0;           // cada rodarDemo pega um numero; o roteiro velho morre sozinho

// ---------- log ----------
let ultimaLinhaLog = null;
let ultimaMensagemLog = "";
let repeticoesLog = 1;

function escreverLog(mensagem) {
  const hora = new Date().toLocaleTimeString();

  // o backend antigo manda "chunk guardado no backend!" a cada 250 ms: junta tudo numa linha so
  if (mensagem === ultimaMensagemLog && ultimaLinhaLog) {
    repeticoesLog++;
    ultimaLinhaLog.textContent = `[${hora}] ${mensagem} (×${repeticoesLog})`;
    return;
  }

  const item = document.createElement("li");
  item.textContent = `[${hora}] ${mensagem}`;
  log.prepend(item);
  ultimaLinhaLog = item;
  ultimaMensagemLog = mensagem;
  repeticoesLog = 1;

  while (log.children.length > LIMITE_LOG) {
    log.lastElementChild.remove();
  }
  console.log(mensagem);
}

// ---------- estado da tela ----------
function definirEstado(nome, sublinha) {
  const dados = ESTADOS[nome];
  if (!dados) {
    escreverLog("estado desconhecido pedido pela tela: " + nome);
    return;
  }

  estadoAtual = nome;
  document.body.dataset.estado = nome;
  rotuloEstado.textContent = dados.rotulo;

  let textoSublinha = sublinha === undefined ? dados.sublinha : sublinha;
  if (modoDemo && nome === "falando") {
    textoSublinha = dados.sublinha + " — voz do navegador, não é o Piper";
  }
  sublinhaEstado.textContent = textoSublinha;

  textoBotao.textContent = dados.botao;
  botaoChamada.disabled = nome === "conectando";

  const emChamada = nome === "ouvindo" || nome === "processando" || nome === "falando";
  botaoChamada.classList.toggle("desligar", emChamada);
  botaoChamada.classList.toggle("ligar", !emChamada && nome !== "conectando");

  // a demo continua a mao em ocioso, encerrada e erro: so some durante a chamada de verdade
  botaoDemo.hidden = estaEmChamada() || modoDemo;
  legendaNivel.hidden = !(modoDemo && nome === "ouvindo");
}

function mudarConexao(classe, texto) {
  bolinha.className = "bolinha " + classe;
  textoStatus.textContent = texto;
}

function estaEmChamada() {
  return ESTADOS_EM_CHAMADA.indexOf(estadoAtual) !== -1;
}

// ---------- timer da chamada ----------
function iniciarTimer() {
  clearInterval(intervaloTimer);
  segundos = 0;
  timer.textContent = "00:00";
  intervaloTimer = setInterval(() => {
    segundos++;
    const min = String(Math.floor(segundos / 60)).padStart(2, "0");
    const seg = String(segundos % 60).padStart(2, "0");
    timer.textContent = `${min}:${seg}`;
  }, 1000);
}

function pararTimer() {
  clearInterval(intervaloTimer);
  intervaloTimer = null;
  duracaoFinal = timer.textContent;
}

// ---------- etapas do rodape ----------
let etapaAtual = 0;
let inicioEtapa = 0;

function resetarEtapas() {
  etapaAtual = 0;
  inicioEtapa = 0;
  for (let i = 1; i <= 4; i++) {
    caixasEtapa[i].className = "etapa";
    caixasEtapa[i].querySelector(".etapa-tempo").textContent = "aguardando";
  }
  tempoTurno.textContent = "—";
}

function marcarEtapa(numero) {
  // fecha a anterior guardando quanto ela levou
  if (etapaAtual && caixasEtapa[etapaAtual] && etapaAtual !== numero) {
    const anterior = caixasEtapa[etapaAtual];
    anterior.classList.remove("ativa");
    anterior.classList.add("feita");
    anterior.querySelector(".etapa-tempo").textContent = emSegundos(Date.now() - inicioEtapa);
  }

  if (!numero || !caixasEtapa[numero]) {
    etapaAtual = 0;
    return;
  }

  if (etapaAtual !== numero) {
    inicioEtapa = Date.now();
  }
  etapaAtual = numero;

  const caixa = caixasEtapa[numero];
  caixa.className = "etapa ativa";
  caixa.querySelector(".etapa-tempo").textContent = numero === 1 ? "OUVINDO AGORA" : "…";
}

function marcarEtapaFalhou(onde) {
  const mapa = { captura: 1, audio: 1, transcricao: 2, llm: 3, ollama: 3, sintese: 4, piper: 4 };
  const numero = mapa[onde] || etapaAtual;
  if (!numero || !caixasEtapa[numero]) return;
  const caixa = caixasEtapa[numero];
  caixa.className = "etapa falhou";
  caixa.querySelector(".etapa-tempo").textContent = "✕ FALHOU";
}

function emSegundos(ms) {
  return (ms / 1000).toFixed(1).replace(".", ",") + " s";
}

// ---------- conexao ----------
function conectar() {
  return new Promise((resolve, reject) => {
    mudarConexao("conectando", "conectando");
    fechamosOSocket = false;
    let abriu = false;   // backend desligado fecha em milissegundos, sem nunca ter aberto

    try {
      socket = new WebSocket(URL_WEBSOCKET);
    } catch (erro) {
      reject(erro);
      return;
    }

    const meuSocket = socket;
    meuSocket.binaryType = "blob";

    meuSocket.onopen = () => {
      abriu = true;
      mudarConexao("conectado", "conectado");
      escreverLog("websocket conectado (modo mudo: só binário até o servidor se apresentar)");
      resolve();
    };

    meuSocket.onmessage = tratarMensagem;

    meuSocket.onerror = () => {
      escreverLog("erro no websocket (o backend está rodando?)");
    };

    meuSocket.onclose = () => {
      mudarConexao("desconectado", "desconectado");
      escreverLog("websocket fechado");
      // se nem chegou a abrir, a culpa nao é de "queda no meio da chamada": rejeita e deixa
      // o ligar() dizer que o backend nao está rodando
      if (!abriu) {
        reject(new Error("o websocket não abriu"));
        return;
      }
      if (!fechamosOSocket && estaEmChamada()) {
        mostrarErro("A conexão com o servidor caiu no meio da chamada.", true);
      }
    };

    // se nao abrir em 5 s, desiste e avisa
    setTimeout(() => {
      if (meuSocket.readyState !== WebSocket.OPEN) {
        try { meuSocket.close(); } catch (erro) { /* ja era */ }
        reject(new Error("o websocket não abriu"));
      }
    }, ESPERA_SOCKET_MS);
  });
}

// so manda texto se o servidor ja provou que entende o protocolo novo
function enviarTexto(obj) {
  if (!protocoloNovo) return;
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify(obj));
}

function tratarMensagem(evento) {
  // binario: so vale quando a gente avisou que vinha audio de resposta.
  // o piper pode mandar a resposta em varios pedacos, entao a gente junta todos e so toca
  // no fim_audio (o relogio abaixo é a rede pra servidor que esquece de mandar o fim_audio)
  if (typeof evento.data !== "string") {
    if (esperandoAudio) {
      pedacosResposta.push(evento.data);
      clearTimeout(relogioFimAudio);
      relogioFimAudio = setTimeout(fecharAudioResposta, ESPERA_FIM_AUDIO_MS);
    } else {
      escreverLog("chegou binário sem aviso de audio_resposta, ignorado");
    }
    return;
  }

  let obj = null;
  try {
    obj = JSON.parse(evento.data);
  } catch (erro) {
    obj = null;
  }

  // texto que nao eh json com "tipo" cai no log e para por aqui (ex.: "chunk guardado no backend!")
  if (!obj || typeof obj !== "object" || !obj.tipo) {
    escreverLog("backend: " + evento.data);
    return;
  }

  if (!protocoloNovo) {
    protocoloNovo = true;
    escreverLog("o servidor fala o protocolo novo, saindo do modo mudo");
    comandaAviso.hidden = true;
    enviarTexto({
      tipo: "iniciar_chamada",
      versao_protocolo: VERSAO_PROTOCOLO,
      formato_audio: formatoEmUso(),
      chunk_ms: TAMANHO_CHUNK_MS
    });
  }

  aplicarMensagem(obj);
}

// o switch unico: a demo e o backend real passam os dois por aqui
function aplicarMensagem(obj) {
  switch (obj.tipo) {
    case "pronto":
      escreverLog("servidor pronto, protocolo versão " + obj.versao_protocolo);
      break;

    case "estado":
      aplicarEtapa(obj.etapa);
      break;

    case "fim_audio":
      fecharAudioResposta();
      break;

    case "transcricao":
      mostrarTranscricao(obj.quem, obj.texto, obj.parcial === true);
      break;

    case "audio_resposta":
      esperandoAudio = true;
      pedacosResposta = [];
      formatoRespostaEsperado = obj.formato || "audio/wav";
      armarRelogioSeguranca();   // o audio ainda vem por ai, o servidor continua vivo
      marcarEtapa(4);
      break;

    case "pedido":
      ultimoPedido = obj;
      desenharPedido(obj, comandaItens);
      break;

    case "pedido_salvo":
      pedidoSalvoId = obj.pedido_id;
      comandaAviso.hidden = true;
      escreverLog(`pedido ${obj.pedido_id} salvo no banco, total ${obj.total}`);
      break;

    case "erro":
      mostrarErro(obj.mensagem || "o servidor não explicou o que deu errado.", obj.fatal === true);
      marcarEtapaFalhou(obj.onde);
      break;

    case "chamada_encerrada": {
      escreverLog("servidor encerrou a chamada: " + (obj.motivo || "sem motivo"));
      // o socket fica aberto mais um instante: se o backend salvar o pedido DEPOIS de avisar
      // que a chamada acabou, o pedido_salvo atrasado ainda entra no resumo
      encerrar(null, "encerrada", true);
      const socketDaChamada = socket;
      setTimeout(() => {
        fecharSocket(socketDaChamada);
        if (estadoAtual !== "encerrada") return;   // o usuário já ligou de novo, deixa quieto
        abrirResumo({ pedido: ultimoPedido, pedido_id: pedidoSalvoId, duracao: duracaoFinal });
      }, ESPERA_PEDIDO_SALVO_MS);
      break;
    }

    default:
      escreverLog("mensagem desconhecida do backend: " + JSON.stringify(obj));
  }
}

function aplicarEtapa(etapa) {
  switch (etapa) {
    case "ouvindo":
      // meia-duplex manda: se o atendente ainda esta falando, o microfone continua fechado
      if (estadoAtual === "falando") {
        escreverLog("servidor pediu 'ouvindo' com a resposta tocando, ignorado");
        return;
      }
      // o microfone está pausado desde o fim_da_fala: sem reabrir aqui a tela diria
      // "pode falar" com o microfone morto (acontece quando o servidor manda um erro
      // não fatal e volta pra ouvindo sem nenhum audio de resposta)
      clearTimeout(relogioSeguranca);
      retomarCaptura();
      marcarEtapa(1);
      definirEstado("ouvindo");
      break;
    case "transcrevendo":
      armarRelogioSeguranca();
      marcarEtapa(2);
      definirEstado("processando");
      break;
    case "pensando":
      armarRelogioSeguranca();
      marcarEtapa(3);
      definirEstado("processando");
      break;
    case "respondendo":
      armarRelogioSeguranca();
      marcarEtapa(4);
      definirEstado("processando");
      break;
    case "ocioso":
      clearTimeout(relogioSeguranca);
      marcarEtapa(0);
      break;
    default:
      escreverLog("etapa desconhecida: " + etapa);
  }
}

// ---------- conversa ----------
function limparConversa() {
  conversa.innerHTML = "";
  const vazia = document.createElement("p");
  vazia.className = "conversa-vazia";
  vazia.textContent = "A conversa aparece aqui enquanto vocês falam.";
  conversa.appendChild(vazia);
  falaParcial = { cliente: null, atendente: null };
}

function criarBalao(quem, parcial) {
  const bloco = document.createElement("div");
  bloco.className = "fala fala-" + quem + (parcial ? " parcial" : "");

  const rotulo = document.createElement("span");
  rotulo.className = "quem";
  rotulo.textContent = quem === "cliente" ? "VOCÊ" : "ATENDENTE";
  bloco.appendChild(rotulo);

  if (modoDemo) {
    const etiqueta = document.createElement("span");
    etiqueta.className = "etiqueta-demo";
    etiqueta.textContent = "DEMO";
    bloco.appendChild(etiqueta);
  }

  const texto = document.createElement("p");
  texto.className = "texto";
  bloco.appendChild(texto);
  return bloco;
}

function mostrarTranscricao(quem, texto, parcial) {
  if (quem !== "cliente" && quem !== "atendente") {
    escreverLog("transcrição com 'quem' desconhecido: " + quem);
    return;
  }

  const vazia = conversa.querySelector(".conversa-vazia");
  if (vazia) vazia.remove();

  // parcial: um balao so, em italico, que vai sendo atualizado.
  // vale pros dois lados: o llama respondendo em streaming também manda parcial
  if (parcial) {
    if (!falaParcial[quem]) {
      falaParcial[quem] = criarBalao(quem, true);
      conversa.appendChild(falaParcial[quem]);
    }
    falaParcial[quem].querySelector(".texto").textContent = texto + "…";
    conversa.scrollTop = conversa.scrollHeight;
    return;
  }

  if (falaParcial[quem]) {
    falaParcial[quem].classList.remove("parcial");
    falaParcial[quem].querySelector(".texto").textContent = texto;
    falaParcial[quem] = null;
  } else {
    const bloco = criarBalao(quem, false);
    bloco.querySelector(".texto").textContent = texto;
    conversa.appendChild(bloco);
  }

  conversa.scrollTop = conversa.scrollHeight;
}

// ---------- comanda ----------
// o combinado é string com duas casas (str(Decimal)), mas aceita numero também:
// preço sumir da tela é pior que arredondar
function formatarDinheiro(valor) {
  const numero = typeof valor === "string" ? Number(valor.trim()) : Number(valor);
  if (valor === null || valor === undefined || valor === "" || !Number.isFinite(numero)) {
    escreverLog("valor de dinheiro fora do formato esperado: " + valor);
    return "—";
  }
  const partes = numero.toFixed(2).split(".");
  const inteiro = partes[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `R$ ${inteiro},${partes[1]}`;
}

// o banco manda preco_unitario e quantidade; o subtotal quem faz é a tela
function calcularSubtotal(item) {
  const preco = Number(item.preco_unitario);
  const quantidade = Number(item.quantidade);
  if (!Number.isFinite(preco) || !Number.isFinite(quantidade)) return null;
  return preco * quantidade;
}

function formatarPagamento(valor) {
  if (!valor) return "a combinar";
  if (PAGAMENTOS[valor]) return PAGAMENTOS[valor];
  escreverLog("forma de pagamento que o banco não aceita: " + valor);
  return "a combinar";
}

function formatarTelefone(valor) {
  const digitos = String(valor || "").replace(/\D/g, "");
  if (digitos.length === 11) return `(${digitos.slice(0, 2)}) ${digitos.slice(2, 7)}-${digitos.slice(7)}`;
  if (digitos.length === 10) return `(${digitos.slice(0, 2)}) ${digitos.slice(2, 6)}-${digitos.slice(6)}`;
  return digitos;
}

function limparComanda() {
  chavesDosItens = [];
  ultimoPedido = null;
  desenharPedido({ itens: [] }, comandaItens);
}

// desenha a mesma comanda na tela da chamada e no resumo do fim: so muda o destino
function desenharPedido(pedido, destino) {
  const naComanda = destino === comandaItens;
  const itens = pedido && Array.isArray(pedido.itens) ? pedido.itens : [];

  destino.innerHTML = "";

  if (itens.length === 0) {
    const linha1 = document.createElement("p");
    linha1.className = "comanda-vazia";
    linha1.textContent = "Ainda não anotei nada.";
    const linha2 = document.createElement("p");
    linha2.className = "comanda-vazia fraca";
    linha2.textContent = "O que você pedir vai aparecer aqui.";
    destino.appendChild(linha1);
    destino.appendChild(linha2);
  }

  const chavesAgora = [];

  itens.forEach((item) => {
    const chave = `${item.produto}|${item.quantidade}|${item.observacao || ""}`;
    chavesAgora.push(chave);
    const ehNovo = naComanda && chavesDosItens.indexOf(chave) === -1;

    const linha = document.createElement("div");
    linha.className = "item" + (ehNovo ? " novo" : "");

    const quantidade = document.createElement("span");
    quantidade.className = "quantidade";
    quantidade.textContent = `${item.quantidade}×`;
    linha.appendChild(quantidade);

    const miolo = document.createElement("div");
    miolo.className = "miolo";

    const produto = document.createElement("div");
    produto.className = "produto";
    produto.textContent = item.produto;
    if (ehNovo) {
      const selo = document.createElement("span");
      selo.className = "selo-novo";
      selo.textContent = "NOVO";
      produto.appendChild(selo);
      // o destaque sai sozinho depois de 4 s
      setTimeout(() => {
        linha.classList.remove("novo");
        selo.remove();
      }, 4000);
    }
    miolo.appendChild(produto);

    if (item.observacao) {
      const observacao = document.createElement("div");
      observacao.className = "observacao";
      observacao.textContent = item.observacao;
      miolo.appendChild(observacao);
    }
    linha.appendChild(miolo);

    const subtotal = document.createElement("span");
    subtotal.className = "subtotal";
    subtotal.textContent = formatarDinheiro(calcularSubtotal(item));
    linha.appendChild(subtotal);

    destino.appendChild(linha);
  });

  if (naComanda) {
    chavesDosItens = chavesAgora;
  }

  // cliente, pagamento, entrega e total mudam de lugar conforme o destino
  const alvoCliente = naComanda ? comandaCliente : resumoCliente;
  const alvoPagamento = naComanda ? comandaPagamento : resumoPagamento;
  const alvoEntrega = naComanda ? comandaEntrega : resumoEntrega;
  const alvoTotal = naComanda ? comandaTotal : resumoTotal;

  const cliente = pedido ? pedido.cliente : null;
  if (cliente && cliente.nome) {
    const telefone = formatarTelefone(cliente.telefone);
    alvoCliente.textContent = "Cliente: " + cliente.nome + (telefone ? " · " + telefone : "");
  } else {
    alvoCliente.textContent = "Cliente: ainda não identificado";
  }

  alvoPagamento.textContent = formatarPagamento(pedido ? pedido.forma_pagamento : null);
  alvoEntrega.textContent = (pedido && pedido.endereco_entrega) ? pedido.endereco_entrega : "a confirmar";
  alvoTotal.textContent = (pedido && pedido.total) ? formatarDinheiro(pedido.total) : "R$ 0,00";
}

// ---------- resumo do fim da chamada ----------
function abrirResumo(dados) {
  const pedido = dados.pedido || { itens: [] };
  resumoTitulo.textContent = dados.pedido_id ? "Pedido registrado" : "Pedido não salvo";

  const linhas = [];
  if (dados.pedido_id) linhas.push("Pedido nº " + dados.pedido_id);
  linhas.push("Duração da chamada: " + (dados.duracao || "00:00"));
  resumoLinhas.textContent = linhas.join(" · ");

  desenharPedido(pedido, resumoItens);
  resumo.hidden = false;
  resumoFechar.focus();
}

function fecharResumo() {
  resumo.hidden = true;
}

// ---------- erros ----------
function mostrarErro(mensagem, fatal) {
  erroEhFatal = fatal === true;
  tarjaErroTexto.textContent = mensagem;
  tarjaErroBotao.textContent = erroEhFatal ? "Tentar de novo" : "Fechar aviso";
  tarjaErro.hidden = false;
  escreverLog((erroEhFatal ? "erro fatal: " : "aviso: ") + mensagem);

  if (!erroEhFatal) return;

  // se o socket nem existia (erro de microfone, por exemplo), nao adianta culpar a conexao
  mudarConexao("erro", socket ? "erro de conexão" : "desconectado");
  encerrar(null, "erro");
  sublinhaEstado.textContent = mensagem;   // a sublinha do círculo repete o erro em texto
  comandaAviso.textContent = "Este pedido ainda não foi salvo.";
  comandaAviso.hidden = false;
}

function esconderTarjaErro() {
  tarjaErro.hidden = true;
}

function mensagemDeMicrofone(erro) {
  const nome = erro && erro.name ? erro.name : "";
  if (nome === "NotAllowedError" || nome === "SecurityError" || nome === "PermissionDeniedError") {
    return "Não consegui usar o microfone. Clique no cadeado ao lado do endereço e permita o microfone para este site.";
  }
  if (nome === "NotFoundError" || nome === "DevicesNotFoundError") {
    return "Nenhum microfone foi encontrado neste computador.";
  }
  return "Não consegui usar o microfone. " + (erro && erro.message ? erro.message : "");
}

// ---------- captura de audio ----------
function escolherFormato() {
  // o whisper precisa saber o container, entao a gente escolhe e avisa o backend
  const preferidos = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
  for (let i = 0; i < preferidos.length; i++) {
    if (MediaRecorder.isTypeSupported(preferidos[i])) return preferidos[i];
  }
  return "";
}

function formatoEmUso() {
  // vale o mimeType que o gravador realmente usou, nao o que a gente pediu
  if (gravador && gravador.mimeType) return gravador.mimeType;
  return escolherFormato() || "desconhecido";
}

async function iniciarCaptura() {
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
  });

  const formato = escolherFormato();
  gravador = formato ? new MediaRecorder(stream, { mimeType: formato }) : new MediaRecorder(stream);
  pedacos = [];
  const formatoReal = formatoEmUso();   // guarda agora, o gravador some quando desligar
  escreverLog("gravando em " + formatoReal);

  gravador.ondataavailable = (evento) => {
    if (!evento.data || evento.data.size === 0) return;
    pedacos.push(evento.data);
    // binario so sai com o microfone aberto: a resposta do atendente nunca volta pro backend
    if (estadoAtual !== "ouvindo") return;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(evento.data);
    }
  };

  gravador.onstop = () => {
    if (pedacos.length > 0) {
      const audioCompleto = new Blob(pedacos, { type: formatoReal });
      player.src = URL.createObjectURL(audioCompleto);
      escreverLog(`gravação finalizada (${(audioCompleto.size / 1024).toFixed(1)} KB)`);
    }
    pararTracks();
  };

  gravador.start(TAMANHO_CHUNK_MS);
  prepararMedidor();
}

function pararTracks() {
  // solta o microfone de verdade: sem isso o icone de gravando fica aceso no navegador
  if (!stream) return;
  stream.getTracks().forEach((track) => track.stop());
  stream = null;
}

function pausarCaptura() {
  // cinto e suspensorio: pause() para de emitir chunks, enabled=false garante que nada entra
  if (gravador && gravador.state === "recording") {
    try { gravador.pause(); } catch (erro) { escreverLog("não consegui pausar o gravador"); }
  }
  if (stream) {
    stream.getAudioTracks().forEach((track) => { track.enabled = false; });
  }
}

function retomarCaptura() {
  if (stream) {
    stream.getAudioTracks().forEach((track) => { track.enabled = true; });
  }
  if (gravador && gravador.state === "paused") {
    try { gravador.resume(); } catch (erro) { escreverLog("não consegui retomar o gravador"); }
  }
}

function prepararMedidor() {
  try {
    const Contexto = window.AudioContext || window.webkitAudioContext;
    contextoAudio = new Contexto();
    const fonte = contextoAudio.createMediaStreamSource(stream);
    analisador = contextoAudio.createAnalyser();
    analisador.fftSize = 1024;
    dadosNivel = new Uint8Array(analisador.fftSize);
    fonte.connect(analisador);
  } catch (erro) {
    escreverLog("não consegui medir o nível do microfone: " + erro.message);
    analisador = null;
  }
  if (!loopNivel) medirNivel();
}

function pararMedicao() {
  if (loopNivel) {
    cancelAnimationFrame(loopNivel);
    loopNivel = 0;
  }
  analisador = null;
  if (contextoAudio) {
    try { contextoAudio.close(); } catch (erro) { /* ja fechou */ }
    contextoAudio = null;
  }
  desenharBarras(0);
}

function medirNivel() {
  loopNivel = requestAnimationFrame(medirNivel);
  const agora = Date.now();
  let nivel = 0;

  if (modoDemo) {
    // onda sintetica: na demo nao existe microfone aberto
    nivel = estadoAtual === "ouvindo"
      ? 0.18 + 0.2 * Math.abs(Math.sin(agora / 210)) + 0.1 * Math.abs(Math.sin(agora / 70))
      : 0;
  } else if (analisador && dadosNivel) {
    analisador.getByteTimeDomainData(dadosNivel);
    let soma = 0;
    for (let i = 0; i < dadosNivel.length; i++) {
      const v = (dadosNivel[i] - 128) / 128;
      soma += v * v;
    }
    nivel = Math.sqrt(soma / dadosNivel.length);
  }

  desenharBarras(nivel);

  if (!modoDemo && estadoAtual === "ouvindo") {
    vigiarSilencio(nivel, agora);
  }
}

function desenharBarras(nivel) {
  const barras = barrasMic.children;
  for (let i = 0; i < barras.length; i++) {
    const peso = 0.5 + 0.5 * Math.sin((i + 1) * 1.1 + Date.now() / 120);
    const altura = 1 + Math.min(nivel * 14, 4.5) * peso;
    barras[i].style.transform = "scaleY(" + altura.toFixed(2) + ")";
  }
}

// detecta fim da fala: falou por 300 ms e depois ficou 1,2 s em silencio
function vigiarSilencio(nivel, agora) {
  if (nivel > RMS_FALA) {
    if (!inicioDaFala) inicioDaFala = agora;
    if (agora - inicioDaFala >= MS_PARA_CONFIRMAR_FALA) houveFala = true;
    inicioDoSilencio = 0;
    if (houveFala && agora - inicioDaFala >= FALA_MAXIMA_MS) {
      escreverLog("15 s de fala contínua, fechando o turno à força");
      fimDaFala(agora - inicioDaFala);
    }
    return;
  }

  if (nivel < RMS_SILENCIO) {
    if (!houveFala) {
      inicioDaFala = 0;
      return;
    }
    if (!inicioDoSilencio) inicioDoSilencio = agora;
    if (agora - inicioDoSilencio >= MS_DE_SILENCIO) {
      fimDaFala(agora - inicioDaFala);
    }
  }
}

function fimDaFala(duracaoMs) {
  houveFala = false;
  inicioDaFala = 0;
  inicioDoSilencio = 0;

  // backend antigo nao entende fim_da_fala, entao a tela nao finge pipeline: so anota
  if (!protocoloNovo) {
    escreverLog("fim da fala detectado (não enviado: backend antigo)");
    return;
  }

  pausarCaptura();   // fecha o microfone antes de qualquer outra coisa
  turno++;
  tempoInicioTurno = Date.now();
  enviarTexto({ tipo: "fim_da_fala", turno: turno, duracao_ms: Math.round(duracaoMs) });
  marcarEtapa(2);
  definirEstado("processando");
  armarRelogioSeguranca();
}

// rede de seguranca do turno: cada mensagem de estado do servidor reinicia esse relogio,
// entao o llama pode demorar o quanto precisar sem a tela desistir no meio
function armarRelogioSeguranca() {
  clearTimeout(relogioSeguranca);
  relogioSeguranca = setTimeout(() => {
    escreverLog("resposta não chegou em 15 s, reabrindo o microfone");
    mostrarErro("O servidor demorou demais para responder. Pode falar de novo.", false);
    voltarAOuvir(true);
  }, ESPERA_RESPOSTA_MS);
}

// junta os frames binarios num arquivo so e manda tocar
function fecharAudioResposta() {
  clearTimeout(relogioFimAudio);
  if (!esperandoAudio) return;
  esperandoAudio = false;

  const pedacos = pedacosResposta;
  pedacosResposta = [];
  if (pedacos.length === 0) {
    escreverLog("fim_audio sem nenhum frame binário, nada pra tocar");
    voltarAOuvir(true);
    return;
  }
  tocarResposta(new Blob(pedacos, { type: formatoRespostaEsperado }));
}

function tocarResposta(blob) {
  clearTimeout(relogioSeguranca);
  pausarCaptura();   // garantia: a resposta nunca toca com o microfone aberto

  // numera a fala: trocar o src cancela a play() anterior com AbortError, e o catch dela
  // reabriria o microfone no meio desta aqui. so o dono da fala atual reabre o microfone
  const minhaFala = ++idFala;

  if (urlRespostaAnterior) URL.revokeObjectURL(urlRespostaAnterior);
  urlRespostaAnterior = URL.createObjectURL(blob);
  audioResposta.src = urlRespostaAnterior;

  marcarEtapa(4);
  definirEstado("falando");

  audioResposta.onended = () => {
    if (minhaFala !== idFala) return;
    voltarAOuvir();
  };
  audioResposta.onerror = () => {
    if (minhaFala !== idFala) return;
    escreverLog("não consegui tocar a resposta do servidor");
    voltarAOuvir();
  };

  const tocando = audioResposta.play();
  if (tocando && tocando.catch) {
    tocando.catch((erro) => {
      if (minhaFala !== idFala) return;   // essa fala foi trocada por outra, deixa a nova
      escreverLog("o navegador não deixou tocar a resposta: " + erro.message);
      voltarAOuvir();
    });
  }
}

// so aqui o microfone volta a ouvir: fim do audio, falha ao tocar ou timeout.
// porTimeout=true quando nenhuma resposta chegou a tocar
function voltarAOuvir(porTimeout) {
  clearTimeout(relogioSeguranca);
  if (!estaEmChamada()) return;

  retomarCaptura();
  // resposta_tocada só vale quando uma resposta tocou mesmo
  enviarTexto({ tipo: porTimeout === true ? "timeout" : "resposta_tocada", turno: turno });

  if (tempoInicioTurno) {
    tempoTurno.textContent = emSegundos(Date.now() - tempoInicioTurno);
    tempoInicioTurno = 0;
  }

  marcarEtapa(1);
  definirEstado("ouvindo");
}

// ---------- ligar e desligar ----------
async function ligar() {
  esconderTarjaErro();
  fecharResumo();
  limparConversa();
  limparComanda();
  resetarEtapas();
  comandaAviso.hidden = true;

  turno = 0;
  pedidoSalvoId = null;
  protocoloNovo = false;
  esperandoAudio = false;
  pedacosResposta = [];
  houveFala = false;
  inicioDaFala = 0;
  inicioDoSilencio = 0;

  if (!navigator.mediaDevices || !window.MediaRecorder) {
    mostrarErro("Este navegador não grava áudio. Use o Chrome ou o Edge.", true);
    return;
  }

  definirEstado("conectando");
  iniciarTimer();

  try {
    await iniciarCaptura();
  } catch (erro) {
    pararTimer();
    mostrarErro(mensagemDeMicrofone(erro), true);
    return;
  }

  try {
    await conectar();
  } catch (erro) {
    pararTimer();
    mostrarErro("Não consegui falar com o servidor. Confira se o backend está rodando em http://localhost:8000.", true);
    return;
  }

  // enquanto o servidor nao se apresentar, a comanda diz na cara que isso aqui é protótipo
  if (!protocoloNovo) {
    comandaAviso.textContent = "O servidor ainda não envia o pedido — você está vendo o protótipo.";
    comandaAviso.hidden = false;
  }

  marcarEtapa(1);
  definirEstado("ouvindo");
}

// motivo = null quando quem encerrou foi o servidor (ou um erro): aí não manda encerrar_chamada.
// manterSocket = true deixa o websocket aberto mais um pouco (quem fecha é quem chamou)
function encerrar(motivo, estadoFinal, manterSocket) {
  pararDemo();
  clearTimeout(relogioSeguranca);
  clearTimeout(relogioFimAudio);
  pararMedicao();
  esperandoAudio = false;
  pedacosResposta = [];
  marcarEtapa(0);

  try { audioResposta.pause(); } catch (erro) { /* nem estava tocando */ }

  if (gravador && gravador.state !== "inactive") {
    try { gravador.stop(); } catch (erro) { pararTracks(); }
  } else {
    pararTracks();
  }
  gravador = null;

  if (motivo) enviarTexto({ tipo: "encerrar_chamada", motivo: motivo });
  if (!manterSocket) fecharSocket();

  pararTimer();
  definirEstado(estadoFinal || "encerrada", estadoFinal === "erro" ? undefined : "duração " + duracaoFinal);
}

// fecha o websocket sem o onclose achar que foi queda de conexão
function fecharSocket(qual) {
  const alvo = qual || socket;
  if (alvo && (alvo.readyState === WebSocket.OPEN || alvo.readyState === WebSocket.CONNECTING)) {
    fechamosOSocket = true;
    alvo.close();   // é fechando o socket que o backend de hoje salva o arquivo
  }
  if (socket === alvo) socket = null;
}

function encerrarPeloCliente() {
  encerrar("cliente_desligou", "encerrada");
  abrirResumo({ pedido: ultimoPedido, pedido_id: pedidoSalvoId, duracao: duracaoFinal });
}

// ---------- modo demonstracao ----------
const CLIENTE_DEMO = { nome: "Maria Aparecida", telefone: "19998124477", cadastrado: true };
// mesmos campos que o banco devolve: sem subtotal, que a tela calcula sozinha
const PIZZA_DEMO = { produto: "Pizza Margherita", quantidade: 2, observacao: "sem cebola", preco_unitario: "39.90" };
const COCA_DEMO = { produto: "Coca-Cola 2 Litros", quantidade: 1, observacao: null, preco_unitario: "12.00" };

// os dois produtos existem no seed, entao esse roteiro continua verdadeiro quando o pipeline chegar
const ROTEIRO_DEMO = [
  {
    cliente: "boa noite, eu queria fazer um pedido",
    atendente: "Boa noite! Claro. Me diz o seu nome, por favor?"
  },
  {
    cliente: "maria aparecida",
    atendente: "Prazer, Maria. O que vai ser hoje?",
    pedido: { cliente: CLIENTE_DEMO, itens: [], total: "0.00", forma_pagamento: null, endereco_entrega: null }
  },
  {
    cliente: "duas pizzas margherita sem cebola",
    atendente: "Anotei duas Margherita sem cebola. Mais alguma coisa?",
    pedido: { cliente: CLIENTE_DEMO, itens: [PIZZA_DEMO], total: "79.80", forma_pagamento: null, endereco_entrega: "Rua das Acácias, 120" }
  },
  {
    cliente: "uma coca de dois litros",
    atendente: "Certo, uma Coca-Cola de dois litros. O pagamento vai ser como?",
    pedido: { cliente: CLIENTE_DEMO, itens: [PIZZA_DEMO, COCA_DEMO], total: "91.80", forma_pagamento: null, endereco_entrega: "Rua das Acácias, 120" }
  },
  {
    cliente: "pix",
    atendente: "Fechado: duas Margherita sem cebola e uma Coca-Cola de dois litros, noventa e um reais e oitenta, no Pix. Já vai sair!",
    pedido: { cliente: CLIENTE_DEMO, itens: [PIZZA_DEMO, COCA_DEMO], total: "91.80", forma_pagamento: "pix", endereco_entrega: "Rua das Acácias, 120" },
    fim: true
  }
];

function esperar(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function entrarNoModoDemo() {
  modoDemo = true;
  document.body.dataset.demo = "1";
  faixaDemo.hidden = false;
  seloSimulacao.hidden = false;
  botaoDemo.hidden = true;
  escreverLog("modo demonstração ligado: sem backend e sem microfone");
}

function pararDemo() {
  geracaoDemo++;   // o roteiro que estiver rodando vira geração velha e desiste sozinho
  if (window.speechSynthesis) {
    try { speechSynthesis.cancel(); } catch (erro) { /* nada a fazer */ }
  }
}

// voz do proprio navegador: a banca precisa OUVIR o meia-duplex acontecendo
function falarComNavegador(texto) {
  return new Promise((resolve) => {
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
      setTimeout(resolve, 1800);
      return;
    }
    const fala = new SpeechSynthesisUtterance(texto);
    fala.lang = "pt-BR";
    fala.rate = 0.95;

    let acabou = false;
    const terminar = () => {
      if (acabou) return;
      acabou = true;
      resolve();
    };

    fala.onend = terminar;
    fala.onerror = terminar;
    // trava: em alguns navegadores o onend some, entao solta assim mesmo
    setTimeout(terminar, 3000 + texto.length * 80);

    speechSynthesis.cancel();
    speechSynthesis.speak(fala);
  });
}

async function revelarParcial(frase, minha) {
  const palavras = frase.split(" ");
  let ate = "";
  for (let i = 0; i < palavras.length; i++) {
    if (minha !== geracaoDemo) return;
    ate = ate ? ate + " " + palavras[i] : palavras[i];
    aplicarMensagem({ tipo: "transcricao", turno: turno, quem: "cliente", texto: ate, parcial: true });
    await esperar(120);
  }
}

// a demo passa pelas mesmas funcoes do backend real: aplicarMensagem, definirEstado, desenharPedido
async function rodarDemo() {
  // cada roteiro tem o seu numero: se alguem desligar e ligar de novo, o roteiro antigo
  // acorda do await, vê que nao é mais a geração da vez e para no lugar
  const minha = ++geracaoDemo;

  esconderTarjaErro();
  fecharResumo();
  limparConversa();
  limparComanda();
  resetarEtapas();
  comandaAviso.hidden = true;
  turno = 0;
  pedidoSalvoId = null;
  ultimoPedido = null;
  protocoloNovo = false;

  mudarConexao("conectando", "demonstração (sem servidor)");
  definirEstado("conectando");
  if (!loopNivel) medirNivel();
  iniciarTimer();
  await esperar(900);
  if (minha !== geracaoDemo) return;

  for (let i = 0; i < ROTEIRO_DEMO.length; i++) {
    const passo = ROTEIRO_DEMO[i];
    turno++;

    aplicarMensagem({ tipo: "estado", etapa: "ouvindo", turno: turno });
    await esperar(500);
    if (minha !== geracaoDemo) return;

    await revelarParcial(passo.cliente, minha);
    if (minha !== geracaoDemo) return;
    aplicarMensagem({ tipo: "transcricao", turno: turno, quem: "cliente", texto: passo.cliente, parcial: false });

    // aqui o microfone fecharia de verdade: é o meia-duplex
    pausarCaptura();
    tempoInicioTurno = Date.now();
    aplicarMensagem({ tipo: "estado", etapa: "transcrevendo", turno: turno });
    await esperar(800);
    if (minha !== geracaoDemo) return;

    aplicarMensagem({ tipo: "estado", etapa: "pensando", turno: turno });
    await esperar(1400);
    if (minha !== geracaoDemo) return;

    aplicarMensagem({ tipo: "estado", etapa: "respondendo", turno: turno });
    aplicarMensagem({ tipo: "transcricao", turno: turno, quem: "atendente", texto: passo.atendente, parcial: false });
    definirEstado("falando");
    if (passo.pedido) {
      aplicarMensagem(Object.assign({ tipo: "pedido", turno: turno }, passo.pedido));
    }

    // fim da fala do atendente: o microfone reabre pelo mesmo caminho do backend real
    await falarComNavegador(passo.atendente);
    if (minha !== geracaoDemo) return;
    voltarAOuvir();

    if (passo.fim) {
      aplicarMensagem({ tipo: "pedido_salvo", pedido_id: 42, total: "91.80" });
      await esperar(600);
      if (minha !== geracaoDemo) return;
      aplicarMensagem({ tipo: "chamada_encerrada", motivo: "pedido_finalizado" });
      return;
    }
  }
}

// ---------- eventos ----------
botaoChamada.addEventListener("click", () => {
  if (estadoAtual === "ouvindo" || estadoAtual === "processando" || estadoAtual === "falando") {
    if (modoDemo) {
      pararDemo();
      pararTimer();
      definirEstado("encerrada", "duração " + duracaoFinal);
      abrirResumo({ pedido: ultimoPedido, pedido_id: pedidoSalvoId, duracao: duracaoFinal });
      return;
    }
    encerrarPeloCliente();
    return;
  }

  if (modoDemo) {
    rodarDemo();
    return;
  }
  ligar();
});

botaoDemo.addEventListener("click", () => {
  entrarNoModoDemo();
  rodarDemo();
});

botaoSairDemo.addEventListener("click", () => {
  pararDemo();
  location.href = location.pathname;   // recarrega limpo, sem ?demo=1
});

tarjaErroBotao.addEventListener("click", () => {
  const eraFatal = erroEhFatal;
  esconderTarjaErro();
  if (!eraFatal) return;
  if (modoDemo) {
    rodarDemo();
  } else {
    ligar();
  }
});

resumoLigar.addEventListener("click", () => {
  fecharResumo();
  if (modoDemo) {
    rodarDemo();
  } else {
    ligar();
  }
});

resumoFechar.addEventListener("click", fecharResumo);

// se fechar a aba no meio da chamada, solta o microfone e fecha o socket direito
window.addEventListener("beforeunload", () => {
  if (estaEmChamada()) {
    pararDemo();
    pararTracks();
    if (socket && socket.readyState === WebSocket.OPEN) {
      fechamosOSocket = true;
      socket.close();
    }
  }
});

// ---------- inicio ----------
definirEstado("ocioso");
mudarConexao("desconectado", "desconectado");
escreverLog("tela carregada");

if (!navigator.mediaDevices || !window.MediaRecorder) {
  escreverLog("esse navegador não suporta gravação de áudio");
  mostrarErro("Este navegador não grava áudio. Use o Chrome ou o Edge.", false);
}

if (new URLSearchParams(location.search).get("demo") === "1") {
  entrarNoModoDemo();
  rodarDemo();
}
