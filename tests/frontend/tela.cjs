const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");

// DOM mínimo para executar o app real sem microfone, navegador ou servidor.
function carregarTela(extras = {}) {
  const elementos = new Map();
  function elemento() {
    return {
      textContent: "", innerHTML: "", hidden: true, children: [], dataset: {},
      classList: { toggle() {}, remove() {} },
      appendChild(filho) { this.children.push(filho); },
      prepend(filho) { this.children.unshift(filho); },
      addEventListener() {}, focus() {},
    };
  }
  const document = {
    body: elemento(),
    getElementById(id) {
      if (!elementos.has(id)) elementos.set(id, elemento());
      return elementos.get(id);
    },
    createElement: elemento,
    addEventListener() {},
  };
  const contexto = vm.createContext({
    document, location: { host: "localhost:3000" },
    navigator: { mediaDevices: {} }, window: { MediaRecorder: {}, addEventListener() {} },
    console: { log() {} }, setTimeout() {}, clearTimeout() {}, clearInterval() {},
    ...extras,
  });
  vm.runInContext(readFileSync(join(__dirname, "../../frontend/app.js"), "utf8"), contexto);
  return {
    executar(codigo) { return vm.runInContext(codigo, contexto); },
    enviar(evento) {
      contexto.evento = evento;
      vm.runInContext("aplicarMensagem(evento)", contexto);
    },
    resumo() { vm.runInContext("abrirResumo({pedido: ultimoPedido, pedido_id: pedidoSalvoId})", contexto); },
    ler(id) { return document.getElementById(id); },
  };
}

module.exports = { carregarTela };
