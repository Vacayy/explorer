"""Authenticated member document bookmarks; legacy saved_items is never queried."""
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from models.member_saved import SavedCreate, SavedNote, SavedItem, SavedPage, SavedChanged
from routers.member_portfolio import MemberRoute
from security.member_saved import MemberSaved, SavedUnavailable, SavedLimit
from security.public_documents import PublicDocuments, ListingBudgetExceeded

router=APIRouter(prefix='/api/member/saved',tags=['member-saved'],route_class=MemberRoute)


def member_service(request: Request):
    if not getattr(request.state,'public_access',False): raise HTTPException(404,'Unavailable')
    user=getattr(request.state,'principal',None)
    if user is None or not user.enabled or user.role not in {'member','operator'}:
        raise HTTPException(401,'Authentication required')
    from config import DB_PATH
    try: return MemberSaved(DB_PATH,user.id,PublicDocuments.from_environment)
    except (OSError,ValueError,sqlite3.Error): raise HTTPException(503,'Saved documents unavailable') from None


def perform(action):
    try: return action()
    except SavedUnavailable: raise HTTPException(404,'Saved document unavailable') from None
    except SavedLimit: raise HTTPException(409,'Saved document limit reached') from None
    except (ListingBudgetExceeded,sqlite3.Error,OSError,ValueError):
        raise HTTPException(503,'Saved documents unavailable') from None


@router.get('',response_model=SavedPage)
def listing(offset: int=Query(0,ge=0,le=200),limit: int=Query(20,ge=1,le=20),
            doc_id: int | None=Query(None,ge=1),service: MemberSaved=Depends(member_service)):
    return perform(lambda:service.listing(offset,limit,doc_id))


@router.post('',response_model=SavedItem,status_code=201)
def add(body: SavedCreate,service: MemberSaved=Depends(member_service)):
    return perform(lambda:service.add(body))


@router.patch('/{item_id}',response_model=SavedChanged)
def change(body: SavedNote,item_id: int=Path(ge=1),service: MemberSaved=Depends(member_service)):
    perform(lambda:service.change(item_id,body));return {'ok':True}


@router.delete('/{item_id}',response_model=SavedChanged)
def delete(item_id: int=Path(ge=1),service: MemberSaved=Depends(member_service)):
    perform(lambda:service.change(item_id));return {'ok':True}
