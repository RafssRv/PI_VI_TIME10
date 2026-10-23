"""Repete uma rodada textual preservada, sem banco ou gravação de pedidos.

Uso: python scripts/revalidar_prompt.py evidencia.json rodada saida.json
O arquivo de saída deve ser novo. Não aprova automaticamente as respostas.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

from validar_evidencias import expandir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidencia', type=Path)
    parser.add_argument('rodada')
    parser.add_argument('saida', type=Path)
    args = parser.parse_args()
    dados = expandir(json.loads(args.evidencia.read_text(encoding='utf-8')))
    rodada = next(r for r in dados['rodadas'] if r['id'] == args.rodada)
    resultado = {k: v for k, v in rodada.items() if k not in ('casos', 'observacao')}
    resultado['casos'] = []
    saida = {'formato': 2, 'executado_em': datetime.now(timezone.utc).isoformat(),
             'endpoint': 'http://127.0.0.1:11434/api/chat', 'stream': False,
             'cardapio_ficticio': dados['cardapio_ficticio'],
             'criterios_cenarios': dados['criterios_cenarios'], 'rodadas': [resultado]}
    # Criação exclusiva evita sobrescrever evidências anteriores.
    with args.saida.open('x', encoding='utf-8') as destino:
        for original in rodada['casos']:
            sistema = rodada['prompt']
            if original['com_cardapio']:
                sistema += '\n\n' + dados['cardapio_ficticio']
            mensagens = [{'role': 'system', 'content': sistema}]
            caso = {'id': original['id'], 'com_cardapio': original['com_cardapio'], 'turnos': []}
            resultado['casos'].append(caso)
            for turno in original['turnos']:
                mensagens.append({'role': 'user', 'content': turno['cliente']})
                corpo = {'model': rodada['modelo'], 'options': rodada['opcoes'],
                         'stream': False, 'messages': mensagens}
                pedido = Request(saida['endpoint'], data=json.dumps(corpo).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
                with urlopen(pedido, timeout=180) as resposta:
                    gerado = json.load(resposta)
                mensagens.append(gerado['message'])
                caso['turnos'].append({'cliente': turno['cliente'],
                    'atendente': gerado['message']['content'], 'done_reason': gerado.get('done_reason')})
                destino.seek(0)
                json.dump(saida, destino, ensure_ascii=False, indent=2)
                destino.truncate()
                destino.flush()
            print(caso['id'], 'executado; avaliação funcional pendente', flush=True)


if __name__ == '__main__':
    main()
