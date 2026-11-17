"""The legacy `consolidation._embeddings` contract ({doc_id: vector}) from the candidate's PG vectors.

doc_vec (a sqlite-vec virtual table) is not in the projection; the candidate keeps document vectors in PG
document_embeddings. Installed by the preview API and by scheduled computations (pipeline.postgres_scheduled_compute).
"""
import struct
import sys


def install(factory):
    import pipeline.consolidation as legacy_consolidation
    import pipeline.contradiction  # noqa: F401 - bind `_embeddings` at import, then rebind below
    import pipeline.falsifiers  # noqa: F401

    def legacy_embeddings(conn, doc_ids):
        with factory() as connection:
            rows = connection.execute('SELECT document_id,embedding FROM document_embeddings WHERE document_id=ANY(%s)',
                                      (list(doc_ids),)).fetchall()
        return {ident: list(struct.unpack(f'{len(blob) // 4}f', blob)) for ident, blob in rows}

    for module in list(sys.modules.values()):
        if getattr(module, '_embeddings', None) is legacy_consolidation._embeddings and module is not legacy_consolidation:
            module._embeddings = legacy_embeddings
    legacy_consolidation._embeddings = legacy_embeddings
