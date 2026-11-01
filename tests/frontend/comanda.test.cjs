const { test } = require("node:test");
const assert = require("node:assert/strict");
const { carregarTela } = require("./tela.cjs");

test("outro rascunho não herda a confirmação da venda anterior", () => {
  const tela = carregarTela();
  const pedido = {
    tipo: "pedido", pedido_id: 42,
    cliente: { nome: "Ana", telefone: "19998124477" },
    itens: [{ produto: "Pizza Margherita", quantidade: 2, preco_unitario: "66.90" }],
    total: "133.80", forma_pagamento: "pix", endereco_entrega: "Rua Nova, 45",
  };
  tela.enviar(pedido);
  tela.enviar({ tipo: "pedido_salvo", pedido_id: 42, total: "133.80" });
  tela.resumo();
  assert.equal(tela.ler("resumo-titulo").textContent, "Pedido registrado");
  assert.equal(tela.ler("comanda-total").textContent, "R$ 133,80");

  tela.enviar({ ...pedido, pedido_id: null });
  tela.resumo();
  assert.equal(tela.ler("resumo-titulo").textContent, "Pedido não salvo");
  assert.equal(tela.ler("comanda-aviso").hidden, false);
});

test("queda da chamada não informa que uma venda já registrada deixou de ser salva", () => {
  const tela = carregarTela();
  tela.enviar({ tipo: "pedido_salvo", pedido_id: 42, total: "133.80" });
  tela.enviar({ tipo: "erro", fatal: true, mensagem: "Conexão interrompida" });
  assert.equal(tela.ler("comanda-aviso").textContent,
    "O pedido já foi salvo. A chamada foi interrompida.");
});
