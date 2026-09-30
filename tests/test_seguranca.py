"""
CPF que chega por voz: normalizacao, digito verificador e hash (RNF06, e o RIA09 no espirito).
nao precisa de banco.
"""

import pytest

import seguranca


class TestNormalizacao:
    def test_tira_pontuacao(self):
        assert seguranca.normalizar_cpf("382.914.756-28") == "38291475628"

    def test_tira_palavra_solta_da_transcricao(self):
        # o whisper devolve coisa assim: "meu cpf e 382 914 756 28"
        assert seguranca.normalizar_cpf("meu cpf e 382 914 756 28") == "38291475628"

    def test_vazio_e_none_nao_estouram(self):
        assert seguranca.normalizar_cpf("") == ""
        assert seguranca.normalizar_cpf(None) == ""


class TestDigitoVerificador:
    def test_cpf_valido(self):
        assert seguranca.cpf_valido("38291475628")

    def test_aceita_formatado(self):
        assert seguranca.cpf_valido("382.914.756-28")

    def test_recusa_dv_errado(self):
        # e justamente isso que pega o whisper trocando um digito
        assert not seguranca.cpf_valido("38291475629")

    def test_recusa_todos_os_digitos_iguais(self):
        # passam na conta do dv mas nao sao cpf de ninguem
        for repetido in ("00000000000", "11111111111", "99999999999"):
            assert not seguranca.cpf_valido(repetido)

    def test_recusa_tamanho_errado(self):
        assert not seguranca.cpf_valido("3829147562")
        assert not seguranca.cpf_valido("382914756289")


class TestHash:
    def test_tem_64_caracteres_hex(self):
        hash_do_cpf = seguranca.hashear_cpf("38291475628")
        assert len(hash_do_cpf) == 64
        int(hash_do_cpf, 16)  # estoura se nao for hexadecimal

    def test_mesmo_cpf_mesmo_hash(self):
        # sem isso a busca por igualdade do RF03 nao funcionaria
        assert seguranca.hashear_cpf("38291475628") == seguranca.hashear_cpf("38291475628")

    def test_formatado_e_puro_dao_o_mesmo_hash(self):
        assert seguranca.hashear_cpf("382.914.756-28") == seguranca.hashear_cpf("38291475628")

    def test_cpfs_diferentes_dao_hashes_diferentes(self):
        assert seguranca.hashear_cpf("38291475628") != seguranca.hashear_cpf("51742608353")

    def test_nao_guarda_o_numero_em_lugar_nenhum_do_hash(self):
        # RNF06: o cpf nao pode aparecer em texto puro
        assert "38291475628" not in seguranca.hashear_cpf("38291475628")

    def test_cpf_curto_levanta_com_mensagem_util(self):
        with pytest.raises(ValueError, match="11 digitos"):
            seguranca.hashear_cpf("3829147562")

    def test_dv_errado_levanta(self):
        with pytest.raises(ValueError, match="digitos verificadores"):
            seguranca.hashear_cpf("38291475629")

    def test_segredo_diferente_muda_o_hash(self, monkeypatch):
        """
        o hmac depende do segredo do servidor, nao so do cpf. e isso que diferencia de um
        sha256 puro, que qualquer um quebraria por forca bruta em ~10^9 combinacoes.
        """
        original = seguranca.hashear_cpf("38291475628")
        monkeypatch.setattr(seguranca, "SEGREDO_CPF", "outro-segredo-qualquer")
        assert seguranca.hashear_cpf("38291475628") != original
