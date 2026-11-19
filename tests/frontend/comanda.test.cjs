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

test("a comanda mostra o tamanho da pizza ao lado do nome", () => {
  const tela = carregarTela();
  tela.enviar({
    tipo: "pedido", pedido_id: null, cliente: { nome: "Ana", telefone: null },
    itens: [
      { produto: "Pizza de Calabresa", quantidade: 1, preco_unitario: "49.90", tamanho: "média" },
      { produto: "Coca-Cola 2 Litros", quantidade: 1, preco_unitario: "14.90", tamanho: null },
    ],
    total: "64.80", forma_pagamento: null, endereco_entrega: null,
  });
  const nomes = tela.ler("comanda-itens").children
    .map((linha) => linha.children.find((filho) => filho.className === "miolo"))
    .filter(Boolean)
    .map((miolo) => miolo.children[0].textContent);
  assert.deepEqual(nomes, ["Pizza de Calabresa (média)", "Coca-Cola 2 Litros"]);
});
