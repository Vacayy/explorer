"""Standalone member portfolio fixture with the existing access boundary.

Requires the existing development auth/router modules and an explicitly
provided identity service. It does not initialize accounts or start a server.
"""
from fastapi import FastAPI, HTTPException, Request
from pipeline.postgres_portfolio_fixture import FixturePortfolioMarket, MemberPortfolioFixture


def create_app(factory, *, identity_service):
    from routers import auth, member_portfolio as routes
    from security.access_boundary import PublicAccessBoundary, PUBLIC_ROUTE_POLICIES
    from security.member_portfolio import TransactionUnavailable

    with factory() as conn:
        names=FixturePortfolioMarket(conn).names()

    def prices(*args):
        with factory() as conn:
            return FixturePortfolioMarket(conn).prices(*args)

    def last_close(*args):
        with factory() as conn:
            return FixturePortfolioMarket(conn).last_close(*args)

    def service(request: Request):
        if not getattr(request.state,'public_access',False):
            raise HTTPException(404,'Unavailable')
        user=getattr(request.state,'principal',None)
        if user is None or not user.enabled or user.role not in {'member','operator'}:
            raise HTTPException(401,'Authentication required')
        return MemberPortfolioFixture(factory,user.id,names=names,prices=prices,
                                      last_close=last_close,unavailable=TransactionUnavailable)

    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.include_router(auth.router)
    app.include_router(routes.router)
    app.dependency_overrides[auth.get_service]=lambda:identity_service
    app.dependency_overrides[routes.member_service]=service
    # Principle endpoints need an independent owned store; leave them closed.
    allowed={('GET','/api/auth/session'),('GET','/api/member/portfolio'),('GET','/api/member/portfolio/history'),
             ('GET','/api/member/portfolio/transactions'),('GET','/api/member/portfolio/companies'),
             ('POST','/api/member/portfolio/transactions'),('DELETE','/api/member/portfolio/transactions/{tx_id}')}
    policies={key:PUBLIC_ROUTE_POLICIES[key] for key in allowed}
    app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies=policies,
                       service_factory=lambda:identity_service)
    return app
