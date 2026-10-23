import json

import pytest

from scripts.validar_evidencias import RAIZ, expandir, sha256, validar


def test_expande_referencias_compartilhadas_sem_alterar_a_origem():
    origem = {
        "catalogos": {"textos": {"a/b~c": "ação\nsegunda linha"}},
        "turnos": [{"$ref": "#/catalogos/textos/a~1b~0c"}] * 2,
    }
    antes = json.dumps(origem)
    assert expandir(origem) == {"turnos": ["ação\nsegunda linha"] * 2}
    assert json.dumps(origem) == antes


@pytest.mark.parametrize("referencia", [
    {"$ref": "https://example.com/dados"},
    {"$ref": "#/catalogos/textos/inexistente"},
    {"$ref": "#/catalogos/textos/a", "extra": True},
    {"$ref": "#/catalogos/textos/a"},
])
def test_rejeita_referencias_invalidas_ou_circulares(referencia):
    origem = {"catalogos": {"textos": {"a": referencia}}, "valor": referencia}
    with pytest.raises((ValueError, KeyError)):
        expandir(origem)


def test_hash_divergente_detecta_prompt_alterado(tmp_path):
    caminho = tmp_path / "evidencia.json"
    dados = {
        "formato": 2,
        "rodadas": [{"id": "teste", "prompt": "original", "prompt_sha256": sha256("original"), "casos": []}],
    }
    dados["rodadas"][0]["prompt"] = "alterado"
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    with pytest.raises(ValueError, match="hash do prompt divergente"):
        validar(caminho)


def test_evidencias_do_projeto_e_prompt_atual():
    arquivos = list((RAIZ / "doc/evidencias").glob("*.json"))
    assert len(arquivos) == 3
    for arquivo in arquivos:
        rodadas, respostas, _ = validar(arquivo)
        assert rodadas > 0 and respostas > 0
