"""
regras que o proprio banco garante, mesmo para quem grava sem passar pelo repositorio
(script, painel, outro servico). os mesmos nomes de constraint valem no postgres e no sqlite.
"""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from models import Pedido, Produto, Tamanho


def _grava_ou_recusa(db, objeto):
    db.add(objeto)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    db.rollback()
    return True


@pytest.mark.parametrize("campos, aceita", [
    ({"forma_pagamento": "pix"}, True),
    ({"forma_pagamento": None}, True),                                   # a combinar
    ({"forma_pagamento": "boleto"}, False),
    ({"forma_pagamento": "Cartão de Crédito"}, False),                   # so a forma canonica
    ({"forma_pagamento": "dinheiro", "troco_para": Decimal("100")}, True),
    ({"forma_pagamento": "pix", "troco_para": Decimal("100")}, False),   # troco so em dinheiro
    ({"forma_pagamento": None, "troco_para": Decimal("100")}, False),
    ({"total": Decimal("-1")}, False),
])
def test_regras_do_pedido(db, ana, campos, aceita):
    assert _grava_ou_recusa(db, Pedido(cliente_id=ana.id, **campos)) is aceita


@pytest.mark.parametrize("campos, aceita", [
    ({"preco": Decimal("10")}, True),
    ({"preco": Decimal("0")}, False),
    ({"preco": Decimal("10"), "grupo_tamanho": "pizza"}, True),
    ({"preco": Decimal("10"), "grupo_tamanho": "sobremesa"}, False),
])
def test_regras_do_produto(db, campos, aceita):
    assert _grava_ou_recusa(db, Produto(nome="Teste", categoria="pizza salgada", **campos)) is aceita


def test_tamanho_so_de_pizza_ou_refrigerante(db):
    assert _grava_ou_recusa(db, Tamanho(grupo="sobremesa", nome="gigante")) is False
