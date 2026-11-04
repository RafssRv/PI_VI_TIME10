const assert = require("node:assert/strict");
const test = require("node:test");
const { carregarTela } = require("./tela.cjs");

function telaComMicrofone() {
  class Gravador {
    static isTypeSupported() { return true; }
    constructor() { this.mimeType = "audio/webm;codecs=opus"; }
    start() { this.state = "recording"; }
    pause() { this.state = "paused"; }
    resume() { this.state = "recording"; }
  }
  const trilha = { enabled: true };
  const microfone = { getAudioTracks: () => [trilha], getTracks: () => [trilha] };
  const enviados = [];
  const tela = carregarTela({
    navigator: { mediaDevices: { async getUserMedia() { return microfone; } } },
    window: { MediaRecorder: Gravador, addEventListener() {} },
    MediaRecorder: Gravador, WebSocket: { OPEN: 1 }, setInterval() {}, enviados,
  });
  tela.executar(`
    prepararMedidor = () => {};
    iniciarTimer = () => {};
    resetarEtapas = () => {};
    marcarEtapa = () => {};
    limparComanda = () => {};
    limparConversa = () => {};
    conectar = async () => { socket = { readyState: 1, send: (dado) => enviados.push(dado) }; };
  `);
  return { tela, trilha, enviados };
}

test("o microfone fica fechado enquanto a chamada carrega", async () => {
  const { tela, trilha } = telaComMicrofone();
  await tela.executar("ligar()");
  assert.equal(trilha.enabled, false);
  assert.equal(tela.executar("gravador.state"), "paused");
  assert.equal(tela.executar("estadoAtual"), "conectando");
});

test("o microfone abre quando a saudação termina, sem avisar um turno inexistente", async () => {
  const { tela, trilha, enviados } = telaComMicrofone();
  await tela.executar("ligar()");
  tela.executar('voltarAOuvir("tocou")');
  assert.equal(trilha.enabled, true);
  assert.equal(tela.executar("gravador.state"), "recording");
  assert.equal(tela.executar("estadoAtual"), "ouvindo");
  assert.equal(enviados.filter((dado) => String(dado).includes("resposta_tocada")).length, 0);
});

test("sem voz na saudação, o servidor manda abrir o microfone", async () => {
  const { tela, trilha } = telaComMicrofone();
  await tela.executar("ligar()");
  tela.enviar({ tipo: "estado", etapa: "ouvindo" });
  assert.equal(trilha.enabled, true);
  assert.equal(tela.executar("estadoAtual"), "ouvindo");
});

test("nada do que foi falado antes da saudação fecha um turno", async () => {
  const { tela, enviados } = telaComMicrofone();
  await tela.executar("ligar()");
  assert.equal(enviados.filter((dado) => String(dado).includes("fim_da_fala")).length, 0);
  assert.equal(tela.executar("turno"), 0);
});
