const BASE = '/api/v1'

async function request<T>(
  path: string,
  options: RequestInit & { signal?: AbortSignal } = {}
): Promise<T> {
  const { signal, ...rest } = options
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...rest.headers },
    signal,
    ...rest,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || JSON.stringify(err))
  }
  return res.json()
}

export const api = {
  collections: {
    list: () => request<{ id: string; name: string }[]>('/collections'),
    create: (name: string) =>
      request<{ id: string; name: string }>('/collections', {
        method: 'POST',
        body: JSON.stringify({ name }),
      }),
    upload: async (collectionId: string, files: File[]) => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      const res = await fetch(`${BASE}/collections/${collectionId}/documents:upload`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || JSON.stringify(err))
      }
      return res.json()
    },
    listDocuments: (collectionId: string) =>
      request<{ id: string; filename: string; file_type: string }[]>(
        `/collections/${collectionId}/documents`
      ),
    deleteDocument: (collectionId: string, documentId: string) =>
      request<{ ok: boolean; document_id: string; removed_chunks: number }>(
        `/collections/${collectionId}/documents/${documentId}`,
        { method: 'DELETE' }
      ),
  },
  search: {
    search: (collectionId: string, query: string, topK: number) =>
      request<{ results: { content: string; score: number; document_id: string }[] }>(
        '/search',
        {
          method: 'POST',
          body: JSON.stringify({ collection_id: collectionId, query, top_k: topK }),
        }
      ),
    rerank: (query: string, documents: string[], topN?: number) =>
      request<{ results: { content: string; score: number; index: number }[] }>(
        '/search/rerank',
        {
          method: 'POST',
          body: JSON.stringify({ query, documents, top_n: topN }),
        }
      ),
  },
  research: {
    listPlans: () =>
      request<{
        plan_id: string
        topic: string
        collection_id: string
        collection_name: string
        steps: { index: number; content: string; status?: string }[]
        updated_at: string
      }[]>('/research/plans'),
    getPlan: (planId: string) =>
      request<{
        plan_id: string
        topic: string
        collection_id?: string
        steps: { index: number; content: string; status?: string }[]
        markdown?: string
      }>(`/research/plans/${planId}`),
    generatePlan: (collectionId: string, topic: string) =>
      request<{
        plan_id: string
        topic: string
        steps: { index: number; content: string; status?: string }[]
        markdown?: string
      }>('/research/plans:generate', {
        method: 'POST',
        body: JSON.stringify({ collection_id: collectionId, topic }),
      }),
    updatePlan: (
      planId: string,
      steps: { index: number; content: string; status?: string }[]
    ) =>
      request<{
        plan_id: string
        topic: string
        steps: { index: number; content: string; status?: string }[]
      }>(`/research/plans/${planId}`, {
        method: 'PUT',
        body: JSON.stringify({ steps }),
      }),
    runJob: (collectionId: string, planId: string, topic: string, signal?: AbortSignal) =>
      request<{
        job_id: string
        status: string
        steps: { index: number; content: string; status?: string }[]
        result_markdown?: string
        progress?: string
        output_path?: string
        logs?: { time: string; message: string; level?: string; document?: string }[]
        started_at?: string
      }>('/research/jobs', {
        method: 'POST',
        body: JSON.stringify({
          collection_id: collectionId,
          plan_id: planId,
          topic,
        }),
        signal,
      }),
    runJobStream: async (
      collectionId: string,
      planId: string,
      topic: string,
      onLog: (log: { time: string; message: string; level?: string; document?: string }) => void,
      signal?: AbortSignal
    ): Promise<{ job_id: string; status: string; result_markdown?: string; output_path?: string }> => {
      const res = await fetch(`${BASE}/research/jobs:stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          collection_id: collectionId,
          plan_id: planId,
          topic,
        }),
        signal,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || JSON.stringify(err))
      }
      const reader = res.body?.getReader()
      if (!reader) throw new Error('No response body')
      const decoder = new TextDecoder()
      let buffer = ''
      let result: { job_id: string; status: string; result_markdown?: string; output_path?: string } | null = null
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const part of parts) {
          let event = ''
          let data = ''
          for (const line of part.split('\n')) {
            if (line.startsWith('event: ')) event = line.slice(7).trim()
            else if (line.startsWith('data: ')) data = line.slice(6)
          }
          if (!data) continue
          try {
            const parsed = JSON.parse(data)
            if (event === 'log') onLog(parsed)
            else if (event === 'done') result = parsed
            else if (event === 'error') throw new Error(parsed.message || data)
          } catch (e) {
            if (e instanceof SyntaxError) continue
            throw e
          }
        }
      }
      if (buffer.trim()) {
        let event = ''
        let data = ''
        for (const line of buffer.split('\n')) {
          if (line.startsWith('event: ')) event = line.slice(7).trim()
          else if (line.startsWith('data: ')) data = line.slice(6)
        }
        if (data) {
          try {
            const parsed = JSON.parse(data)
            if (event === 'log') onLog(parsed)
            else if (event === 'done') result = parsed
          } catch (_) {}
        }
      }
      if (!result) throw new Error('No result received')
      return result
    },
    listJobs: (limit?: number) =>
      request<{ job_id: string; topic: string; status: string; progress?: string; started_at?: string; output_path?: string }[]>(
        limit ? `/research/jobs?limit=${limit}` : '/research/jobs'
      ),
    getJob: (jobId: string) =>
      request<{
        job_id: string
        status: string
        steps: { index: number; content: string; status?: string }[]
        result_markdown?: string
        progress?: string
        output_path?: string
        logs?: { time: string; message: string; level?: string; document?: string; agent?: string; response_preview?: string }[]
        started_at?: string
      }>(`/research/jobs/${jobId}`),
    cancelJob: (jobId: string) =>
      request<{ ok: boolean }>(`/research/jobs/${jobId}/cancel`, { method: 'POST' }),
  },
  prompts: {
    listSlots: () =>
      request<{ slot_key: string; name: string; placeholders: string[] }[]>('/prompts/slots'),
    list: (slotKey?: string) =>
      request<{ id: string; slot_key: string; title: string; content: string; published: boolean; created_at: string; updated_at: string }[]>(
        slotKey ? `/prompts?slot_key=${encodeURIComponent(slotKey)}` : '/prompts'
      ),
    create: (slotKey: string, title: string, content: string) =>
      request<{ id: string; slot_key: string; title: string; content: string; published: boolean; created_at: string; updated_at: string }>(
        '/prompts',
        { method: 'POST', body: JSON.stringify({ slot_key: slotKey, title, content }) }
      ),
    update: (id: string, title?: string, content?: string) =>
      request<{ id: string; slot_key: string; title: string; content: string; published: boolean; created_at: string; updated_at: string }>(
        `/prompts/${id}`,
        { method: 'PUT', body: JSON.stringify({ title, content }) }
      ),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/prompts/${id}`, { method: 'DELETE' }),
    publish: (id: string) =>
      request<{ id: string; slot_key: string; title: string; content: string; published: boolean; created_at: string; updated_at: string }>(
        `/prompts/${id}:publish`,
        { method: 'POST' }
      ),
  },
}
