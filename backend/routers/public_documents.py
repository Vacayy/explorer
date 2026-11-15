"""Public document readers and authenticated, CSRF-protected operator decisions."""
import sqlite3
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from models.public_documents import (PublishedDocument, PublicationPreview, ApprovePublication,
    RevokePublication, PublicationResult, PublicDocumentList, PublicFeed)
from security.access_boundary import NO_STORE
from security.public_documents import PublicDocuments, DocumentUnavailable, ListingBudgetExceeded
from security.publication_store import PublicationConflict, InvalidCursor

router = APIRouter(tags=['public-documents'])


def publication_service(request: Request):
    # These routes are unavailable in legacy/private mode, where the public
    # authentication boundary is intentionally absent.
    if not getattr(request.state, 'public_access', False):
        raise HTTPException(404, 'Document unavailable', headers=NO_STORE)
    try:
        return PublicDocuments.from_environment()
    except (ValueError, OSError, sqlite3.Error):
        raise HTTPException(503, 'Publication unavailable', headers=NO_STORE) from None


def operator(request):
    user = getattr(request.state, 'principal', None)
    if user is None or not user.enabled or user.role != 'operator':
        raise HTTPException(403, 'Access denied', headers=NO_STORE)
    return user.id


def perform(action):
    try:
        return action()
    except DocumentUnavailable:
        raise HTTPException(404, 'Document unavailable', headers=NO_STORE) from None
    except PublicationConflict:
        raise HTTPException(409, 'Publication changed; review again', headers=NO_STORE) from None
    except ListingBudgetExceeded:
        raise HTTPException(503, 'Document search unavailable', headers=NO_STORE) from None
    except InvalidCursor:
        raise HTTPException(400, 'Search continuation unavailable; start again', headers=NO_STORE) from None
    except (sqlite3.Error, OSError, ValueError):
        raise HTTPException(503, 'Publication unavailable', headers=NO_STORE) from None


@router.get('/api/operator/publications/{doc_id}/preview', response_model=PublicationPreview)
def preview(request: Request, doc_id: int = Path(ge=1), service: PublicDocuments = Depends(publication_service)):
    operator(request)
    return perform(lambda: service.preview(doc_id))


@router.post('/api/operator/publications/{doc_id}/approve', response_model=PublicationResult)
def approve(body: ApprovePublication, request: Request, doc_id: int = Path(ge=1), service: PublicDocuments = Depends(publication_service)):
    actor = operator(request)
    return perform(lambda: service.approve(doc_id, body, actor))


@router.post('/api/operator/publications/{doc_id}/revoke', response_model=PublicationResult)
def revoke(body: RevokePublication, request: Request, doc_id: int = Path(ge=1), service: PublicDocuments = Depends(publication_service)):
    actor = operator(request)
    return perform(lambda: service.store.revoke(doc_id, body.expected_version, actor))


@router.get('/api/public/documents', response_model=PublicDocumentList)
def documents(q: str = Query(default='', max_length=120), cursor: str | None = Query(default=None, max_length=2048),
              limit: int = Query(default=10, ge=1, le=20), service: PublicDocuments = Depends(publication_service)):
    return perform(lambda: service.listing(q, cursor, limit))


@router.get('/api/public/documents/{doc_id}', response_model=PublishedDocument)
def document(doc_id: int = Path(ge=1), service: PublicDocuments = Depends(publication_service)):
    return perform(lambda: service.published(doc_id).document)


@router.get('/api/public/documents/{doc_id}/attachments/{attachment_id}', response_class=Response,
    responses={200: {'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
def attachment(doc_id: int = Path(ge=1), attachment_id: int = Path(ge=0), service: PublicDocuments = Depends(publication_service)):
    snapshot = perform(lambda: service.published(doc_id, attachment_id))
    return attachment_response(snapshot, doc_id, attachment_id)


def attachment_response(snapshot, doc_id, attachment_id):
    item = snapshot.document.attachments[attachment_id]
    suffix = {'image/png':'png', 'image/jpeg':'jpg', 'image/gif':'gif', 'image/webp':'webp', 'application/pdf':'pdf'}[item.media_type]
    disposition = 'attachment' if suffix == 'pdf' else 'inline'
    headers = {**NO_STORE, 'X-Content-Type-Options':'nosniff', 'Cross-Origin-Resource-Policy':'same-origin',
        'Content-Security-Policy':"default-src 'none'; sandbox",
        'Content-Disposition':f'{disposition}; filename="document-{doc_id}-attachment-{attachment_id}.{suffix}"'}
    return Response(snapshot.selected_bytes, media_type=item.media_type, headers=headers)


@router.get('/api/operator/publications/{doc_id}/preview/{fingerprint}/attachments/{attachment_id}', response_class=Response,
    responses={200: {'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
def preview_attachment(request: Request, doc_id: int = Path(ge=1),
                       fingerprint: str = Path(pattern=r'^[a-f0-9]{64}$'), attachment_id: int = Path(ge=0),
                       service: PublicDocuments = Depends(publication_service)):
    operator(request)
    snapshot = perform(lambda: service.capture(doc_id, attachment_id))
    if snapshot.fingerprint != fingerprint or snapshot.selected_bytes is None:
        raise HTTPException(404, 'Document unavailable', headers=NO_STORE)
    return attachment_response(snapshot, doc_id, attachment_id)


@router.get('/api/public/feed', response_model=PublicFeed)
def feed(channel: str = Query(default='', max_length=2200), platform: str = Query(default='all', max_length=128),
         topic: str = Query(default='', max_length=120), page: int = Query(default=1, ge=1, le=2000),
         until: datetime | None = None, service: PublicDocuments = Depends(publication_service)):
    from security.public_feed import public_feed
    from datetime import timezone
    cutoff = until.replace(tzinfo=timezone.utc) if until is not None and until.tzinfo is None else until
    return perform(lambda: public_feed(service, channel=channel, platform=platform, topic=topic, page=page, until=cutoff))
