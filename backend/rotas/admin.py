"""API da dashboard do administrador (só leitura)."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

import painel
import repositorio
from database import get_db

router = APIRouter(prefix="/api/admin")
logger = logging.getLogger(__name__)


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
