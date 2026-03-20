<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  Alert,
  List,
  Space,
  message,
  Row,
  Col,
  Tag,
  Collapse,
} from 'ant-design-vue'
import { SaveOutlined, PlayCircleOutlined, DeleteOutlined, InsertRowAboveOutlined, StopOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { marked } from 'marked'
import { api } from '@/api/client'

const STORAGE_KEY = 'research_last_job_id'
const POLL_INTERVAL = 2000

const collections = ref<{ id: string; name: string }[]>([])
const savedPlans = ref<{ plan_id: string; topic: string; collection_id: string; collection_name: string; updated_at: string }[]>([])
const selectedPlanId = ref<string>()
const selectedId = ref<string>()
const topic = ref('')
const plan = ref<{
  plan_id: string
  topic: string
  steps: { index: number; content: string; status?: string }[]
} | null>(null)
const stepsEditable = ref(true)
const jobHistory = ref<{ job_id: string; topic: string; status: string; progress?: string; started_at?: string }[]>([])
const selectedJobId = ref<string | null>(null)
const selectedJobDetail = ref<{
  job_id: string
  status: string
  result_markdown?: string
  progress?: string
  output_path?: string
  logs?: { time: string; message: string; level?: string; document?: string; agent?: string; response_preview?: string }[]
} | null>(null)
const loading = ref(false)
const executingResearch = ref(false)
const logsListRef = ref<HTMLElement | null>(null)
const error = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

watch(
  () => selectedJobDetail.value?.logs,
  () => {
    nextTick(() => {
      logsListRef.value?.scrollTo({ top: logsListRef.value.scrollHeight, behavior: 'smooth' })
    })
  },
  { deep: true }
)

async function loadCollections() {
  try {
    collections.value = await api.collections.list()
    const first = collections.value[0]
    if (first && !selectedId.value) selectedId.value = first.id
  } catch (e) {
    error.value = (e as Error).message
  }
}

async function loadSavedPlans() {
  try {
    const list = await api.research.listPlans()
    savedPlans.value = list.map((p) => ({
      plan_id: p.plan_id,
      topic: p.topic,
      collection_id: p.collection_id,
      collection_name: p.collection_name,
      updated_at: p.updated_at,
    }))
  } catch (e) {
    savedPlans.value = []
  }
}

async function onPlanSelect(value: unknown) {
  const planId = typeof value === 'string' ? value : undefined
  if (!planId) {
    selectedPlanId.value = undefined
    plan.value = null
    topic.value = ''
    return
  }
  try {
    const p = await api.research.getPlan(planId)
    selectedPlanId.value = planId
    if (p.collection_id) selectedId.value = p.collection_id
    topic.value = p.topic
    plan.value = {
      plan_id: p.plan_id,
      topic: p.topic,
      steps: p.steps.map((s, i) => ({ ...s, index: i })),
    }
    stepsEditable.value = true
  } catch (e) {
    message.error('加载计划失败')
  }
}

async function generatePlan() {
  if (!selectedId.value || !topic.value.trim()) return
  try {
    error.value = ''
    loading.value = true
    plan.value = await api.research.generatePlan(selectedId.value, topic.value.trim())
    stepsEditable.value = true
    await loadSavedPlans()
    selectedPlanId.value = plan.value.plan_id
    message.success('研究计划已生成')
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error)?.message ?? '操作失败')
  } finally {
    loading.value = false
  }
}

async function savePlan() {
  if (!plan.value) return
  try {
    error.value = ''
    loading.value = true
    plan.value = await api.research.updatePlan(plan.value.plan_id, plan.value.steps)
    await loadSavedPlans()
    message.success('计划已保存')
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error)?.message ?? '操作失败')
  } finally {
    loading.value = false
  }
}

function addStep() {
  if (!plan.value) return
  const idx = plan.value.steps.length
  plan.value.steps.push({ index: idx, content: '', status: 'pending' })
}

function insertStepBefore(i: number) {
  if (!plan.value) return
  plan.value.steps.splice(i, 0, { index: i, content: '', status: 'pending' })
  plan.value.steps.forEach((s, j) => (s.index = j))
}

function removeStep(i: number) {
  if (!plan.value) return
  plan.value.steps.splice(i, 1)
  plan.value.steps.forEach((s, j) => (s.index = j))
}

async function loadJobHistory() {
  try {
    jobHistory.value = await api.research.listJobs()
  } catch {
    jobHistory.value = []
  }
}

async function selectJob(jobId: string | null) {
  selectedJobId.value = jobId
  if (!jobId) {
    selectedJobDetail.value = null
    return
  }
  try {
    const job = await api.research.getJob(jobId)
    selectedJobDetail.value = {
      job_id: job.job_id,
      status: job.status,
      result_markdown: job.result_markdown,
      progress: job.progress,
      output_path: job.output_path,
      logs: job.logs || [],
    }
    if (job.status === 'running') {
      executingResearch.value = true
      startPolling()
    } else {
      stopPolling()
      executingResearch.value = false
    }
  } catch {
    selectedJobDetail.value = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (!selectedJobId.value) return
    try {
      const job = await api.research.getJob(selectedJobId.value)
      if (selectedJobDetail.value) {
        selectedJobDetail.value = {
          ...selectedJobDetail.value,
          status: job.status,
          result_markdown: job.result_markdown ?? selectedJobDetail.value.result_markdown,
          progress: job.progress,
          output_path: job.output_path ?? selectedJobDetail.value.output_path,
          logs: job.logs ?? selectedJobDetail.value.logs,
        }
      }
      if (job.status !== 'running') {
        stopPolling()
        executingResearch.value = false
        stepsEditable.value = true
        loadJobHistory()
        if (job.status === 'completed') {
          message.success('研究执行完成')
        } else if (job.status === 'cancelled') {
          message.info('任务已中止')
        } else if (job.status === 'failed' || job.status === 'interrupted') {
          message.warning('研究任务未成功完成')
        }
      }
    } catch {
      stopPolling()
    }
  }, POLL_INTERVAL)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function abortResearch() {
  const jid = selectedJobId.value || sessionStorage.getItem(STORAGE_KEY)
  if (!jid) {
    stopPolling()
    executingResearch.value = false
    message.info('没有可中止的任务')
    return
  }
  try {
    await api.research.cancelJob(jid)
    message.success('已发送中止指令，未执行的步骤将不再运行')
    await loadJobHistory()
    await selectJob(jid)
    if (!pollTimer) startPolling()
  } catch (e) {
    const msg = (e as Error)?.message ?? ''
    if (
      msg.includes('not running') ||
      msg.includes('Job is not running') ||
      msg.includes('not found') ||
      msg.includes('not running on this server')
    ) {
      stopPolling()
      executingResearch.value = false
      stepsEditable.value = true
      message.info('任务已结束或未在运行')
      await loadJobHistory()
      if (selectedJobId.value) await selectJob(selectedJobId.value)
    } else {
      message.error(msg || '中止失败')
    }
  }
}

async function runResearch() {
  if (!plan.value || !selectedId.value || !topic.value.trim()) return
  try {
    error.value = ''
    loading.value = true
    stepsEditable.value = false
    plan.value = await api.research.updatePlan(plan.value.plan_id, plan.value.steps)
    const job = await api.research.runJob(
      selectedId.value,
      plan.value.plan_id,
      topic.value.trim()
    )
    sessionStorage.setItem(STORAGE_KEY, job.job_id)
    await loadJobHistory()
    await selectJob(job.job_id)
    message.info('研究任务已在后台执行')
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error)?.message ?? '操作失败')
    stepsEditable.value = true
  } finally {
    loading.value = false
  }
}

const renderedMarkdown = computed(() => {
  const md = selectedJobDetail.value?.result_markdown || ''
  if (!md) return ''
  return marked.parse(md)
})

const selectedJobLogs = computed(() => selectedJobDetail.value?.logs ?? [])

const selectOptions = computed(() =>
  collections.value.map((c) => ({ value: c.id, label: c.name }))
)

const planOptions = computed(() =>
  savedPlans.value.map((p) => ({
    value: p.plan_id,
    label: `${p.topic} (${p.collection_name || p.collection_id})`,
  }))
)

onMounted(async () => {
  loadCollections()
  loadSavedPlans()
  await loadJobHistory()
  const lastId = sessionStorage.getItem(STORAGE_KEY)
  if (lastId) {
    try {
      const job = await api.research.getJob(lastId)
      if (job.status === 'running') {
        await selectJob(lastId)
      }
    } catch {
      // Job may not exist, ignore
    }
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="research-view">
    <Alert v-if="error" type="error" :message="error" show-icon closable class="mb-24" />

    <Space direction="vertical" :size="24" style="width: 100%">
      <Card title="选择文档集与主题" size="small">
        <Form layout="inline" :label-col="{ span: 0 }">
          <Form.Item>
            <Select
              v-model:value="selectedPlanId"
              placeholder="选择执行计划"
              style="width: 260px"
              :options="planOptions"
              allow-clear
              @change="onPlanSelect"
            />
          </Form.Item>
          <Form.Item>
            <Select
              v-model:value="selectedId"
              placeholder="选择文档集"
              style="width: 200px"
              :options="selectOptions"
              allow-clear
            />
          </Form.Item>
          <Form.Item>
            <Input
              v-model:value="topic"
              placeholder="研究主题"
              style="width: 280px"
              @press-enter="generatePlan"
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              :loading="loading && !executingResearch"
              :disabled="!selectedId || !topic.trim() || executingResearch"
              @click="generatePlan"
            >
              制定研究计划
            </Button>
          </Form.Item>
          <Form.Item v-if="executingResearch">
            <Button danger @click="abortResearch">
              <template #icon><StopOutlined /></template>
              中止
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card v-if="plan" title="研究计划" size="small">
        <List :data-source="plan.steps" bordered size="small">
          <template #renderItem="{ item, index }">
            <List.Item>
              <template v-if="stepsEditable">
                <div class="step-row">
                  <span class="step-num">{{ index + 1 }}.</span>
                  <Input.TextArea
                    v-model:value="item.content"
                    placeholder="步骤内容"
                    :autosize="{ minRows: 1, maxRows: 4 }"
                    class="step-input"
                  />
                  <Button
                    type="text"
                    size="small"
                    title="在此行前插入步骤"
                    @click="insertStepBefore(index)"
                  >
                    <template #icon><InsertRowAboveOutlined /></template>
                  </Button>
                  <Button
                    type="text"
                    danger
                    size="small"
                    @click="removeStep(index)"
                  >
                    <template #icon><DeleteOutlined /></template>
                  </Button>
                </div>
              </template>
              <template v-else>
                <Space>
                  <span class="step-num">{{ index + 1 }}.</span>
                  <span>{{ item.content }}</span>
                  <span class="step-status">{{ item.status || 'pending' }}</span>
                </Space>
              </template>
            </List.Item>
          </template>
        </List>
        <div v-if="stepsEditable" class="plan-actions">
          <Space>
            <Button @click="addStep">
              <template #icon><PlusOutlined /></template>
              增加步骤
            </Button>
            <Button type="default" @click="savePlan">
              <template #icon><SaveOutlined /></template>
              保存计划
            </Button>
            <Button
              type="primary"
              :loading="loading"
              :disabled="!plan.steps.some((s) => s.content.trim()) || executingResearch"
              @click="runResearch"
            >
              <template #icon><PlayCircleOutlined /></template>
              执行研究计划
            </Button>
          </Space>
        </div>
      </Card>

      <Card title="研究执行结果" size="small">
        <Row :gutter="16">
          <Col :span="8">
            <div class="history-list">
              <div
                v-for="j in jobHistory"
                :key="j.job_id"
                :class="['history-item', { active: selectedJobId === j.job_id }]"
                @click="selectJob(j.job_id)"
              >
                <div class="history-item-main">
                  <span class="history-topic">{{ j.topic || '未命名' }}</span>
                  <Tag
                    :color="
                      j.status === 'completed'
                        ? 'success'
                        : j.status === 'cancelled'
                          ? 'warning'
                          : j.status === 'failed' || j.status === 'interrupted'
                            ? 'error'
                            : 'processing'
                    "
                  >
                    {{
                      j.status === 'running'
                        ? '进行中'
                        : j.status === 'completed'
                          ? '成功'
                          : j.status === 'cancelled'
                            ? '已中止'
                            : j.status === 'interrupted'
                              ? '已中断'
                              : j.status
                    }}
                  </Tag>
                </div>
                <div class="history-item-meta">
                  {{ j.started_at ? new Date(j.started_at).toLocaleString() : '' }}
                </div>
                <Collapse
                  ghost
                  class="job-id-collapse"
                  @click.stop
                >
                  <Collapse.Panel key="jid" header="查看 job_id">
                    <code class="job-id-code">{{ j.job_id }}</code>
                  </Collapse.Panel>
                </Collapse>
              </div>
              <div v-if="!jobHistory.length" class="no-history">暂无执行记录</div>
            </div>
          </Col>
          <Col :span="16">
            <template v-if="selectedJobDetail">
              <template v-if="selectedJobDetail.status === 'running'">
                <Alert type="info" show-icon class="mb-16">
                  <template #message>后台执行中，请稍候</template>
                </Alert>
                <div v-if="selectedJobDetail.progress" class="progress-text">{{ selectedJobDetail.progress }}</div>
                <div class="execution-logs-section">
                  <div class="logs-section-title">执行日志</div>
                  <div v-if="selectedJobLogs.length" ref="logsListRef" class="logs-list">
                    <div
                      v-for="(log, idx) in selectedJobLogs"
                      :key="idx"
                      :class="['log-entry', `log-${log.level || 'info'}`]"
                    >
                      <span class="log-time">[{{ log.time }}]</span>
                      <span v-if="log.agent" class="log-agent">{{ log.agent }}</span>
                      <span v-if="log.document" class="log-doc">{{ log.document }}</span>
                      <span class="log-msg">{{ log.message }}</span>
                      <div v-if="log.response_preview" class="log-response-preview">
                        <span class="log-response-label">智能体返回：</span>
                        <pre class="log-response-content">{{ log.response_preview }}</pre>
                      </div>
                    </div>
                  </div>
                  <div v-else class="no-logs">暂无执行日志</div>
                </div>
              </template>
              <template v-else>
                <Alert
                  v-if="selectedJobDetail.status === 'cancelled'"
                  type="warning"
                  show-icon
                  class="mb-16"
                >
                  <template #message>
                    {{ selectedJobDetail.progress || '任务已由用户中止' }}
                  </template>
                </Alert>
                <Alert
                  v-else-if="selectedJobDetail.status === 'failed' || selectedJobDetail.status === 'interrupted'"
                  type="error"
                  show-icon
                  class="mb-16"
                >
                  <template #message>
                    {{ selectedJobDetail.progress || '任务未成功完成' }}
                  </template>
                </Alert>
                <Alert
                  v-if="selectedJobDetail.output_path"
                  type="info"
                  show-icon
                  class="mb-16"
                >
                  <template #message>
                    已保存到：<code class="output-path">{{ selectedJobDetail.output_path }}</code>
                    <br />
                    <small>包含 plan.md（研究计划）、final.md（合并报告）、各文档的 *_result.md</small>
                  </template>
                </Alert>
                <div class="result-section-title">研究结果</div>
                <div
                  v-if="renderedMarkdown"
                  class="markdown-preview"
                  v-html="renderedMarkdown"
                ></div>
                <div
                  v-else
                  class="no-result-md"
                >
                  暂无 final.md 内容（可能失败或尚未生成）
                </div>
                <div
                  v-if="
                    selectedJobLogs.length &&
                    (selectedJobDetail.status === 'failed' ||
                      selectedJobDetail.status === 'interrupted' ||
                      selectedJobDetail.status === 'cancelled')
                  "
                  class="execution-logs-section execution-logs-after-result"
                >
                  <div class="logs-section-title">执行日志</div>
                  <div ref="logsListRef" class="logs-list">
                    <div
                      v-for="(log, idx) in selectedJobLogs"
                      :key="idx"
                      :class="['log-entry', `log-${log.level || 'info'}`]"
                    >
                      <span class="log-time">[{{ log.time }}]</span>
                      <span v-if="log.agent" class="log-agent">{{ log.agent }}</span>
                      <span v-if="log.document" class="log-doc">{{ log.document }}</span>
                      <span class="log-msg">{{ log.message }}</span>
                      <div v-if="log.response_preview" class="log-response-preview">
                        <span class="log-response-label">智能体返回：</span>
                        <pre class="log-response-content">{{ log.response_preview }}</pre>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </template>
            <div v-else class="no-selection">请从左侧选择或执行研究任务</div>
          </Col>
        </Row>
      </Card>
    </Space>
  </div>
</template>

<style scoped>
.research-view {
  padding: 0;
}
.mb-24 {
  margin-bottom: 24px;
}
.mb-16 {
  margin-bottom: 16px;
}
.result-section-title {
  font-weight: 600;
  margin: 16px 0 8px;
  font-size: 14px;
}
.output-path {
  font-size: 12px;
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  word-break: break-all;
}
.step-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}
.step-row .step-num {
  font-weight: 600;
  min-width: 24px;
  flex-shrink: 0;
  padding-top: 5px;
}
.step-row .step-input {
  flex: 1;
  min-width: 0;
  resize: none;
}
.step-status {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
}
.plan-actions {
  margin-top: 16px;
}
.job-id-collapse {
  margin-top: 4px;
}
.job-id-collapse :deep(.ant-collapse-header) {
  padding: 4px 0 !important;
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
}
.job-id-code {
  font-size: 11px;
  word-break: break-all;
}
.no-result-md {
  font-size: 13px;
  color: rgba(0, 0, 0, 0.45);
  padding: 12px 0;
}
.execution-logs-after-result {
  margin-top: 16px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  padding-top: 12px;
}
.execution-logs-section {
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}
.logs-section-title {
  font-weight: 600;
  margin-bottom: 8px;
  font-size: 14px;
}
.no-logs {
  color: rgba(0, 0, 0, 0.45);
  font-size: 13px;
}
.logs-list {
  max-height: 320px;
  overflow-y: auto;
  font-family: ui-monospace, monospace;
  font-size: 13px;
  line-height: 1.6;
}
.log-entry {
  padding: 4px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
}
.log-entry:last-child {
  border-bottom: none;
}
.log-response-preview {
  width: 100%;
  margin-top: 6px;
  padding: 8px;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 4px;
  font-size: 12px;
}
.log-response-label {
  color: rgba(0, 0, 0, 0.45);
  display: block;
  margin-bottom: 4px;
}
.log-response-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}
.log-time {
  color: rgba(0, 0, 0, 0.45);
  flex-shrink: 0;
}
.log-agent {
  font-size: 11px;
  color: #722ed1;
  background: rgba(114, 46, 209, 0.08);
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.log-doc {
  color: #1677ff;
  font-weight: 500;
  flex-shrink: 0;
}
.log-msg {
  flex: 1;
  min-width: 0;
}
.log-entry.log-success .log-msg {
  color: #52c41a;
  font-weight: 500;
}
.log-entry.log-error .log-msg {
  color: #ff4d4f;
  font-weight: 500;
}
.markdown-preview {
  padding: 16px;
  background: #fafafa;
  border-radius: 6px;
  max-height: 600px;
  overflow-y: auto;
  line-height: 1.6;
}
.markdown-preview :deep(h1) {
  font-size: 24px;
  margin: 16px 0 8px;
}
.markdown-preview :deep(h2) {
  font-size: 20px;
  margin: 16px 0 8px;
}
.markdown-preview :deep(p) {
  margin: 8px 0;
}
.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  margin: 8px 0;
  padding-left: 24px;
}
.markdown-preview :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
}
.markdown-preview :deep(pre) {
  overflow-x: auto;
  padding: 12px;
  background: rgba(0, 0, 0, 0.04);
  border-radius: 6px;
}
.history-list {
  max-height: 480px;
  overflow-y: auto;
}
.history-item {
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
}
.history-item:hover {
  background: rgba(0, 0, 0, 0.02);
}
.history-item.active {
  border-color: #1677ff;
  background: rgba(22, 119, 255, 0.06);
}
.history-item-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.history-topic {
  font-weight: 500;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-item-meta {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
}
.no-history,
.no-selection {
  color: rgba(0, 0, 0, 0.45);
  font-size: 14px;
  padding: 16px 0;
}
.progress-text {
  font-size: 13px;
  color: rgba(0, 0, 0, 0.65);
  margin-bottom: 12px;
}
</style>
