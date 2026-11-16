"""Read scenario prompt inputs from an explicit disposable PG candidate.

The caller supplies the same PG-backed search and local embedding model used by
chat. Graph writes and beneficiary resolution are deliberately separate.
"""
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_urgent_selection_fixture import open_snapshot
from pipeline.visibility import get_muted,is_muted
from pipeline.knowledge_recall import recall_for_query
from pipeline.narrative import _node_vocab
from pipeline.scenario import EXCERPT

TABLES=('raw_documents','telegram_channels','blog_sources','entities','knowledge','knowledge_evidence')


class ScenarioInputsFixture:
    def __init__(self,connect,*,search,embedder):
        if not callable(search) or not callable(embedder):raise ValueError('Explicit search and embedding providers required')
        self.connect,self.search,self.embedder=connect,search,embedder

    def gather(self,event,*,limit=10):
        if not isinstance(limit,int) or not 1<=limit<=10:raise ValueError('Invalid scenario document limit')
        result=self.search(event,k=limit+5)
        ids=[item['doc_id'] for item in result.items if item.get('doc_id') is not None]
        with self.connect() as pg:
            pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            _guard(pg)
            root,_,_=open_snapshot(pg,TABLES,document_ids=ids)
            try:
                muted=get_muted(root);docs=[]
                for ident in ids:
                    row=root.execute(f'''SELECT id,source_type,source_id,title,url,published_at,
                        substr(markdown,1,{EXCERPT}) excerpt FROM raw_documents WHERE id=?''',(ident,)).fetchone()
                    if row and not is_muted(row['source_type'],row['source_id'] or '',row['url'],muted):
                        docs.append(dict(row))
                    if len(docs)>=limit:break
                knowledge=recall_for_query(root,event,embedder=self.embedder)
                vocab=_node_vocab(root)
                return docs,knowledge,vocab
            finally:root.close()
