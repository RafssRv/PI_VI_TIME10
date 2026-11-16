"""Gerenciador de telemetria e eventos em tempo real para o monitoramento do admin."""

import asyncio
from datetime import datetime
from typing import Dict, Any, List

class MonitorEventos:
    def __init__(self):
        self._conexoes = set()
        self.chamadas_ativas: Dict[str, Dict[str, Any]] = {}
        self.historico_recente: List[Dict[str, Any]] = []
        self._limite_historico = 30

    async def conectar(self, websocket):
        await websocket.accept()
        self._conexoes.add(websocket)
        # Ao conectar, envia o estado inicial completo
        await websocket.send_json({
            "tipo": "snapshot",
            "ativas": list(self.chamadas_ativas.values()),
            "historico": self.historico_recente
        })

    def desconectar(self, websocket):
        self._conexoes.discard(websocket)

    async def _transmitir(self, mensagem: Dict[str, Any]):
        mortas = set()
        for ws in self._conexoes:
            try:
                await ws.send_json(mensagem)
            except Exception:
                mortas.add(ws)
        for ws in mortas:
            self._conexoes.discard(ws)

    def iniciar_chamada(self, chamada_id: str):
        agora = datetime.now().isoformat()
        chamada = {
            "id": chamada_id,
            "inicio": agora,
            "status": "conectado",
            "etapa": "iniciando",
            "turno_atual": 0,
            "duracao_ms": 0,
            "transcricoes": [],
            "comanda": None,
            "metricas_turno": {},
            "ultimo_evento": agora
        }
        self.chamadas_ativas[chamada_id] = chamada
        asyncio.create_task(self._transmitir({
            "tipo": "chamada_iniciada",
            "chamada": chamada
        }))

    def atualizar_etapa(self, chamada_id: str, etapa: str, turno: int = 0):
        if chamada_id not in self.chamadas_ativas:
            return
        chamada = self.chamadas_ativas[chamada_id]
        chamada["etapa"] = etapa
        chamada["status"] = etapa
        chamada["turno_atual"] = turno
        chamada["ultimo_evento"] = datetime.now().isoformat()
        asyncio.create_task(self._transmitir({
            "tipo": "etapa_atualizada",
            "chamada_id": chamada_id,
            "etapa": etapa,
            "turno": turno,
            "timestamp": chamada["ultimo_evento"]
        }))

    def registrar_transcricao(self, chamada_id: str, quem: str, texto: str, turno: int):
        if chamada_id not in self.chamadas_ativas:
            return
        chamada = self.chamadas_ativas[chamada_id]
        registro = {
            "quem": quem,
            "texto": texto,
            "turno": turno,
            "timestamp": datetime.now().isoformat()
        }
        chamada["transcricoes"].append(registro)
        if len(chamada["transcricoes"]) > 40:
            chamada["transcricoes"].pop(0)
        asyncio.create_task(self._transmitir({
            "tipo": "transcricao",
            "chamada_id": chamada_id,
            "registro": registro
        }))

    def registrar_metricas(self, chamada_id: str, turno: int, metricas: Dict[str, Any]):
        if chamada_id not in self.chamadas_ativas:
            return
        chamada = self.chamadas_ativas[chamada_id]
        chamada["metricas_turno"] = metricas
        asyncio.create_task(self._transmitir({
            "tipo": "metricas_turno",
            "chamada_id": chamada_id,
            "turno": turno,
            "metricas": metricas
        }))

    def atualizar_comanda(self, chamada_id: str, comanda: Dict[str, Any]):
        if chamada_id not in self.chamadas_ativas:
            return
        chamada = self.chamadas_ativas[chamada_id]
        chamada["comanda"] = comanda
        asyncio.create_task(self._transmitir({
            "tipo": "comanda_atualizada",
            "chamada_id": chamada_id,
            "comanda": comanda
        }))

    def encerrar_chamada(self, chamada_id: str, motivo: str = "finalizada", pedido_id: Any = None):
        if chamada_id not in self.chamadas_ativas:
            return
        chamada = self.chamadas_ativas.pop(chamada_id)
        chamada["fim"] = datetime.now().isoformat()
        chamada["status"] = "encerrada"
        chamada["motivo_encerramento"] = motivo
        chamada["pedido_id"] = pedido_id
        
        self.historico_recente.insert(0, chamada)
        if len(self.historico_recente) > self._limite_historico:
            self.historico_recente.pop()

        asyncio.create_task(self._transmitir({
            "tipo": "chamada_encerrada",
            "chamada": chamada
        }))


# Instância global do monitor
monitor = MonitorEventos()
