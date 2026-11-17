"""Monitor do painel: avisos em tempo real sem depender de banco nem de rede."""

import asyncio

from monitor import MonitorEventos


class Painel:
    def __init__(self, ao_receber=None):
        self.recebidas = []
        self.ao_receber = ao_receber

    async def accept(self):
        pass

    async def send_json(self, mensagem):
        self.recebidas.append(mensagem["tipo"])
        if self.ao_receber:
            self.ao_receber()


def test_painel_que_sai_durante_o_envio_nao_interrompe_os_outros():
    async def cenario():
        monitor = MonitorEventos()
        ultimo = Painel()
        # o primeiro painel a receber derruba outro no meio do envio
        primeiro = Painel(ao_receber=lambda: monitor.desconectar(saindo))
        saindo = Painel()
        for painel in (primeiro, saindo, ultimo):
            await monitor.conectar(painel)
        primeiro.recebidas.clear()
        ultimo.recebidas.clear()

        monitor.iniciar_chamada("chamada-1")
        await asyncio.gather(*monitor._envios)
        return primeiro.recebidas, ultimo.recebidas, monitor._envios

    primeiro, ultimo, pendentes = asyncio.run(cenario())
    assert primeiro == ["chamada_iniciada"]
    assert ultimo == ["chamada_iniciada"]
    assert not pendentes


def test_painel_com_conexao_quebrada_e_removido():
    async def cenario():
        monitor = MonitorEventos()

        def quebrar():
            raise ConnectionError("painel fechou")

        quebrado = Painel()
        await monitor.conectar(quebrado)
        quebrado.ao_receber = quebrar
        monitor.iniciar_chamada("chamada-1")
        await asyncio.gather(*monitor._envios)
        return monitor._conexoes

    assert asyncio.run(cenario()) == set()
