const { test } = require("node:test");
const assert = require("node:assert/strict");
const { carregarTela } = require("./tela.cjs");

test("envia abertura antes do áudio e preserva o cabeçalho capturado antes de pronto", async () => {
  class Gravador {
    static isTypeSupported() { return true; }
    constructor() { this.mimeType = "audio/webm;codecs=opus"; }
    start() { this.state = "recording"; }
  }
  const enviados = [];
  const cabecalho = new Blob(["cabecalho"]);
  const continuacao = new Blob(["continuacao"]);
  const tela = carregarTela({
    navigator: { mediaDevices: { async getUserMedia() { return {}; } } },
    window: { MediaRecorder: Gravador, addEventListener() {} },
    MediaRecorder: Gravador, WebSocket: { OPEN: 1 }, enviados, cabecalho, continuacao,
  });
  await tela.executar(`
    socket = {readyState: WebSocket.OPEN, send: dado => enviados.push(dado)};
    estadoAtual = "ouvindo";
    prepararMedidor = () => {};
    iniciarCaptura();
  `);
  tela.executar("gravador.ondataavailable({data: cabecalho})");
  assert.equal(enviados.length, 0, "nenhum binário pode anteceder iniciar_chamada");
  tela.executar('tratarMensagem({data: JSON.stringify({tipo: "pronto", versao_protocolo: 1})})');
  assert.deepEqual(JSON.parse(enviados[0]), {
    tipo: "iniciar_chamada", versao_protocolo: 1,
    formato_audio: "audio/webm;codecs=opus", chunk_ms: 250,
  });
  assert.equal(enviados[1], cabecalho);
  tela.executar("gravador.ondataavailable({data: continuacao})");
  assert.equal(enviados[2], continuacao);
  assert.equal(enviados.length, 3, "não reenviar o cabeçalho nem repetir a abertura");
});
