import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { askQuestion } from '@/api/spine'

/** 저장 문서를 첨부해 새 대화를 시작한다 (POST /api/spine/ask document_ids) */
export function useReadingDiscussion() {
  const navigate = useNavigate()
  return useMutation({ mutationFn: ({ question, ids }: { question: string; ids: number[] }) => askQuestion({ question, document_ids: ids }),
    onSuccess: d => { if (d.conversation_id) navigate(`/chat?id=${d.conversation_id}`) } })
}
