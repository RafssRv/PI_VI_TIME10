const { test } = require("node:test");
const assert = require("node:assert/strict");
const { carregarTela } = require("./tela.cjs");

const privado = "111.222.333-96 Marina Privacidade (19) 98765-4321 Rua Privacidade, 987";

for (const [nome, evento] of [
  ["mensagem desconhecida", { tipo: "novo", texto: privado }],
  ["tipo desconhecido", { tipo: privado }],
  ["versão inválida", { tipo: "pronto", versao_protocolo: privado }],
  ["estado desconhecido", { tipo: "estado", etapa: privado }],
  ["autor desconhecido", { tipo: "transcricao", quem: privado, texto: privado }],
  ["erro recuperável", { tipo: "erro", mensagem: privado, fatal: false }],
  ["erro fatal", { tipo: "erro", mensagem: privado, fatal: true }],
  ["encerramento", { tipo: "chamada_encerrada", motivo: privado }],
  ["comanda inválida", { tipo: "pedido", cliente: { nome: privado }, itens: [],
                         total: privado, forma_pagamento: privado }],
]) {
  test(`${nome} não copia dados pessoais para os logs`, () => {
    const consoleLog = [];
    const tela = carregarTela({ console: { log: texto => consoleLog.push(texto) } });
    tela.enviar(evento);
    assert.ok(!consoleLog.join("\n").includes(privado));
    assert.ok(!tela.ler("log").children.map(e => e.textContent).join("\n").includes(privado));
    if (evento.tipo === "erro") {
      assert.equal(tela.ler("tarja-erro-texto").textContent, privado);
    }
  });
}

test("texto sem protocolo e frame anterior a pronto não vazam nos logs", () => {
  const consoleLog = [];
  const tela = carregarTela({ console: { log: texto => consoleLog.push(texto) }, privado });
  tela.executar("tratarMensagem({data: privado})");
  tela.executar("tratarMensagem({data: JSON.stringify({tipo: privado})})");
  assert.ok(!consoleLog.join("\n").includes(privado));
  assert.ok(!tela.ler("log").children.map(e => e.textContent).join("\n").includes(privado));
});
