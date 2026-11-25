"""API da dashboard do administrador (só leitura)."""

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

import painel
import repositorio
from database import get_db
from monitor import monitor

router = APIRouter(prefix="/api/admin")
logger = logging.getLogger(__name__)


@router.websocket("/ws/monitor")
async def websocket_monitor(websocket: WebSocket):
    """Canal WebSocket para o monitoramento em tempo real das chamadas."""
    await monitor.conectar(websocket)
    try:
        while True:
            # Mantém conexão viva escutando pings ou mensagens do cliente admin
            await websocket.receive_text()
    except WebSocketDisconnect:
        monitor.desconectar(websocket)
    except Exception:
        monitor.desconectar(websocket)


@router.get("/painel")
def obter_painel(dias: int = Query(30), db=Depends(get_db)):
    if dias not in painel.PERIODOS:
        return JSONResponse(status_code=422, content={"erro": "Período inválido. Use 7, 30, 90 ou 0."})
    agora = datetime.now().astimezone()
    desde, inicio_anterior = painel.periodo(dias, agora)
    try:
        pedidos, itens = repositorio.dados_do_painel(db, desde)
        primeiras = repositorio.primeiras_compras(db, {p.cliente_id for p in pedidos})
        anterior = repositorio.totais_do_periodo(db, inicio_anterior, desde) if desde else None
        cardapio = repositorio.listar_cardapio(db, apenas_ativos=False)
    except SQLAlchemyError:
        # a mensagem do driver pode trazer parametros da consulta: nao vai pro log nem pra tela
        logger.warning("etapa=painel categoria=banco")
        return JSONResponse(status_code=503, content={"erro": "Não consegui consultar o banco."})
    return painel.montar_painel(pedidos, itens, primeiras, cardapio, dias, desde, agora, anterior)


@router.get("/pedidos/andamento")
def obter_em_andamento(db=Depends(get_db)):
    """pedidos que a cozinha e a entrega ainda precisam tocar."""
    try:
        pedidos = repositorio.pedidos_em_andamento(db)
    except SQLAlchemyError:
        logger.warning("etapa=pedidos_em_andamento categoria=banco")
        return JSONResponse(status_code=503, content={"erro": "Não consegui consultar o banco."})
    return painel.montar_em_andamento(pedidos, datetime.now().astimezone())


@router.post("/pedidos/{pedido_id}/status")
def mudar_status(pedido_id: int, status: str = Body(..., embed=True), db=Depends(get_db)):
    """um passo por vez: aberto -> em_preparo -> saiu_entrega -> entregue, ou cancelado antes de sair."""
    try:
        pedido = repositorio.mudar_status(db, pedido_id, status)
    except LookupError:
        return JSONResponse(status_code=404, content={"erro": "Pedido não encontrado."})
    except ValueError:
        return JSONResponse(status_code=409, content={"erro": "Esse pedido não pode ir para esse status."})
    except SQLAlchemyError:
        db.rollback()
        logger.warning("etapa=mudar_status categoria=banco pedido=%s", pedido_id)
        return JSONResponse(status_code=503, content={"erro": "Não consegui gravar no banco."})
    logger.info("etapa=mudar_status pedido=%s status=%s", pedido.id, pedido.status)
    return {"id": pedido.id, "status": pedido.status}
