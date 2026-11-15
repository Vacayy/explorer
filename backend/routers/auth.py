"""Disabled unless explicitly configured. Does not protect other app routes."""
import hmac
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from security.login_flow import LOGIN_COOKIE, SESSION_COOKIE, SESSION_TTL, LoginFlow, session_csrf, public_read_only

router = APIRouter(prefix='/api/auth', tags=['auth'])
NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer'}


class SessionUser(BaseModel):
    id: str
    role: Literal['member', 'operator']


class SessionResponse(BaseModel):
    authenticated: bool
    user: SessionUser | None
    csrf_token: str | None
    login_available: bool = True
    chat_available: bool = True


class LogoutResponse(BaseModel):
    ok: bool


def get_service():
    if public_read_only():
        return None
    try:
        return LoginFlow.from_environment()
    except Exception:
        raise HTTPException(503, 'Authentication unavailable', headers=NO_STORE) from None


def require_service(service: LoginFlow | None = Depends(get_service)):
    if service is None:
        raise HTTPException(503, 'Authentication unavailable', headers=NO_STORE)
    return service


def set_cookie(response, name, value, max_age):
    response.set_cookie(name, value, max_age=max_age, secure=True, httponly=True, samesite='lax', path='/')


def clear_cookie(response, name):
    response.delete_cookie(name, secure=True, httponly=True, samesite='lax', path='/')


@router.get('/session', response_model=SessionResponse)
def session(request: Request, response: Response, service: LoginFlow | None = Depends(get_service)):
    response.headers.update(NO_STORE)
    if service is None:
        return SessionResponse(authenticated=False, user=None, csrf_token=None,
                               login_available=False, chat_available=False)
    token = request.cookies.get(SESSION_COOKIE, '')
    try:
        user = service.identities.resolve_session(token)
    except Exception:
        raise HTTPException(503, 'Authentication unavailable', headers=NO_STORE) from None
    if user is None:
        if token:
            clear_cookie(response, SESSION_COOKIE)
        return SessionResponse(authenticated=False, user=None, csrf_token=None)
    return SessionResponse(authenticated=True, user=SessionUser(id=user.id, role=user.role), csrf_token=session_csrf(token))


@router.get('/google/start', response_class=RedirectResponse, status_code=303)
def google_start(return_to: str = '/', service: LoginFlow = Depends(require_service)):
    try:
        location, binding = service.start(return_to)
    except ValueError:
        raise HTTPException(400, 'Invalid login request', headers=NO_STORE) from None
    except Exception:
        raise HTTPException(503, 'Authentication unavailable', headers=NO_STORE) from None
    response = RedirectResponse(location, status_code=303, headers=NO_STORE)
    set_cookie(response, LOGIN_COOKIE, binding, 300)
    return response


@router.get('/google/callback', response_class=RedirectResponse, status_code=303)
def google_callback(request: Request, service: LoginFlow = Depends(require_service)):
    try:
        if request.query_params.get('error'):
            raise ValueError('Login denied')
        # Reject duplicated parameters, avoiding parser ambiguity.
        if any(len(request.query_params.getlist(k)) != 1 for k in ('code', 'state')):
            raise ValueError('Invalid callback')
        token, target = service.complete(request.query_params.get('code'), request.query_params.get('state'),
            request.cookies.get(LOGIN_COOKIE), request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse(target, status_code=303, headers=NO_STORE)
        set_cookie(response, SESSION_COOKIE, token, SESSION_TTL)
    except Exception:
        response = JSONResponse({'detail': 'Login could not be completed'}, status_code=400, headers=NO_STORE)
    clear_cookie(response, LOGIN_COOKIE)
    return response


@router.post('/logout', response_model=LogoutResponse)
def logout(request: Request, response: Response, service: LoginFlow = Depends(require_service)):
    response.headers.update(NO_STORE)
    token = request.cookies.get(SESSION_COOKIE, '')
    csrf = request.headers.get('x-csrf-token', '')
    try:
        user = service.identities.resolve_session(token)
    except Exception:
        raise HTTPException(503, 'Authentication unavailable', headers=NO_STORE) from None
    if (request.headers.get('origin') != service.config.public_origin
            or user is None
            or not hmac.compare_digest(csrf.encode(), session_csrf(token).encode())):
        raise HTTPException(403, 'Logout request rejected', headers=NO_STORE)
    try:
        service.identities.revoke_session(token)
    except Exception:
        raise HTTPException(503, 'Authentication unavailable', headers=NO_STORE) from None
    clear_cookie(response, SESSION_COOKIE)
    return LogoutResponse(ok=True)
