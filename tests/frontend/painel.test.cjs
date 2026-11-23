const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");

// carrega o painel sem iniciar: sem #secao-dashboard ele só define as funções
function carregarPainel() {
  const contexto = vm.createContext({ document: { getElementById() { return null; } }, console });
  vm.runInContext(readFileSync(join(__dirname, "../../frontend/admin/painel.js"), "utf8"), contexto);
  return contexto;
}

const pedido = (status, extra = {}) => ({
  id: 7, criado_em: "2026-11-23T19:05:00-03:00", status, cliente: "Ana",
  itens: [{ quantidade: 1, produto: "Pizza Margherita grande", observacao: "sem cebola" }],
  total: "66.90", forma_pagamento: "dinheiro", troco_para: "100.00", endereco_entrega: "Rua Nova, 45", ...extra,
});

test("cada status mostra só o próximo passo, e cancelar só antes de sair", () => {
  const painel = carregarPainel();
  const casos = [
    ["aberto", "Começar preparo", true],
    ["em_preparo", "Saiu para entrega", true],
    ["saiu_entrega", "Marcar entregue", false],
  ];
  for (const [status, rotulo, cancela] of casos) {
    const html = painel.htmlDoAndamento([pedido(status)]);
    assert.ok(html.includes(rotulo), status);
    assert.equal(html.includes('data-status="cancelado"'), cancela, status);
  }
});

test("o cartão mostra itens, observação, endereço e troco", () => {
  const html = carregarPainel().htmlDoAndamento([pedido("aberto")]);
  for (const trecho of ["#7", "1× Pizza Margherita grande", "sem cebola", "Rua Nova, 45", "troco para R$ 100,00"]) {
    assert.ok(html.includes(trecho), trecho);
  }
});

test("texto vindo do banco é escapado", () => {
  const html = carregarPainel().htmlDoAndamento([pedido("aberto", { cliente: "<img src=x onerror=alert(1)>" })]);
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
});

test("lista vazia avisa em vez de ficar em branco", () => {
  assert.ok(carregarPainel().htmlDoAndamento([]).includes("Nenhum pedido esperando"));
});
