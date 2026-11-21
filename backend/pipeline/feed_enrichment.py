"""Bounded multi-document enrichment for staged feed documents."""
from pipeline import enrich, llm


class InvalidBatchResult(ValueError):
    """The model answered, but not with one usable result per document; `reason` names the document, `raw` keeps the answer."""

    def __init__(self, reason, raw, label):
        super().__init__(f'Feed batch model returned incomplete or invalid results: {reason}')
        self.reason, self.raw, self.label = reason, raw, label


def enrich_documents(documents, *, vocabulary=None):
    """All results must be complete and uniquely mapped before any document is stored."""
    if not 1 <= len(documents) <= 5:
        raise ValueError('A feed batch must contain one to five documents')
    prompt = enrich._build_batch_prompt(documents, vocabulary=vocabulary, max_chars=enrich.MAX_DOC_CHARS)
    result = llm.run(prompt, task='document.tag_batch')

    def invalid(reason):
        return InvalidBatchResult(reason, result.text, result.label)
    try:
        data = enrich._parse_json(result.text)
    except (TypeError, ValueError, AttributeError):
        raise invalid('not JSON') from None
    records = data.get('results') if isinstance(data, dict) else None
    if not isinstance(records, list) or len(records) != len(documents):
        raise invalid(f'{len(records) if isinstance(records, list) else "no"} results for {len(documents)} documents')
    by_index = {}
    for position, record in enumerate(records, 1):
        if not isinstance(record, dict) or isinstance(record.get('doc'), bool):
            raise invalid(f'result {position}: not a record')
        value = record.get('doc')
        if not isinstance(value, int) and (not isinstance(value, str) or not value.isdecimal()):
            raise invalid(f'result {position}: document number {value!r}')
        index = int(value)
        if not 1 <= index <= len(documents):
            raise invalid(f'result {position}: document number {index} out of range')
        if index in by_index:
            raise invalid(f'doc {index}: answered twice')
        if not str(record.get('summary') or '').strip():
            raise invalid(f'doc {index}: empty summary')
        try:
            by_index[index] = enrich._normalize_llm_result(record, result.label)
        except (TypeError, KeyError, ValueError, AttributeError) as exc:
            raise invalid(f'doc {index}: {type(exc).__name__}') from None
    return [by_index[index] for index in range(1, len(documents) + 1)]
