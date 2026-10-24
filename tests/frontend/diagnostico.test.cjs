const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");

function diagnostico(falharGravador = false) {
  const elementos = new Map();
  const sockets = [];
  const gravadores = [];
  const trilha = { parou: false, stop() { this.parou = true; } };
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; this.enviados = []; sockets.push(this); }
    send(dado) { this.enviados.push(dado); }
    close() { this.readyState = 3; this.onclose?.(); }
  }
  class Gravador {
    static isTypeSupported(formato) { return formato === "audio/webm;codecs=opus"; }
    constructor(stream, opcoes) {
      if (falharGravador) throw new Error("formato indisponível");
      // Sem opção explícita, o formato ainda pode estar vazio antes de start().
      this.mimeType = opcoes?.mimeType || "";
      this.state = "inactive";
      gravadores.push(this);
    }
    start() { this.state = "recording"; }
    stop() { this.state = "inactive"; this.onstop?.(); }
  }
  const document = { getElementById(id) {
    if (!elementos.has(id)) elementos.set(id, {});
    return elementos.get(id);
  } };
  const html = readFileSync(join(__dirname, "../../scripts/diagnostico/teste_ws.html"), "utf8");
  vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], {
    document, WebSocket: Socket, MediaRecorder: Gravador,
    location: { host: "localhost:3000" },
    navigator: { mediaDevices: { async getUserMedia() { return { getTracks: () => [trilha] }; } } },
  });
  return { elementos, sockets, gravadores, trilha };
}

test("diagnóstico envia abertura antes dos blocos e solta microfone ao fechar", async () => {
  const tela = diagnostico();
  await tela.elementos.get("btn-iniciar").onclick();
  const socket = tela.sockets[0];
  socket.onopen();
  assert.equal(tela.gravadores.length, 0);
  await socket.onmessage({ data: JSON.stringify({ tipo: "pronto", versao_protocolo: 1 }) });
  assert.deepEqual(JSON.parse(socket.enviados[0]), {
    tipo: "iniciar_chamada", versao_protocolo: 1,
    formato_audio: "audio/webm;codecs=opus", chunk_ms: 500,
  });
  const bloco = new Blob(["audio"]);
  tela.gravadores[0].ondataavailable({ data: bloco });
  assert.equal(socket.enviados[1], bloco);
  socket.close();
  assert.equal(tela.trilha.parou, true);
});

test("diagnóstico solta o microfone se o gravador falhar após obter permissão", async () => {
  const tela = diagnostico(true);
  await tela.elementos.get("btn-iniciar").onclick();
  await tela.sockets[0].onmessage({ data: JSON.stringify({ tipo: "pronto", versao_protocolo: 1 }) });
  assert.equal(tela.sockets[0].readyState, 3);
  assert.equal(tela.trilha.parou, true);
});
