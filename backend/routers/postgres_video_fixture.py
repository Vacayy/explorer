"""Private video digest endpoint for the single-path PG preview only."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pipeline.postgres_video_jobs_fixture import queue_video, run_video_job, run_video_analysis, publish_video_result, mark_video_interrupted
from pipeline.postgres_video_analysis_fixture import video_analyzer, video_call_recorder


def create_router(connect, *, search_lock, invalidate_search):
    router = APIRouter()

    def process(doc_id, token, title, transcript):
        from pipeline import llm
        recorder = video_call_recorder(connect, doc_id)
        def model(prompt, *, task):
            return llm.run(prompt, task=task, record_call=recorder)
        try:
            result = run_video_job(connect, doc_id, token, title, transcript, run_llm=model)
            if result['status'] != 'staged':
                mark_video_interrupted(connect, doc_id, token)
                return
            analysis = run_video_analysis(connect, doc_id, analyze=video_analyzer(connect, doc_id))
            if analysis['status'] != 'completed':
                mark_video_interrupted(connect, doc_id, token)
                return
            publish_video_result(connect, doc_id, search_lock=search_lock, invalidate_search=invalidate_search)
        except Exception:
            # The result remains in PG for explicit reconciliation, not retry.
            mark_video_interrupted(connect, doc_id, token)

    @router.post('/api/spine/doc/{doc_id}/digest', status_code=202)
    def digest(doc_id: int, background: BackgroundTasks):
        try:
            job = queue_video(connect, doc_id)
        except ValueError as exc:
            status = 404 if '찾을 수 없습니다' in str(exc) else 422
            raise HTTPException(status, str(exc)) from exc
        if job['status'] == 'interrupted':
            raise HTTPException(409, '이전 정리 작업을 확인한 뒤 다시 진행해 주세요')
        if job['token']:
            background.add_task(process, doc_id, job['token'], job['title'], job['transcript'])
        return {'status': job['status']}
    return router
