"""
identificacao e cadastro do cliente no meio da conversa (RF03 e RF04).
"""

import pytest

import repositorio


class TestIdentificacao:
    def test_acha_pelo_cpf(self, db, cpf_da_ana):
        cliente = repositorio.buscar_cliente_por_cpf(db, cpf_da_ana)
        assert cliente is not None
        assert cliente.nome == "Ana Beatriz Moraes"

    def test_acha_com_o_cpf_formatado(self, db, cpf_da_ana):
        formatado = "{}.{}.{}-{}".format(
            cpf_da_ana[:3], cpf_da_ana[3:6], cpf_da_ana[6:9], cpf_da_ana[9:]
        )
        assert repositorio.buscar_cliente_por_cpf(db, formatado) is not None

    def test_acha_com_o_cpf_falado_com_espacos(self, db, cpf_da_ana):
        falado = "{} {} {} {}".format(
            cpf_da_ana[:3], cpf_da_ana[3:6], cpf_da_ana[6:9], cpf_da_ana[9:]
        )
        assert repositorio.buscar_cliente_por_cpf(db, falado) is not None

    def test_cpf_que_nao_existe_devolve_none(self, db):
        # cpf valido no digito verificador, mas nao cadastrado: e o gatilho do RF04
        assert repositorio.buscar_cliente_por_cpf(db, "11122233396") is None

    def test_cpf_invalido_nao_vira_consulta_no_banco(self, db):
        with pytest.raises(ValueError):
            repositorio.buscar_cliente_por_cpf(db, "11122233300")

    def test_o_numero_nao_fica_no_banco(self, db, cpf_da_ana):
        # RNF06: so o hmac e gravado
        cliente = repositorio.buscar_cliente_por_cpf(db, cpf_da_ana)
        assert cpf_da_ana not in cliente.cpf_hash
        assert len(cliente.cpf_hash) == 64


class TestCadastro:
    def test_cadastra_e_encontra_depois(self, db):
        novo = repositorio.criar_cliente(
            db, "Joao da Silva", "11122233396",
            telefone="(19) 99999-1234", endereco="Rua das Palmeiras, 120",
        )
        assert novo.id is not None
        encontrado = repositorio.buscar_cliente_por_cpf(db, "11122233396")
        assert encontrado.id == novo.id
        assert encontrado.nome == "Joao da Silva"

    def test_telefone_e_guardado_so_com_digitos(self, db):
        # a fala traz "(19) 99999-1234 whatsapp"; no banco fica so o numero
        novo = repositorio.criar_cliente(
            db, "Joao da Silva", "11122233396", telefone="(19) 99999-1234 whatsapp"
        )
        assert novo.telefone == "19999991234"

    def test_cpf_repetido_vira_erro_explicado(self, db, cpf_da_ana):
        with pytest.raises(ValueError, match="cpf"):
            repositorio.criar_cliente(db, "Outra Pessoa", cpf_da_ana)

    def test_nome_vazio_nao_cadastra(self, db):
        with pytest.raises(ValueError, match="nome"):
            repositorio.criar_cliente(db, "   ", "11122233396")

    def test_cpf_invalido_nao_cadastra(self, db):
        with pytest.raises(ValueError):
            repositorio.criar_cliente(db, "Joao da Silva", "11122233300")

    def test_sessao_continua_utilizavel_depois_de_um_erro(self, db, cpf_da_ana):
        """
        a conversa do websocket e uma sessao longa: se um cadastro falhar e a transacao
        ficar abortada, todo o resto da chamada morre junto.
        """
        with pytest.raises(ValueError):
            repositorio.criar_cliente(db, "Outra Pessoa", cpf_da_ana)
        assert repositorio.buscar_cliente_por_cpf(db, cpf_da_ana) is not None
