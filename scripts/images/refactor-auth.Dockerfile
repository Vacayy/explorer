# Build (no network): docker build --network none -t explorer-refactor-test:psycopg-3.2.13-auth -f scripts/images/refactor-auth.Dockerfile scripts/images
# Candidate image plus google-auth (and its deps) copied from the public image: no package download.
FROM explorer-public:bf556e86 AS public
FROM explorer-refactor-test:psycopg-3.2.13
ARG SP=/usr/local/lib/python3.14/site-packages
COPY --from=public ${SP}/google/auth ${SP}/google/auth
COPY --from=public ${SP}/google/oauth2 ${SP}/google/oauth2
COPY --from=public ${SP}/google_auth-2.62.2.dist-info ${SP}/google_auth-2.62.2.dist-info
COPY --from=public ${SP}/pyasn1 ${SP}/pyasn1
COPY --from=public ${SP}/pyasn1-0.6.5.dist-info ${SP}/pyasn1-0.6.5.dist-info
COPY --from=public ${SP}/pyasn1_modules ${SP}/pyasn1_modules
COPY --from=public ${SP}/pyasn1_modules-0.4.2.dist-info ${SP}/pyasn1_modules-0.4.2.dist-info
COPY --from=public ${SP}/cryptography ${SP}/cryptography
COPY --from=public ${SP}/cryptography-50.0.2.dist-info ${SP}/cryptography-50.0.2.dist-info
