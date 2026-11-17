"""Bounded multi-document enrichment for staged feed documents."""
from pipeline import enrich, llm


def enrich_documents(documents, *, vocabulary=None):
    """All results must be complete and uniquely mapped before any document is stored."""
    if not 1 <= len(documents) <= 5:
        raise ValueError('A feed batch must contain one to five documents')
    prompt = enrich._build_batch_prompt(documents, vocabulary=vocabulary, max_chars=enrich.MAX_DOC_CHARS)
    result = llm.run(prompt, task='document.tag_batch')
    try:
        data = enrich._parse_json(result.text)
        records = data['results']
        if not isinstance(records, list) or len(records) != len(documents):
            raise ValueError('incomplete result')
        by_index = {}
        for record in records:
            if not isinstance(record, dict) or isinstance(record.get('doc'), bool):
                raise ValueError('invalid result')
            value = record['doc']
            if not isinstance(value, int) and (not isinstance(value, str) or not value.isdecimal()):
                raise ValueError('invalid result index')
            index = int(value)
            if index in by_index or not 1 <= index <= len(documents) or not str(record.get('summary') or '').strip():
                raise ValueError('invalid result mapping')
            by_index[index] = enrich._normalize_llm_result(record, result.label)
        if len(by_index) != len(documents):
            raise ValueError('incomplete result mapping')
        return [by_index[index] for index in range(1, len(documents) + 1)]
    except (TypeError, KeyError, ValueError, AttributeError):
        raise ValueError('Feed batch model returned incomplete or invalid results') from None
