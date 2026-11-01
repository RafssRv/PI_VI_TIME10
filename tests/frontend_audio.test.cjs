const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function tela() {
  const elementos = new Map();
  const temporizadores = new Map();
  let proximoTimer = 1;
  function elemento() {
    return {
      dataset: {}, children: [], style: {}, hidden: true,
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener() {}, prepend() {}, appendChild() {},
      querySelector: elemento, play: () => Promise.resolve(), pause() {},
    };
  }
  const eventosGravador = [];
  class Gravador extends EventTarget {
    constructor() { super(); this.state = "inactive"; this.mimeType = "audio/webm"; }
    start() { this.state = "recording"; }
    pause() {
      this.state = "paused";
      eventosGravador.push(() => this.dispatchEvent(new Event("pause")));
    }
    requestData() {
      eventosGravador.push(() => this.emitir("final-da-fala"));
    }
    emitir(texto) {
      const evento = new Event("dataavailable");
      evento.data = new Blob([texto]);
      this.ondataavailable(evento);
      this.dispatchEvent(evento);
    }
  }
  const track = { enabled: true, stop() {} };
  const enviados = [];
  const contexto = vm.createContext({
    Blob, Event, Promise, console: { log() {} },
    location: { host: "localhost" },
    document: {
      body: elemento(), addEventListener() {}, createElement: elemento,
      getElementById(id) {
        if (!elementos.has(id)) elementos.set(id, elemento());
        return elementos.get(id);
      },
    },
    window: { MediaRecorder: Gravador, addEventListener() {} },
    navigator: { mediaDevices: { getUserMedia: async () => ({
      getTracks: () => [track], getAudioTracks: () => [track],
    }) } },
    MediaRecorder: Gravador, WebSocket: { OPEN: 1 },
    requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    setTimeout(fn, ms) { const id = proximoTimer++; temporizadores.set(id, { fn, ms }); return id; },
    clearTimeout(id) { temporizadores.delete(id); }, clearInterval() {},
    URL: { createObjectURL: () => "blob:resposta", revokeObjectURL() {} },
    enviados,
  });
  const executar = (codigo) => vm.runInContext(codigo, contexto);
  executar(readFileSync(join(__dirname, "../frontend/app.js"), "utf8"));
  executar('socket = { readyState: 1, send: (valor) => enviados.push(valor) }; protocoloNovo = true; definirEstado("ouvindo");');
  return { executar, enviados, eventosGravador, temporizadores, elementos, track };
}

test("fim_da_fala chega depois do ultimo audio do gravador", async () => {
  const t = tela();
  await t.executar("iniciarCaptura()");
  t.executar('gravador.emitir("cabecalho-e-inicio")');
  const fechamento = t.executar("fimDaFala(2000)");
  assert.equal(t.track.enabled, false);
  while (t.eventosGravador.length) {
    t.eventosGravador.shift()();
    await new Promise(setImmediate);
  }
  await fechamento;
  const fluxo = await Promise.all(t.enviados.map((valor) =>
    typeof valor === "string" ? JSON.parse(valor).tipo : valor.text()));
  assert.deepEqual(fluxo, ["cabecalho-e-inicio", "final-da-fala", "fim_da_fala"]);
});

test("resposta aguarda fim_audio mesmo com intervalo entre os frames", () => {
  const t = tela();
  t.executar('aplicarMensagem({ tipo: "audio_resposta", turno: 1 }); tratarMensagem({ data: new Blob(["inicio"]) });');
  for (const [id, timer] of [...t.temporizadores]) {
    if (timer.ms <= 1000) { t.temporizadores.delete(id); timer.fn(); }
  }
  assert.equal(t.executar("esperandoAudio"), true);
  t.executar('tratarMensagem({ data: new Blob(["fim"]) }); aplicarMensagem({ tipo: "fim_audio", turno: 1 });');
  assert.equal(t.executar("estadoAtual"), "falando");
});
