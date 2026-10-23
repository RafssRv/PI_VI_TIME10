"""Confere evidências locais; não chama o Ollama nem aprova respostas do modelo.

Uso: python scripts/validar_evidencias.py
     python scripts/validar_evidencias.py --expandir arquivo.json
"""

import argparse
import hashlib
import json
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]


def expandir(documento):
    """Resolve somente referências locais, sem acesso à rede ou a outros arquivos."""
    def resolver(valor, pilha=()):
        if isinstance(valor, dict):
            if "$ref" in valor:
                if set(valor) != {"$ref"}:
                    raise ValueError("Referência misturada com outros campos")
                ref = valor["$ref"]
                if not isinstance(ref, str) or not ref.startswith("#/catalogos/"):
                    raise ValueError(f"Referência não local: {ref}")
                if ref in pilha:
                    raise ValueError(f"Referência circular: {ref}")
                alvo = documento
                for parte in ref[2:].split("/"):
                    alvo = alvo[parte.replace("~1", "/").replace("~0", "~")]
                return resolver(alvo, pilha + (ref,))
            return {chave: resolver(item, pilha) for chave, item in valor.items()}
        if isinstance(valor, list):
            return [resolver(item, pilha) for item in valor]
        return valor

    # Valida também entradas de catálogo que não estejam em uso.
    resolver(documento.get("catalogos", {}))
    return resolver({k: v for k, v in documento.items() if k != "catalogos"})


def sha256(texto):
    return hashlib.sha256(texto.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def validar(caminho):
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    if bruto.get("formato") != 2:
        raise ValueError(f"{caminho.name}: formato não suportado")
    dados = expandir(bruto)
    respostas = 0
    avisos = []
    ids = set()
    for rodada in dados["rodadas"]:
        identificador = rodada.get("id", rodada.get("id_comparacao", rodada.get("id_rodada")))
        if not identificador or identificador in ids:
            raise ValueError(f"Identificador ausente ou duplicado: {identificador}")
        ids.add(identificador)
        prompt = rodada.get("prompt")
        if prompt is None:
            if not rodada.get("limitacao"):
                raise ValueError(f"{identificador}: prompt ausente sem justificativa")
            avisos.append(f"{identificador}: prompt histórico ausente")
        elif sha256(prompt) != rodada["prompt_sha256"]:
            raise ValueError(f"{identificador}: hash do prompt divergente")
        casos_ids = set()
        for caso in rodada["casos"]:
            if caso["id"] in casos_ids or not caso["turnos"]:
                raise ValueError(f"{identificador}: cenário repetido ou vazio")
            if not dados.get("criterios_cenarios", {}).get(caso["id"]):
                raise ValueError(f"{identificador}: cenário sem critério esperado")
            avaliacao = caso.get("avaliacao")
            if avaliacao and (
                avaliacao.get("resultado") not in {"atendeu", "parcial", "falhou"}
                or not avaliacao.get("observacao", "").strip()
            ):
                raise ValueError(f"{identificador}: avaliação inválida")
            casos_ids.add(caso["id"])
            for turno in caso["turnos"]:
                if not turno["cliente"].strip() or not turno["atendente"].strip():
                    raise ValueError(f"{identificador}: fala ou resposta vazia")
                if "done_reason" in turno and turno["done_reason"] != "stop":
                    avisos.append(f"{identificador}/{caso['id']}: término {turno['done_reason']}")
                respostas += 1
    atual = dados.get("prompt_no_arquivo")
    if atual:
        texto = (RAIZ / "backend/agente/prompt_sistema.txt").read_text(encoding="utf-8")
        rodada = next(r for r in dados["rodadas"] if r["id"] == atual["rodada_id"])
        if sha256(texto) != atual["sha256"] or texto != rodada["prompt"]:
            raise ValueError("O prompt atual não corresponde à rodada indicada")
    return len(ids), respostas, avisos


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expandir", type=Path, help="Imprime JSON com referências resolvidas")
    args = parser.parse_args()
    if args.expandir:
        dados = json.loads(args.expandir.read_text(encoding="utf-8"))
        print(json.dumps(expandir(dados), ensure_ascii=False, indent=2))
        return
    for caminho in sorted((RAIZ / "doc/evidencias").glob("*.json")):
        rodadas, respostas, avisos = validar(caminho)
        print(f"{caminho.name}: {rodadas} rodadas, {respostas} respostas; integridade OK")
        for aviso in avisos:
            print(f"  AVISO: {aviso}")
    print("Integridade dos arquivos não significa aprovação funcional do atendente.")


if __name__ == "__main__":
    main()
