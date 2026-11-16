from typing import Literal
from fastapi import APIRouter, Query
from models.public_trade import PublicTradeResponse
from security.public_trade import stored_trade

router=APIRouter(prefix='/api/public/trade',tags=['public-trade'])


@router.get('',response_model=PublicTradeResponse)
def trade(flow: Literal['export','import']='export',
          period: str | None=Query(None,pattern=r'^[1-9][0-9]{3}-(0[1-9]|1[0-2])$'),
          months: int=Query(60,ge=24,le=60)):
    return stored_trade(flow,period,months)
