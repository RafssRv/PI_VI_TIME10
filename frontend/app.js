// endereco do websocket do backend (rota /ws/falar do main.py)
// se o backend rodar em outra porta ou maquina, eh so trocar aqui
const URL_WEBSOCKET = `ws://${location.hostname}:8000/ws/falar`;

// de quanto em quanto tempo o gravador entrega um pedaco (chunk) de audio, em ms
const TAMANHO_CHUNK_MS = 250;

// pegando os elementos da tela
const botaoGravar = document.getElementById("botao-gravar");
const player = document.getElementById("player");
const timer = document.getElementById("timer");
const bolinha = document.getElementById("bolinha");
const textoStatus = document.getElementById("texto-status");
const log = document.getElementById("log");

// variaveis de controle
let gravador = null;       // o MediaRecorder
let socket = null;         // a conexao com o backend
let pedacos = [];          // guarda os chunks pra montar o audio no final
let gravando = false;
let intervaloTimer = null;
let segundos = 0;

// escreve uma linha no log da tela (e no console tambem)
function escreverLog(mensagem) {
  const hora = new Date().toLocaleTimeString();
  const item = document.createElement("li");
  item.textContent = `[${hora}] ${mensagem}`;
  log.prepend(item);
  console.log(mensagem);
}

function mudarStatus(texto, classe) {
  textoStatus.textContent = texto;
  bolinha.className = "bolinha " + classe;
}

// ---- timer da gravacao ----
function iniciarTimer() {
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
}

// ---- conexao com o backend ----
function conectarWebSocket() {
  // retorna uma promise pra gente so comecar a gravar depois que conectar
  return new Promise((resolve, reject) => {
    socket = new WebSocket(URL_WEBSOCKET);

    socket.onopen = () => {
      mudarStatus("conectado ao backend", "conectado");
      escreverLog("websocket conectado");
      resolve();
    };

    // por enquanto o backend so responde um texto confirmando o chunk
    socket.onmessage = (evento) => {
      escreverLog("backend: " + evento.data);
    };

    socket.onerror = () => {
      mudarStatus("erro na conexao", "erro");
      escreverLog("erro no websocket (o backend esta rodando?)");
      reject(new Error("falha ao conectar"));
    };

    socket.onclose = () => {
      mudarStatus("desconectado", "desconectado");
      escreverLog("websocket fechado");
    };
  });
}

// ---- gravacao ----
async function comecarGravacao() {
  // 1. pede permissao do microfone
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (erro) {
    escreverLog("sem permissao de microfone: " + erro.message);
    return;
  }

  // 2. tenta conectar no backend. se nao der, grava so local mesmo
  try {
    await conectarWebSocket();
  } catch (erro) {
    escreverLog("seguindo sem backend, o audio vai ser so tocado aqui");
  }

  // 3. cria o gravador
  pedacos = [];
  gravador = new MediaRecorder(stream);

  // toda vez que um pedaco fica pronto, guarda e manda pro backend
  gravador.ondataavailable = (evento) => {
    if (evento.data.size === 0) return;

    pedacos.push(evento.data);

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(evento.data);
    }
  };

  // quando parar, monta o audio inteiro e coloca no player
  gravador.onstop = () => {
    const audioCompleto = new Blob(pedacos, { type: gravador.mimeType });
    player.src = URL.createObjectURL(audioCompleto);
    escreverLog(`gravacao finalizada (${(audioCompleto.size / 1024).toFixed(1)} KB)`);

    // desliga o microfone (some o icone de gravando do navegador)
    stream.getTracks().forEach((track) => track.stop());

    // fecha o websocket, eh nessa hora que o backend salva o arquivo
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.close();
    }
  };

  gravador.start(TAMANHO_CHUNK_MS);
  gravando = true;
  botaoGravar.textContent = "Parar";
  botaoGravar.classList.add("gravando");
  iniciarTimer();
  escreverLog("gravando...");
}

function pararGravacao() {
  if (gravador && gravador.state !== "inactive") {
    gravador.stop();
  }
  gravando = false;
  botaoGravar.textContent = "Gravar";
  botaoGravar.classList.remove("gravando");
  pararTimer();
}

botaoGravar.addEventListener("click", () => {
  if (gravando) {
    pararGravacao();
  } else {
    comecarGravacao();
  }
});

// aviso caso o navegador nao tenha suporte
if (!navigator.mediaDevices || !window.MediaRecorder) {
  escreverLog("esse navegador nao suporta gravacao de audio");
  botaoGravar.disabled = true;
}
