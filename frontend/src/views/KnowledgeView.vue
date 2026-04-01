<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Alert, Button, Card, Col, Form, Input, List, Row, Select, Space, Tabs, Tag, Tree, Collapse, Modal, Table, message } from 'ant-design-vue'
import {
  api,
  type KnowledgeResultItem,
  type KnowledgeLogEntry,
  type KnowledgeRetrieveCitation,
  type KnowledgeRetrieveLog,
} from '@/api/client'
import { PlusOutlined, DeleteOutlined, EditOutlined, RollbackOutlined } from '@ant-design/icons-vue'

const POLL_MS = 2000
const STORAGE_KEY = 'knowledge_last_job_id'
const RETRIEVE_HISTORY_KEY = 'knowledge_retrieve_history_v1'

type RetrieveSnapshot = {
  at: string
  query: string
  answer: string
  route: string
  citations: KnowledgeRetrieveCitation[]
  logs: KnowledgeRetrieveLog[]
}

const collections = ref<{ id: string; name: string }[]>([])
const selectedCollectionId = ref<string>()
const jobs = ref<
  { job_id: string; collection_id: string; status: string; progress?: string; started_at?: string }[]
>([])
const selectedJobId = ref<string>()
const jobLogs = ref<KnowledgeLogEntry[]>([])
const running = ref(false)
const extracting = ref(false)
const error = ref('')
const results = ref<KnowledgeResultItem[]>([])
const resultType = ref<string>()
const keyword = ref('')
const activeTab = ref('summary')
const graphNodes = ref<Record<string, unknown>[]>([])
const graphEdges = ref<Record<string, unknown>[]>([])
const selectedGraphNodeId = ref<string>('')
const graphViewMode = ref<'visual' | 'triples'>('visual')
const hoveredEdgeText = ref<string>('')
const hoveredEdgePos = ref<{ x: number; y: number } | null>(null)
const newItemPanelActive = ref<string[]>([])
const originalContentMap = ref<Record<string, string>>({})
const selectedStructureNodeKey = ref<string>('')
const selectedStructureNodeLabel = ref<string>('')
const structureEditText = ref<string>('')
const structureVersionHistory = ref<Record<string, string[]>>({})
const structureEditModalOpen = ref(false)
const newItem = ref({
  result_type: 'knowledge_point',
  title: '',
  content: '',
  tags: '',
  document_id: 'manual',
  document_name: '手工新增',
})
const retrieveQuery = ref('')
const retrieveLoading = ref(false)
const retrieveAnswer = ref('')
const retrieveRoute = ref('')
const retrieveCitations = ref<KnowledgeRetrieveCitation[]>([])
const retrieveLogs = ref<KnowledgeRetrieveLog[]>([])
const retrieveHistorySnapshots = ref<RetrieveSnapshot[]>([])
const activeHistoryIndex = ref(0)
/** 每次执行检索递增，用于强制刷新下方日志/回答/引用区域 */
const retrieveRunId = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const collectionOptions = computed(() => collections.value.map((c) => ({ value: c.id, label: c.name })))

const retrieveHistorySelectOptions = computed(() =>
  retrieveHistorySnapshots.value.map((s, i) => ({
    value: i,
    label: `${formatRetrieveHistoryTime(s.at)} · ${truncateRetrieveQuery(s.query)}`,
  }))
)

function formatRetrieveHistoryTime(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 19) || '—'
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${y}/${m}/${day} ${hh}:${mm}`
}

function truncateRetrieveQuery(q: string, maxLen = 42) {
  const t = (q || '').trim()
  if (t.length <= maxLen) return t || '（空问题）'
  return `${t.slice(0, maxLen)}…`
}

function clearRetrieveUI() {
  retrieveQuery.value = ''
  retrieveAnswer.value = ''
  retrieveRoute.value = ''
  retrieveCitations.value = []
  retrieveLogs.value = []
}

function applyRetrieveSnapshot(s: RetrieveSnapshot) {
  retrieveQuery.value = s.query
  retrieveAnswer.value = s.answer
  retrieveRoute.value = s.route
  retrieveCitations.value = [...s.citations]
  retrieveLogs.value = [...s.logs]
}

function persistRetrieveHistory(cid: string, list: RetrieveSnapshot[]) {
  try {
    const raw = sessionStorage.getItem(RETRIEVE_HISTORY_KEY)
    const map = raw ? (JSON.parse(raw) as Record<string, RetrieveSnapshot[]>) : {}
    map[cid] = list
    sessionStorage.setItem(RETRIEVE_HISTORY_KEY, JSON.stringify(map))
  } catch {
    /* ignore */
  }
}

function loadRetrieveHistoryForCollection(cid: string | undefined) {
  if (!cid) {
    retrieveHistorySnapshots.value = []
    activeHistoryIndex.value = 0
    clearRetrieveUI()
    return
  }
  try {
    const raw = sessionStorage.getItem(RETRIEVE_HISTORY_KEY)
    const map = raw ? (JSON.parse(raw) as Record<string, RetrieveSnapshot[]>) : {}
    const list = Array.isArray(map[cid]) ? map[cid] : []
    retrieveHistorySnapshots.value = list
    activeHistoryIndex.value = 0
    const first = list[0]
    if (first) applyRetrieveSnapshot(first)
    else clearRetrieveUI()
  } catch {
    retrieveHistorySnapshots.value = []
    activeHistoryIndex.value = 0
    clearRetrieveUI()
  }
}

function onPickRetrieveHistory(value: unknown) {
  if (value === undefined || value === null) return
  const idx = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(idx)) return
  const s = retrieveHistorySnapshots.value[idx]
  if (s) applyRetrieveSnapshot(s)
}

async function onCollectionChange() {
  await loadResults()
  await loadGraph()
  loadRetrieveHistoryForCollection(selectedCollectionId.value)
}
const filteredResults = computed(() => {
  const t = activeTab.value
  if (t === 'graph') return []
  const map: Record<string, string> = {
    summary: 'summary',
    structure: 'structure',
    points: 'knowledge_point',
  }
  const target = map[t]
  return results.value.filter((x) => x.result_type === target)
})
const structureTreeData = computed(() => {
  const src = results.value.filter((x) => x.result_type === 'structure')
  return src.map((x) => {
    let parsed: Record<string, unknown> = {}
    try {
      parsed = JSON.parse(x.content || '{}')
    } catch {
      parsed = {}
    }
    const sections = Array.isArray(parsed.sections) ? parsed.sections : []
    const paragraphs = Array.isArray(parsed.paragraph_notes) ? parsed.paragraph_notes : []
    const paragraphBuckets = new Map<string, { p: Record<string, unknown>; idx: number }[]>()
    const unmatched: { p: Record<string, unknown>; idx: number }[] = []
    paragraphs.forEach((p, idx) => {
      const pObj = p as Record<string, unknown>
      const sectionRef = String(pObj.section_ref || '').trim()
      if (!sectionRef) {
        unmatched.push({ p: pObj, idx })
        return
      }
      const list = paragraphBuckets.get(sectionRef) || []
      list.push({ p: pObj, idx })
      paragraphBuckets.set(sectionRef, list)
    })
    const sectionIdSet = new Set(
      sections.map((s, i) => String((s as Record<string, unknown>).id || `sec_${i + 1}`))
    )
    paragraphBuckets.forEach((list, sectionRef) => {
      if (!sectionIdSet.has(sectionRef)) {
        unmatched.push(...list)
        paragraphBuckets.delete(sectionRef)
      }
    })
    const chapterChildren = sections.map((s, i) => {
      const sectionObj = s as Record<string, unknown>
      const sectionId = String(sectionObj.id || `sec_${i + 1}`)
      const paraForSection = paragraphBuckets.get(sectionId) || []
      return {
        title: `${sectionObj.name || `章节${i + 1}`} - ${sectionObj.summary || ''}`,
        key: `${x.id}|section|${i}`,
        children: paraForSection.map(({ p: pObj, idx: paragraphIndex }, j) => {
          const pBody = String(pObj.content || pObj.text || pObj.body || '')
          const pBodyPreview = pBody.length > 180 ? `${pBody.slice(0, 180)}...` : pBody
          return {
            title: `${pObj.name || `段落${j + 1}`} - ${pObj.summary || ''}`,
            key: `${x.id}|paragraph|${paragraphIndex}`,
            children: pBody
              ? [
                  {
                    title: `段落正文 - ${pBodyPreview}`,
                    key: `${x.id}|paragraph_body|${paragraphIndex}`,
                    isLeaf: true,
                  },
                ]
              : [],
          }
        }),
      }
    })
    if (unmatched.length) {
      chapterChildren.push({
        title: '未匹配章节',
        key: `${x.id}|section_unmatched`,
        children: unmatched.map(({ p: pObj, idx: i }) => {
          const pBody = String(pObj.content || pObj.text || pObj.body || '')
          const pBodyPreview = pBody.length > 180 ? `${pBody.slice(0, 180)}...` : pBody
          return {
            title: `${pObj.name || `段落${i + 1}`} - ${pObj.summary || ''}`,
            key: `${x.id}|paragraph|${i}`,
            children: pBody
              ? [
                  {
                    title: `段落正文 - ${pBodyPreview}`,
                    key: `${x.id}|paragraph_body|${i}`,
                    isLeaf: true,
                  },
                ]
              : [],
          }
        }),
      })
    }
    return {
      title: x.title || x.document_name || '文档结构',
      key: x.id,
      children: chapterChildren,
    }
  })
})
const selectedGraphNode = computed(() =>
  graphNodes.value.find((n) => String(n.id || '') === selectedGraphNodeId.value)
)
const centeredGraphData = computed(() => {
  const centerId = selectedGraphNodeId.value
  if (!centerId) return { nodes: [], edges: [] }
  const edges = graphEdges.value.filter(
    (e) => String(e.source || '') === centerId || String(e.target || '') === centerId
  )
  const relatedIds = new Set<string>([centerId])
  edges.forEach((e) => {
    relatedIds.add(String(e.source || ''))
    relatedIds.add(String(e.target || ''))
  })
  const nodes = graphNodes.value.filter((n) => relatedIds.has(String(n.id || '')))
  return { nodes, edges }
})
const graphSvg = computed(() => {
  const width = 700
  const height = 420
  const cx = width / 2
  const cy = height / 2
  const centerId = selectedGraphNodeId.value
  const center = centeredGraphData.value.nodes.find((n) => String(n.id || '') === centerId)
  if (!center) return { width, height, lines: [], circles: [], labels: [] }
  const others = centeredGraphData.value.nodes.filter((n) => String(n.id || '') !== centerId)
  const radius = 150
  const circles: { x: number; y: number; id: string; label: string; center: boolean }[] = [
    { x: cx, y: cy, id: centerId, label: String(center.label || center.id || ''), center: true },
  ]
  others.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(others.length, 1)
    circles.push({
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
      id: String(n.id || ''),
      label: String(n.label || n.id || ''),
      center: false,
    })
  })
  const byId = new Map(circles.map((c) => [c.id, c]))
  const lines = centeredGraphData.value.edges
    .map((e) => {
      const s = byId.get(String(e.source || ''))
      const t = byId.get(String(e.target || ''))
      if (!s || !t) return null
      return {
        x1: s.x,
        y1: s.y,
        x2: t.x,
        y2: t.y,
        relation: String(e.relation || ''),
        sourceLabel: s.label,
        targetLabel: t.label,
      }
    })
    .filter(Boolean) as {
    x1: number
    y1: number
    x2: number
    y2: number
    relation: string
    sourceLabel: string
    targetLabel: string
  }[]
  const labels = circles.map((c) => ({ x: c.x, y: c.y + 28, text: c.label }))
  return { width, height, lines, circles, labels }
})
const graphTripleColumns = [
  { title: '实体A', dataIndex: 'sourceLabel', key: 'sourceLabel', width: 180 },
  { title: '关系', dataIndex: 'relation', key: 'relation', width: 140 },
  { title: '实体B', dataIndex: 'targetLabel', key: 'targetLabel', width: 180 },
]
const graphTripleRows = computed(() => {
  const labelById = new Map(
    graphNodes.value.map((n) => [String(n.id || ''), String(n.label || n.id || '')])
  )
  return centeredGraphData.value.edges.map((e, idx) => {
    const sourceId = String(e.source || '')
    const targetId = String(e.target || '')
    return {
      key: `triple-${idx}-${sourceId}-${targetId}`,
      sourceLabel: labelById.get(sourceId) || sourceId,
      relation: String(e.relation || '关联'),
      targetLabel: labelById.get(targetId) || targetId,
    }
  })
})
function onGraphEdgeEnter(
  e: MouseEvent,
  edge: { sourceLabel: string; relation: string; targetLabel: string }
) {
  hoveredEdgeText.value = `${edge.sourceLabel} ${edge.relation || '关联'} ${edge.targetLabel}`
  hoveredEdgePos.value = { x: e.offsetX + 10, y: e.offsetY + 10 }
}
function onGraphEdgeMove(e: MouseEvent) {
  if (!hoveredEdgeText.value) return
  hoveredEdgePos.value = { x: e.offsetX + 10, y: e.offsetY + 10 }
}
function onGraphEdgeLeave() {
  hoveredEdgeText.value = ''
  hoveredEdgePos.value = null
}

async function loadCollections() {
  collections.value = await api.collections.list()
  if (!selectedCollectionId.value && collections.value.length) {
    const first = collections.value[0]
    if (first) selectedCollectionId.value = first.id
  }
}

async function loadJobs() {
  jobs.value = await api.knowledge.listJobs(50)
  if (!selectedJobId.value && jobs.value.length) {
    const first = jobs.value[0]
    if (first) {
      selectedJobId.value = first.job_id
      await selectJob(first.job_id)
    }
  }
}

async function loadResults() {
  if (!selectedCollectionId.value) return
  results.value = await api.knowledge.listResults({
    collection_id: selectedCollectionId.value,
    result_type: resultType.value || undefined,
    keyword: keyword.value.trim() || undefined,
  })
  originalContentMap.value = Object.fromEntries(results.value.map((x) => [x.id, x.content || '']))
}

async function loadGraph() {
  if (!selectedCollectionId.value) return
  const g = await api.knowledge.getGraph(selectedCollectionId.value, 300)
  graphNodes.value = g.nodes
  graphEdges.value = g.edges
  if (!selectedGraphNodeId.value || !graphNodes.value.some((x) => String(x.id || '') === selectedGraphNodeId.value)) {
    const first = graphNodes.value[0]
    selectedGraphNodeId.value = first ? String(first.id || '') : ''
  }
}

async function createJob() {
  if (!selectedCollectionId.value) {
    message.warning('请先选择文档集')
    return
  }
  extracting.value = true
  try {
    const job = await api.knowledge.createJob(selectedCollectionId.value)
    selectedJobId.value = job.job_id
    sessionStorage.setItem(STORAGE_KEY, job.job_id)
    jobLogs.value = job.logs || []
    running.value = true
    message.success('知识提取任务已启动')
    await loadJobs()
    startPolling()
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error).message || '启动失败')
  } finally {
    extracting.value = false
  }
}

async function selectJob(jobId?: string) {
  if (!jobId) return
  selectedJobId.value = jobId
  sessionStorage.setItem(STORAGE_KEY, jobId)
  const j = await api.knowledge.getJob(jobId)
  if (j.collection_id && selectedCollectionId.value !== j.collection_id) {
    selectedCollectionId.value = j.collection_id
  }
  jobLogs.value = j.logs || []
  running.value = j.status === 'running'
  if (selectedCollectionId.value) {
    await loadResults()
    await loadGraph()
    loadRetrieveHistoryForCollection(selectedCollectionId.value)
  }
}

function startPolling() {
  stopPolling()
  timer = setInterval(async () => {
    if (!selectedJobId.value) return
    try {
      const j = await api.knowledge.getJob(selectedJobId.value)
      jobLogs.value = j.logs || []
      running.value = j.status === 'running'
      if (!running.value) {
        stopPolling()
        await loadJobs()
        await loadResults()
        await loadGraph()
        if (j.status === 'completed') message.success('知识提取执行完成')
        else if (j.status === 'cancelled') message.info('知识提取已中止')
        else if (j.status === 'failed') message.warning('知识提取失败')
      }
    } catch {
      stopPolling()
      running.value = false
    }
  }, POLL_MS)
}

function stopPolling() {
  if (timer) clearInterval(timer)
  timer = null
}
function formatJobDate(dateStr?: string) {
  if (!dateStr) return '----/--/--'
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return '----/--/--'
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}/${m}/${day}`
}
function removeTag(item: KnowledgeResultItem, idx: number) {
  item.tags.splice(idx, 1)
}
function addTag(item: KnowledgeResultItem) {
  const val = window.prompt('请输入新标签')
  if (!val) return
  const tag = val.trim()
  if (!tag) return
  if (!item.tags.includes(tag)) item.tags.push(tag)
}
function shouldShowSave(item: KnowledgeResultItem) {
  if (activeTab.value !== 'summary' && activeTab.value !== 'points') return true
  return (item.content || '') !== (originalContentMap.value[item.id] || '')
}
function onStructureSelect(keys: (string | number)[], info: { node?: { title?: string } }) {
  const key = String(keys?.[0] ?? '')
  selectedStructureNodeKey.value = key
  selectedStructureNodeLabel.value = String(info?.node?.title ?? '')
  structureEditText.value = selectedStructureNodeLabel.value
}
function openStructureEditModal() {
  if (!selectedStructureNodeKey.value) return
  structureEditText.value = selectedStructureNodeLabel.value
  structureEditModalOpen.value = true
}
function parseStructureSelectionKey(key: string) {
  const [itemId, kind, idxStr] = key.split('|')
  const idx = Number(idxStr)
  if (!itemId || (kind !== 'section' && kind !== 'paragraph') || Number.isNaN(idx)) return null
  return { itemId, kind, idx }
}
const structureSelectionEditable = computed(() => !!parseStructureSelectionKey(selectedStructureNodeKey.value))
function pushStructureVersion(item: KnowledgeResultItem) {
  if (!structureVersionHistory.value[item.id]) structureVersionHistory.value[item.id] = []
  const stack = structureVersionHistory.value[item.id]
  if (!stack) return
  stack.push(item.content || '')
}
function editSelectedStructureNode() {
  const p = parseStructureSelectionKey(selectedStructureNodeKey.value)
  if (!p) return
  const item = results.value.find((x) => x.id === p.itemId)
  if (!item) return
  let obj: Record<string, unknown> = {}
  try {
    obj = JSON.parse(item.content || '{}')
  } catch {
    obj = {}
  }
  const arrKey = p.kind === 'section' ? 'sections' : 'paragraph_notes'
  const arr = Array.isArray(obj[arrKey]) ? (obj[arrKey] as Record<string, unknown>[]) : []
  const row = arr[p.idx]
  if (!row) return
  pushStructureVersion(item)
  const text = (structureEditText.value || '').trim()
  const splitIdx = text.indexOf(' - ')
  if (splitIdx > 0) {
    row.name = text.slice(0, splitIdx).trim()
    row.summary = text.slice(splitIdx + 3).trim()
  } else {
    row.summary = text
  }
  obj[arrKey] = arr
  item.content = JSON.stringify(obj, null, 2)
  selectedStructureNodeLabel.value = structureEditText.value
}
function deleteSelectedStructureNode() {
  const p = parseStructureSelectionKey(selectedStructureNodeKey.value)
  if (!p) return
  const item = results.value.find((x) => x.id === p.itemId)
  if (!item) return
  let obj: Record<string, unknown> = {}
  try {
    obj = JSON.parse(item.content || '{}')
  } catch {
    obj = {}
  }
  const arrKey = p.kind === 'section' ? 'sections' : 'paragraph_notes'
  const arr = Array.isArray(obj[arrKey]) ? (obj[arrKey] as Record<string, unknown>[]) : []
  if (!arr[p.idx]) return
  pushStructureVersion(item)
  arr.splice(p.idx, 1)
  obj[arrKey] = arr
  item.content = JSON.stringify(obj, null, 2)
  selectedStructureNodeKey.value = ''
  selectedStructureNodeLabel.value = ''
  structureEditText.value = ''
}
function rollbackSelectedStructureNode() {
  const p = parseStructureSelectionKey(selectedStructureNodeKey.value)
  if (!p) return
  const item = results.value.find((x) => x.id === p.itemId)
  if (!item) return
  const stack = structureVersionHistory.value[item.id] || []
  const prev = stack.pop()
  if (!prev) return
  item.content = prev
  selectedStructureNodeLabel.value = ''
  structureEditText.value = ''
}
function confirmStructureEdit() {
  editSelectedStructureNode()
  structureEditModalOpen.value = false
}

async function saveItem(item: KnowledgeResultItem) {
  await api.knowledge.updateResult(item.id, { title: item.title, content: item.content, tags: item.tags })
  originalContentMap.value[item.id] = item.content || ''
  message.success('保存成功')
  await loadResults()
}

async function removeItem(item: KnowledgeResultItem) {
  await api.knowledge.deleteResult(item.id)
  message.success('删除成功')
  await loadResults()
}

async function addItem() {
  if (!selectedCollectionId.value) return
  if (!newItem.value.title.trim() || !newItem.value.content.trim()) {
    message.warning('请填写标题与内容')
    return
  }
  await api.knowledge.createResult({
    collection_id: selectedCollectionId.value,
    document_id: newItem.value.document_id,
    document_name: newItem.value.document_name,
    result_type: newItem.value.result_type,
    title: newItem.value.title.trim(),
    content: newItem.value.content.trim(),
    tags: newItem.value.tags
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean),
  })
  message.success('新增成功')
  newItem.value.title = ''
  newItem.value.content = ''
  newItem.value.tags = ''
  await loadResults()
}

async function cancelCurrentJob() {
  if (!selectedJobId.value) {
    message.info('当前无可中止任务')
    return
  }
  try {
    await api.knowledge.cancelJob(selectedJobId.value)
    message.success('已发送中止指令')
    if (!timer) startPolling()
  } catch (e) {
    message.error((e as Error).message || '中止失败')
  }
}

async function runKnowledgeRetrieve() {
  if (!selectedCollectionId.value) {
    message.warning('请先选择文档集')
    return
  }
  if (!retrieveQuery.value.trim()) {
    message.warning('请输入问题')
    return
  }
  retrieveRunId.value += 1
  retrieveAnswer.value = ''
  retrieveRoute.value = ''
  retrieveCitations.value = []
  retrieveLogs.value = []
  retrieveLoading.value = true
  try {
    const res = await api.knowledge.retrieve(selectedCollectionId.value, retrieveQuery.value.trim(), 8)
    retrieveAnswer.value = res.answer || ''
    retrieveRoute.value = res.route || ''
    retrieveCitations.value = res.citations || []
    retrieveLogs.value = res.logs || []
    const q = retrieveQuery.value.trim()
    const snap: RetrieveSnapshot = {
      at: new Date().toISOString(),
      query: q,
      answer: res.answer || '',
      route: res.route || '',
      citations: JSON.parse(JSON.stringify(res.citations || [])),
      logs: JSON.parse(JSON.stringify(res.logs || [])),
    }
    const cid = selectedCollectionId.value
    if (cid) {
      retrieveHistorySnapshots.value = [snap, ...retrieveHistorySnapshots.value].slice(0, 3)
      persistRetrieveHistory(cid, retrieveHistorySnapshots.value)
      activeHistoryIndex.value = 0
    }
  } catch (e) {
    message.error((e as Error).message || '知识检索失败')
  } finally {
    retrieveLoading.value = false
  }
}

function _resultTypeByLayer(layer: string): string | null {
  if (layer === 'summary') return 'summary'
  if (layer === 'structure' || layer === 'paragraph') return 'structure'
  if (layer === 'knowledge_point') return 'knowledge_point'
  return null
}

async function jumpToCitation(item: KnowledgeRetrieveCitation) {
  if (item.layer === 'graph_triple') {
    activeTab.value = 'graph'
    if (!graphNodes.value.length && selectedCollectionId.value) await loadGraph()
    const md = (item.metadata || {}) as Record<string, unknown>
    const sourceId = String(md.source || '')
    const targetId = String(md.target || '')
    const targetNodeId = sourceId || targetId
    if (targetNodeId && graphNodes.value.some((x) => String(x.id || '') === targetNodeId)) {
      selectedGraphNodeId.value = targetNodeId
      message.success('已跳转到图谱节点')
      return
    }
    message.info('已切换到图谱标签，未定位到具体节点')
    return
  }

  const rt = _resultTypeByLayer(item.layer)
  if (!rt) {
    message.info('该引用暂不支持跳转')
    return
  }
  if (!results.value.length && selectedCollectionId.value) await loadResults()
  const candidates = results.value.filter((x) => x.result_type === rt)
  const best =
    candidates.find((x) => x.id === String((item.metadata || {}).id || '')) ||
    candidates.find(
      (x) =>
        (!item.document_id || x.document_id === item.document_id) &&
        x.content &&
        item.content &&
        (x.content.includes(item.content) || item.content.includes(x.content.slice(0, 20)))
    ) ||
    candidates.find((x) => !item.document_id || x.document_id === item.document_id) ||
    null
  if (!best) {
    message.info('未找到可跳转的结果项')
    return
  }
  activeTab.value = rt === 'knowledge_point' ? 'points' : rt
  setTimeout(() => {
    const el = document.getElementById(`result-item-${best.id}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('jump-highlight')
      window.setTimeout(() => el.classList.remove('jump-highlight'), 1200)
    }
  }, 30)
  message.success('已跳转到对应结果项')
}

onMounted(async () => {
  try {
    await loadCollections()
    await loadJobs()
    const last = sessionStorage.getItem(STORAGE_KEY)
    if (last) {
      const matched = jobs.value.find((x) => x.job_id === last)
      if (matched) await selectJob(last)
    }
    if (selectedCollectionId.value) {
      await loadResults()
      await loadGraph()
      loadRetrieveHistoryForCollection(selectedCollectionId.value)
    }
  } catch (e) {
    error.value = (e as Error).message
  }
})

onUnmounted(() => stopPolling())
</script>

<template>
  <div class="knowledge-view">
    <Alert v-if="error" type="error" :message="error" show-icon closable class="mb-16" />
    <Space direction="vertical" :size="16" style="width: 100%">
      <Card title="知识提取" size="small">
        <Form layout="inline">
          <Form.Item>
            <Select
              v-model:value="selectedCollectionId"
              style="width: 320px"
              placeholder="选择文档集"
              :options="collectionOptions"
              @change="onCollectionChange"
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" :loading="extracting" :disabled="!selectedCollectionId" @click="createJob">
              知识提取
            </Button>
          </Form.Item>
          <Form.Item>
            <Button danger :disabled="!running || !selectedJobId" @click="cancelCurrentJob">中止</Button>
          </Form.Item>
          <Form.Item>
            <Input
              v-model:value="keyword"
              placeholder="查询关键字"
              style="width: 220px"
              @press-enter="loadResults"
            />
          </Form.Item>
          <Form.Item>
            <Select
              v-model:value="resultType"
              style="width: 160px"
              allow-clear
              placeholder="结果类型"
              :options="[
                { value: 'summary', label: '概要' },
                { value: 'structure', label: '结构' },
                { value: 'knowledge_point', label: '知识点' },
              ]"
              @change="loadResults"
            />
          </Form.Item>
          <Form.Item>
            <Button @click="loadResults">查询</Button>
          </Form.Item>
        </Form>
      </Card>

      <Row :gutter="16">
        <Col :span="8">
          <Card title="执行任务与日志" size="small">
            <List :data-source="jobs" size="small" bordered class="job-list">
              <template #renderItem="{ item }">
                <List.Item @click="selectJob(item.job_id)" class="job-item">
                  <Space>
                    <span>{{ formatJobDate(item.started_at) }}</span>
                    <Tag :color="item.status === 'completed' ? 'success' : item.status === 'failed' ? 'error' : item.status === 'cancelled' ? 'warning' : 'processing'">
                      {{ item.status }}
                    </Tag>
                  </Space>
                </List.Item>
              </template>
            </List>
            <div class="logs-box">
              <div v-for="(l, i) in jobLogs" :key="i" class="log-line">
                [{{ l.time }}] {{ l.message }}
              </div>
            </div>
          </Card>
        </Col>
        <Col :span="16">
          <Card title="提取结果（可编辑）" size="small">
            <Tabs v-model:activeKey="activeTab">
              <Tabs.TabPane key="summary" tab="概要" />
              <Tabs.TabPane key="structure" tab="结构" />
              <Tabs.TabPane key="points" tab="知识点" />
              <Tabs.TabPane key="graph" tab="图谱" />
            </Tabs>

            <template v-if="activeTab !== 'graph'">
              <Collapse v-model:activeKey="newItemPanelActive" class="mb-16">
                <Collapse.Panel key="new-item" header="新增结果项">
                  <Space direction="vertical" style="width: 100%">
                    <Space>
                      <Select
                        v-model:value="newItem.result_type"
                        style="width: 180px"
                        :options="[
                          { value: 'summary', label: '概要' },
                          { value: 'structure', label: '结构' },
                          { value: 'knowledge_point', label: '知识点' },
                        ]"
                      />
                      <Input v-model:value="newItem.title" placeholder="标题" style="width: 260px" />
                    </Space>
                    <Input.TextArea v-model:value="newItem.content" :rows="3" placeholder="内容" />
                    <Input v-model:value="newItem.tags" placeholder="标签（逗号分隔）" />
                    <Button type="primary" @click="addItem">新增</Button>
                  </Space>
                </Collapse.Panel>
              </Collapse>

              <template v-if="activeTab === 'structure'">
                <Row>
                  <Col :span="24">
                    <div class="structure-tree-wrap">
                    <Tree
                      :tree-data="structureTreeData"
                      default-expand-all
                      class="structure-tree"
                      :selected-keys="selectedStructureNodeKey ? [selectedStructureNodeKey] : []"
                      @select="onStructureSelect"
                    />
                    <div v-if="structureSelectionEditable" class="structure-floating-actions">
                      <Button size="small" type="text" @click="openStructureEditModal">
                        <template #icon><EditOutlined /></template>
                      </Button>
                      <Button size="small" type="text" @click="rollbackSelectedStructureNode">
                        <template #icon><RollbackOutlined /></template>
                      </Button>
                      <Button size="small" type="text" danger @click="deleteSelectedStructureNode">
                        <template #icon><DeleteOutlined /></template>
                      </Button>
                    </div>
                    </div>
                  </Col>
                </Row>
              </template>
              <List v-else :data-source="filteredResults" bordered>
                <template #renderItem="{ item }">
                  <List.Item :id="`result-item-${item.id}`">
                    <Space direction="vertical" style="width: 100%">
                      <Input v-if="activeTab === 'structure'" v-model:value="item.title" />
                      <div class="summary-content-row">
                        <Input.TextArea v-model:value="item.content" :auto-size="{ minRows: 3 }" />
                        <Button
                          v-if="activeTab === 'summary' || activeTab === 'points'"
                          danger
                          size="small"
                          type="text"
                          class="summary-delete-btn"
                          @click="removeItem(item)"
                        >
                          <template #icon><DeleteOutlined /></template>
                        </Button>
                      </div>
                      <Input
                        v-if="activeTab === 'structure'"
                        :value="item.tags.join(',')"
                        @update:value="(v:string) => { item.tags = v.split(',').map(x=>x.trim()).filter(Boolean) }"
                      />
                      <Space wrap>
                        <Tag v-for="(tag, idx) in item.tags" :key="`${item.id}-${idx}-${tag}`" closable @close.prevent="removeTag(item, Number(idx))">
                          {{ tag }}
                        </Tag>
                        <Button size="small" type="dashed" @click="addTag(item)">
                          <template #icon><PlusOutlined /></template>
                        </Button>
                      </Space>
                      <Space>
                        <Button v-if="shouldShowSave(item)" type="primary" @click="saveItem(item)">保存</Button>
                        <Button v-if="activeTab === 'structure'" danger @click="removeItem(item)">删除</Button>
                      </Space>
                    </Space>
                  </List.Item>
                </template>
              </List>
            </template>

            <template v-else>
              <Row :gutter="12">
                <Col :span="8">
                  <Card size="small" title="图谱节点（左侧选择）">
                    <List :data-source="graphNodes" size="small" bordered class="graph-list">
                      <template #renderItem="{ item }">
                        <List.Item
                          :class="['graph-node-item', { active: String(item.id || '') === selectedGraphNodeId }]"
                          @click="selectedGraphNodeId = String(item.id || '')"
                        >
                          <div class="graph-item">
                            <div>{{ item.label || item.id }}</div>
                            <div class="graph-sub">{{ item.type }}</div>
                          </div>
                        </List.Item>
                      </template>
                    </List>
                  </Card>
                </Col>
                <Col :span="16">
                  <Card size="small" title="图谱可视化（以左侧节点为中心）">
                    <div class="graph-center-meta" v-if="selectedGraphNode">
                      中心节点：<strong>{{ selectedGraphNode.label || selectedGraphNode.id }}</strong>
                    </div>
                    <Space style="margin-bottom: 8px">
                      <Button
                        size="small"
                        :type="graphViewMode === 'visual' ? 'primary' : 'default'"
                        @click="graphViewMode = 'visual'"
                      >
                        可视化图形
                      </Button>
                      <Button
                        size="small"
                        :type="graphViewMode === 'triples' ? 'primary' : 'default'"
                        @click="graphViewMode = 'triples'"
                      >
                        三元组表格
                      </Button>
                    </Space>
                    <template v-if="graphViewMode === 'visual'">
                      <div class="graph-svg-wrap">
                        <svg
                          :width="graphSvg.width"
                          :height="graphSvg.height"
                          viewBox="0 0 700 420"
                          class="graph-svg"
                        >
                          <line
                            v-for="(ln, idx) in graphSvg.lines"
                            :key="`ln-${idx}`"
                            :x1="ln.x1"
                            :y1="ln.y1"
                            :x2="ln.x2"
                            :y2="ln.y2"
                            stroke="#91caff"
                            stroke-width="2"
                            class="graph-edge-line"
                            @mouseenter="onGraphEdgeEnter($event, ln)"
                            @mousemove="onGraphEdgeMove($event)"
                            @mouseleave="onGraphEdgeLeave"
                          />
                        <circle
                          v-for="c in graphSvg.circles"
                          :key="`c-${c.id}`"
                          :cx="c.x"
                          :cy="c.y"
                          :r="c.center ? 20 : 14"
                          :fill="c.center ? '#1677ff' : '#69b1ff'"
                          stroke="#fff"
                          stroke-width="2"
                        />
                        <text
                          v-for="(lb, idx) in graphSvg.labels"
                          :key="`lb-${idx}`"
                          :x="lb.x"
                          :y="lb.y"
                          text-anchor="middle"
                          font-size="12"
                          fill="#333"
                        >
                          {{ lb.text }}
                        </text>
                        </svg>
                        <div
                          v-if="hoveredEdgeText && hoveredEdgePos"
                          class="graph-edge-tooltip"
                          :style="{ left: `${hoveredEdgePos.x}px`, top: `${hoveredEdgePos.y}px` }"
                        >
                          {{ hoveredEdgeText }}
                        </div>
                      </div>
                    </template>
                    <template v-else>
                      <Table
                        size="small"
                        :columns="graphTripleColumns"
                        :data-source="graphTripleRows"
                        :pagination="{ pageSize: 8, hideOnSinglePage: true }"
                        :scroll="{ y: 360 }"
                      />
                    </template>
                  </Card>
                </Col>
              </Row>
            </template>
          </Card>
        </Col>
      </Row>
      <Card title="知识检索" size="small">
        <Space direction="vertical" style="width: 100%">
          <Space style="width: 100%">
            <Input
              v-model:value="retrieveQuery"
              placeholder="输入你的问题，例如：A 和 B 的关系是什么？"
              style="width: 640px"
              @press-enter="runKnowledgeRetrieve"
            />
            <Button type="primary" :loading="retrieveLoading" @click="runKnowledgeRetrieve">执行知识检索</Button>
            <Select
              v-if="retrieveHistorySnapshots.length"
              v-model:value="activeHistoryIndex"
              style="width: 380px"
              :options="retrieveHistorySelectOptions"
              placeholder="查看最近检索（最多3次）"
              @change="(v) => onPickRetrieveHistory(v)"
            />
          </Space>
          <Space :key="retrieveRunId" direction="vertical" style="width: 100%" class="retrieve-result-block">
            <div v-if="retrieveRoute" class="retrieve-route">检索路由：{{ retrieveRoute }}</div>
            <Card size="small" title="检索过程日志">
              <div class="logs-box retrieve-logs-box">
                <template v-if="retrieveLogs.length">
                  <div v-for="(l, i) in retrieveLogs" :key="`rlog-${i}`" class="log-line">
                    [{{ l.time }}] {{ l.message }}
                  </div>
                </template>
                <div v-else class="retrieve-logs-empty">
                  {{ retrieveLoading ? '检索进行中…' : '暂无检索过程日志' }}
                </div>
              </div>
            </Card>
            <Card size="small" title="回答">
              <div class="retrieve-answer">
                <template v-if="retrieveLoading">正在检索…</template>
                <template v-else>{{ retrieveAnswer || '暂无回答' }}</template>
              </div>
            </Card>
            <Card size="small" title="引用依据">
              <List
                v-if="retrieveCitations.length"
                :data-source="retrieveCitations"
                size="small"
                bordered
              >
                <template #renderItem="{ item }">
                  <List.Item>
                    <div class="citation-item">
                      <div class="citation-head">
                        <Tag>{{ item.layer === 'paragraph' ? '段落' : item.layer }}</Tag>
                        <span>{{ item.document_name || item.document_id || '-' }}</span>
                        <span>{{ item.section_path || '-' }}</span>
                        <span>score={{ item.score.toFixed(4) }}</span>
                        <Button size="small" type="link" @click="jumpToCitation(item)">跳转</Button>
                      </div>
                      <div class="citation-content">{{ item.content }}</div>
                    </div>
                  </List.Item>
                </template>
              </List>
              <div v-else-if="retrieveLoading" class="retrieve-logs-empty">检索进行中…</div>
              <div v-else class="retrieve-logs-empty">暂无引用</div>
            </Card>
          </Space>
        </Space>
      </Card>
    </Space>
    <Modal
      v-model:open="structureEditModalOpen"
      title="编辑章节/段落"
      ok-text="保存"
      cancel-text="取消"
      @ok="confirmStructureEdit"
    >
      <div class="structure-node-label">{{ selectedStructureNodeLabel }}</div>
      <Input.TextArea v-model:value="structureEditText" :auto-size="{ minRows: 4 }" />
    </Modal>
  </div>
</template>

<style scoped>
.knowledge-view { padding: 0; }
.mb-16 { margin-bottom: 16px; }
.job-list { max-height: 240px; overflow-y: auto; }
.job-item { cursor: pointer; }
.logs-box { margin-top: 12px; max-height: 340px; overflow-y: auto; background: #fafafa; padding: 10px; border-radius: 6px; }
.log-line { font-size: 12px; line-height: 1.6; border-bottom: 1px solid rgba(0,0,0,.04); padding: 3px 0; }
.graph-list { max-height: 420px; overflow-y: auto; }
.graph-item { width: 100%; }
.graph-sub { font-size: 12px; color: rgba(0,0,0,.45); }
.graph-node-item { cursor: pointer; }
.graph-node-item.active { background: rgba(22,119,255,.08); }
.graph-svg { width: 100%; max-width: 100%; background: #fafafa; border: 1px solid rgba(0,0,0,.06); border-radius: 6px; }
.graph-svg-wrap { position: relative; display: inline-block; width: 100%; }
.graph-edge-line { cursor: pointer; }
.graph-edge-tooltip {
  position: absolute;
  pointer-events: none;
  z-index: 3;
  max-width: 360px;
  font-size: 12px;
  line-height: 1.4;
  background: rgba(0, 0, 0, 0.82);
  color: #fff;
  padding: 6px 8px;
  border-radius: 4px;
  white-space: nowrap;
}
.graph-center-meta { margin-bottom: 8px; font-size: 13px; }
.structure-tree { background: #fff; border: 1px solid rgba(0,0,0,.06); border-radius: 6px; padding: 8px; }
.structure-tree :deep(.ant-tree-treenode) { margin-bottom: 0.5em; }
.structure-tree-wrap { position: relative; }
.structure-floating-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  display: inline-flex;
  gap: 4px;
  background: rgba(255,255,255,0.96);
  border: 1px solid rgba(0,0,0,.08);
  border-radius: 6px;
  padding: 2px 4px;
}
.summary-content-row { display: flex; align-items: flex-start; gap: 6px; width: 100%; }
.summary-delete-btn { margin-top: 2px; }
.structure-node-label { font-size: 12px; color: rgba(0,0,0,.65); margin-bottom: 8px; }
.structure-empty-tip { font-size: 12px; color: rgba(0,0,0,.45); }
.retrieve-route { font-size: 12px; color: rgba(0,0,0,.55); }
.retrieve-logs-box { max-height: 180px; margin-top: 0; }
.retrieve-logs-empty { font-size: 12px; color: rgba(0,0,0,.45); padding: 4px 0; }
.retrieve-answer { white-space: pre-wrap; line-height: 1.7; }
.citation-item { width: 100%; }
.citation-head { display: flex; gap: 8px; flex-wrap: wrap; font-size: 12px; color: rgba(0,0,0,.6); margin-bottom: 4px; }
.citation-content { font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.jump-highlight { background: rgba(22,119,255,.12); transition: background .2s; }
</style>
