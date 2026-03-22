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
  Modal,
} from 'ant-design-vue'
import {
  SaveOutlined,
  PlayCircleOutlined,
  DeleteOutlined,
  InsertRowAboveOutlined,
  StopOutlined,
  PlusOutlined,
  DownloadOutlined,
  CopyOutlined,
} from '@ant-design/icons-vue'
import { marked } from 'marked'
import { api, type ResearchJobLogEntry } from '@/api/client'

const STORAGE_KEY = 'research_last_job_id'
const POLL_INTERVAL = 2000

const collections = ref<{ id: string; name: string }[]>([])
const savedPlans = ref<
  {
    plan_id: string
    title?: string | null
    topic: string
    collection_id: string
    collection_name: string
    updated_at: string
  }[]
>([])
const selectedPlanId = ref<string>()
const plan = ref<{
  plan_id: string
  title?: string | null
  topic: string
  collection_id?: string
  steps: { index: number; content: string; status?: string }[]
} | null>(null)
const projectModalVisible = ref(false)
const newProjectCollectionId = ref<string>()
const newProjectTitle = ref('')
const newProjectTopic = ref('')
const creatingProject = ref(false)
const reusePlanModalVisible = ref(false)
const reuseSourcePlanId = ref<string>()
const reusePlanSubmitting = ref(false)
const stepsEditable = ref(true)
const jobHistory = ref<
  { job_id: string; topic: string; title?: string | null; status: string; progress?: string; started_at?: string }[]
>([])
const selectedJobId = ref<string | null>(null)
const selectedJobDetail = ref<{
  job_id: string
  status: string
  result_markdown?: string
  progress?: string
  output_path?: string
  logs?: ResearchJobLogEntry[]
} | null>(null)
const loading = ref(false)
const resumeLoading = ref(false)
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
  } catch (e) {
    error.value = (e as Error).message
  }
}

async function loadSavedPlans() {
  try {
    const list = await api.research.listPlans()
    savedPlans.value = list.map((p) => ({
      plan_id: p.plan_id,
      title: p.title,
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
    return
  }
  try {
    const p = await api.research.getPlan(planId)
    selectedPlanId.value = planId
    plan.value = {
      plan_id: p.plan_id,
      title: p.title,
      topic: p.topic,
      collection_id: p.collection_id,
      steps: p.steps.map((s, i) => ({ ...s, index: i })),
    }
    stepsEditable.value = true
  } catch (e) {
    message.error('加载研究项目失败')
  }
}

function planDropdownLabel(p: { title?: string | null; topic?: string }) {
  if (p.title != null && String(p.title).trim()) return String(p.title).trim()
  return (p.topic != null ? String(p.topic) : '').trim()
}

function openCreateProjectModal() {
  projectModalVisible.value = true
  if (!newProjectCollectionId.value && collections.value.length) {
    const first = collections.value[0]
    if (first) newProjectCollectionId.value = first.id
  }
}

async function submitCreateProject() {
  if (
    !newProjectCollectionId.value ||
    !newProjectTitle.value.trim() ||
    !newProjectTopic.value.trim()
  ) {
    message.warning('请填写研究标题、选择文档集并填写研究主题')
    throw new Error('CREATE_PROJECT_VALIDATION')
  }
  try {
    error.value = ''
    creatingProject.value = true
    const p = await api.research.createResearchProject(
      newProjectCollectionId.value,
      newProjectTopic.value.trim(),
      newProjectTitle.value.trim()
    )
    await loadSavedPlans()
    selectedPlanId.value = p.plan_id
    plan.value = {
      plan_id: p.plan_id,
      title: p.title,
      topic: p.topic,
      collection_id: p.collection_id,
      steps: (p.steps || []).map((s, i) => ({ ...s, index: i })),
    }
    stepsEditable.value = true
    newProjectTitle.value = ''
    newProjectTopic.value = ''
    projectModalVisible.value = false
    message.success('研究项目已创建')
  } catch (e) {
    if ((e as Error).message !== 'CREATE_PROJECT_VALIDATION') {
      error.value = (e as Error).message
      message.error((e as Error)?.message ?? '创建失败')
    }
    throw e
  } finally {
    creatingProject.value = false
  }
}

function openReusePlanModal() {
  if (!plan.value?.plan_id) {
    message.warning('请先选择当前要编辑的研究项目')
    return
  }
  reuseSourcePlanId.value = undefined
  reusePlanModalVisible.value = true
  loadSavedPlans()
}

async function submitReusePlan() {
  if (!plan.value?.plan_id) {
    message.warning('请先选择当前要编辑的研究项目')
    throw new Error('REUSE_PLAN_VALIDATION')
  }
  if (!reuseSourcePlanId.value) {
    message.warning('请选择要复用其研究计划的来源项目')
    throw new Error('REUSE_PLAN_VALIDATION')
  }
  if (reuseSourcePlanId.value === plan.value.plan_id) {
    message.warning('不能选择当前项目作为来源')
    throw new Error('REUSE_PLAN_VALIDATION')
  }
  try {
    error.value = ''
    reusePlanSubmitting.value = true
    const src = await api.research.getPlan(reuseSourcePlanId.value)
    const rawSteps = src.steps || []
    if (!rawSteps.length) {
      message.warning('所选项目暂无研究步骤')
      throw new Error('REUSE_PLAN_VALIDATION')
    }
    const newSteps = rawSteps.map((s, i) => ({
      index: i,
      content: typeof s.content === 'string' ? s.content : String(s.content ?? ''),
      status: (s.status && String(s.status)) || 'pending',
    }))
    const updated = await api.research.updatePlan(plan.value.plan_id, newSteps)
    plan.value = {
      plan_id: updated.plan_id,
      title: updated.title ?? plan.value.title,
      topic: updated.topic,
      collection_id: updated.collection_id ?? plan.value.collection_id,
      steps: updated.steps.map((s, i) => ({ ...s, index: i })),
    }
    await loadSavedPlans()
    selectedPlanId.value = plan.value.plan_id
    reusePlanModalVisible.value = false
    reuseSourcePlanId.value = undefined
    message.success('已复用研究计划步骤到当前项目，可继续编辑后保存或执行')
  } catch (e) {
    if ((e as Error).message !== 'REUSE_PLAN_VALIDATION') {
      error.value = (e as Error).message
      message.error((e as Error)?.message ?? '复用失败')
    }
    throw e
  } finally {
    reusePlanSubmitting.value = false
  }
}

async function generatePlan() {
  if (!plan.value?.plan_id || !plan.value.collection_id || !plan.value.topic?.trim()) {
    message.warning('请先选择或创建研究项目')
    return
  }
  try {
    error.value = ''
    loading.value = true
    const prevCollectionId = plan.value.collection_id
    const p = await api.research.generatePlan(
      plan.value.collection_id,
      plan.value.topic.trim(),
      plan.value.plan_id
    )
    plan.value = {
      plan_id: p.plan_id,
      title: p.title ?? plan.value.title,
      topic: p.topic,
      collection_id: p.collection_id ?? prevCollectionId,
      steps: p.steps.map((s, i) => ({ ...s, index: i })),
    }
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
    const updated = await api.research.updatePlan(plan.value.plan_id, plan.value.steps)
    plan.value = {
      plan_id: updated.plan_id,
      title: updated.title ?? plan.value.title,
      topic: updated.topic,
      collection_id: updated.collection_id ?? plan.value.collection_id,
      steps: updated.steps.map((s, i) => ({ ...s, index: i })),
    }
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
  if (!plan.value?.collection_id || !plan.value.topic?.trim()) return
  try {
    error.value = ''
    loading.value = true
    stepsEditable.value = false
    const updated = await api.research.updatePlan(plan.value.plan_id, plan.value.steps)
    const collectionId = updated.collection_id ?? plan.value.collection_id
    plan.value = {
      plan_id: updated.plan_id,
      title: updated.title ?? plan.value.title,
      topic: updated.topic,
      collection_id: collectionId,
      steps: updated.steps.map((s, i) => ({ ...s, index: i })),
    }
    if (!collectionId) {
      message.error('缺少文档集信息，无法执行')
      stepsEditable.value = true
      return
    }
    const job = await api.research.runJob(
      collectionId,
      plan.value.plan_id,
      plan.value.topic.trim()
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

const canResumeSelectedJob = computed(() => {
  const d = selectedJobDetail.value
  if (!d || executingResearch.value) return false
  return d.status === 'cancelled' || d.status === 'interrupted'
})

async function resumeResearch() {
  const jid = selectedJobId.value
  if (!jid) return
  try {
    error.value = ''
    resumeLoading.value = true
    stepsEditable.value = false
    await api.research.resumeJob(jid)
    sessionStorage.setItem(STORAGE_KEY, jid)
    await loadJobHistory()
    await selectJob(jid)
    message.success('已从已保存进度继续执行，将跳过已完成步骤')
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error)?.message ?? '继续执行失败')
    stepsEditable.value = true
  } finally {
    resumeLoading.value = false
  }
}

const renderedMarkdown = computed(() => {
  const md = selectedJobDetail.value?.result_markdown || ''
  if (!md) return ''
  return marked.parse(md)
})

const selectedJobLogs = computed(() => selectedJobDetail.value?.logs ?? [])

/** 同源相对路径，开发环境经 Vite 代理到后端 */
const researchDownloadFinalUrl = computed(() => {
  const id = selectedJobId.value
  return id ? `/api/v1/research/jobs/${encodeURIComponent(id)}/download/final` : ''
})
const researchDownloadPackageUrl = computed(() => {
  const id = selectedJobId.value
  return id ? `/api/v1/research/jobs/${encodeURIComponent(id)}/download/package` : ''
})

const selectOptions = computed(() =>
  collections.value.map((c) => ({ value: c.id, label: c.name }))
)

const planOptions = computed(() =>
  savedPlans.value.map((p) => ({
    value: p.plan_id,
    label: planDropdownLabel(p),
  }))
)

const selectedProjectTitleDisplay = computed(() => {
  if (!plan.value) return '—'
  return planDropdownLabel(plan.value)
})

const selectedCollectionLabel = computed(() => {
  if (!plan.value?.collection_id) return '—'
  const row = savedPlans.value.find((p) => p.plan_id === plan.value?.plan_id)
  if (row?.collection_name) return row.collection_name
  const c = collections.value.find((x) => x.id === plan.value!.collection_id)
  return c?.name || plan.value.collection_id
})

const canGeneratePlan = computed(
  () =>
    !!plan.value?.plan_id &&
    !!plan.value.collection_id &&
    !!plan.value.topic?.trim() &&
    !executingResearch.value
)

const canReusePlan = computed(() => !!plan.value?.plan_id && !executingResearch.value)

const reusePlanSelectOptions = computed(() =>
  savedPlans.value
    .filter((p) => p.plan_id !== plan.value?.plan_id)
    .map((p) => ({
      value: p.plan_id,
      label: `${planDropdownLabel(p)}${p.collection_name ? ` · ${p.collection_name}` : ''}`,
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
      <Card title="研究项目" size="small">
        <Form layout="inline" :label-col="{ span: 0 }">
          <Form.Item>
            <Select
              v-model:value="selectedPlanId"
              placeholder="选择研究项目"
              style="width: min(100%, 360px)"
              :options="planOptions"
              allow-clear
              @change="onPlanSelect"
            />
          </Form.Item>
          <Form.Item>
            <Button @click="openCreateProjectModal">创建研究项目</Button>
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              :loading="loading && !executingResearch"
              :disabled="!canGeneratePlan"
              @click="generatePlan"
            >
              制定研究计划
            </Button>
          </Form.Item>
          <Form.Item>
            <Button :disabled="!canReusePlan" @click="openReusePlanModal">
              <template #icon><CopyOutlined /></template>
              复用研究计划
            </Button>
          </Form.Item>
          <Form.Item v-if="executingResearch">
            <Button danger @click="abortResearch">
              <template #icon><StopOutlined /></template>
              中止
            </Button>
          </Form.Item>
          <Form.Item v-if="canResumeSelectedJob && !executingResearch">
            <Button type="primary" :loading="resumeLoading" @click="resumeResearch">
              <template #icon><PlayCircleOutlined /></template>
              继续执行
            </Button>
          </Form.Item>
        </Form>
        <div v-if="plan" class="project-meta">
          <div class="project-meta-row">
            <span class="project-meta-label">研究标题</span>
            <span class="project-meta-value">{{ selectedProjectTitleDisplay }}</span>
          </div>
          <div class="project-meta-row">
            <span class="project-meta-label">文档集</span>
            <span class="project-meta-value">{{ selectedCollectionLabel }}</span>
          </div>
          <div class="project-meta-row">
            <span class="project-meta-label">研究主题</span>
            <span class="project-meta-value">{{ plan.topic }}</span>
          </div>
        </div>
        <div v-else class="project-meta-hint">请选择已有研究项目，或点击「创建研究项目」新建。</div>
      </Card>

      <Modal
        v-model:open="reusePlanModalVisible"
        title="复用研究计划"
        ok-text="应用到当前项目"
        :confirm-loading="reusePlanSubmitting"
        @ok="submitReusePlan"
      >
        <p class="reuse-plan-hint">
          从下方选择一个<strong>其他</strong>研究项目，将其研究步骤复制到当前项目（会覆盖当前步骤，不修改来源项目）。
        </p>
        <Alert
          v-if="!reusePlanSelectOptions.length"
          type="info"
          show-icon
          message="暂无其他研究项目可复用，请先创建至少两个项目。"
          class="mb-16"
        />
        <Form layout="vertical" class="create-project-form">
          <Form.Item label="来源项目" required>
            <Select
              v-model:value="reuseSourcePlanId"
              placeholder="选择已有项目"
              style="width: 100%"
              :options="reusePlanSelectOptions"
              show-search
              option-filter-prop="label"
              allow-clear
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        v-model:open="projectModalVisible"
        title="创建研究项目"
        ok-text="创建"
        :confirm-loading="creatingProject"
        @ok="submitCreateProject"
      >
        <Form layout="vertical" class="create-project-form">
          <Form.Item label="研究标题" required>
            <Input
              v-model:value="newProjectTitle"
              placeholder="用于列表展示，例如：Q1 财报对比分析"
              @press-enter="submitCreateProject"
            />
          </Form.Item>
          <Form.Item label="文档集" required>
            <Select
              v-model:value="newProjectCollectionId"
              placeholder="选择文档集"
              style="width: 100%"
              :options="selectOptions"
              allow-clear
            />
          </Form.Item>
          <Form.Item label="研究主题" required>
            <Input
              v-model:value="newProjectTopic"
              placeholder="输入研究主题（将用于制定计划与执行）"
              @press-enter="submitCreateProject"
            />
          </Form.Item>
        </Form>
      </Modal>

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
                  <span class="history-topic">{{
                    planDropdownLabel({ title: j.title, topic: j.topic || '' }) || '未命名'
                  }}</span>
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
                      <div
                        v-if="log.prompt_slot || log.prompt_preview"
                        class="log-prompt-preview"
                      >
                        <span class="log-prompt-label">提示词</span>
                        <span v-if="log.prompt_slot" class="log-prompt-slot">{{ log.prompt_slot }}</span>
                        <pre v-if="log.prompt_preview" class="log-prompt-content">{{
                          log.prompt_preview
                        }}</pre>
                      </div>
                      <div v-if="log.tool_name || log.tool_detail" class="log-tool-preview">
                        <span class="log-tool-label">工具</span>
                        <span v-if="log.tool_name" class="log-tool-name">{{ log.tool_name }}</span>
                        <pre v-if="log.tool_detail" class="log-tool-content">{{
                          log.tool_detail
                        }}</pre>
                      </div>
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
                <div v-if="canResumeSelectedJob" class="mb-16">
                  <Space direction="vertical" :size="8" style="width: 100%">
                    <Button type="primary" :loading="resumeLoading" @click="resumeResearch">
                      <template #icon><PlayCircleOutlined /></template>
                      从当前进度继续执行
                    </Button>
                    <span class="resume-hint">将跳过磁盘上已有步骤结果，从中止处继续跑剩余步骤并合并报告</span>
                  </Space>
                </div>
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
                <div class="result-section-head">
                  <span class="result-section-title">研究结果</span>
                  <Space v-if="selectedJobId" wrap class="result-downloads">
                    <a
                      :href="researchDownloadFinalUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="download-link"
                    >
                      <DownloadOutlined />
                      下载最终报告 (.md)
                    </a>
                    <a
                      :href="researchDownloadPackageUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="download-link"
                    >
                      <DownloadOutlined />
                      下载全部输出 (.zip)
                    </a>
                  </Space>
                </div>
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
                  v-if="selectedJobLogs.length"
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
                      <div
                        v-if="log.prompt_slot || log.prompt_preview"
                        class="log-prompt-preview"
                      >
                        <span class="log-prompt-label">提示词</span>
                        <span v-if="log.prompt_slot" class="log-prompt-slot">{{ log.prompt_slot }}</span>
                        <pre v-if="log.prompt_preview" class="log-prompt-content">{{
                          log.prompt_preview
                        }}</pre>
                      </div>
                      <div v-if="log.tool_name || log.tool_detail" class="log-tool-preview">
                        <span class="log-tool-label">工具</span>
                        <span v-if="log.tool_name" class="log-tool-name">{{ log.tool_name }}</span>
                        <pre v-if="log.tool_detail" class="log-tool-content">{{
                          log.tool_detail
                        }}</pre>
                      </div>
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
.project-meta {
  margin-top: 16px;
  padding: 12px 16px;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.06);
}
.project-meta-row {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 14px;
}
.project-meta-row:last-child {
  margin-bottom: 0;
}
.project-meta-label {
  flex-shrink: 0;
  width: 72px;
  color: rgba(0, 0, 0, 0.45);
}
.project-meta-value {
  flex: 1;
  word-break: break-word;
}
.project-meta-hint {
  margin-top: 12px;
  font-size: 13px;
  color: rgba(0, 0, 0, 0.45);
}
.reuse-plan-hint {
  font-size: 13px;
  color: rgba(0, 0, 0, 0.65);
  margin-bottom: 16px;
  line-height: 1.5;
}
.create-project-form {
  margin-top: 8px;
}
.result-section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 16px 0 8px;
}
.result-section-title {
  font-weight: 600;
  font-size: 14px;
  margin: 0;
}
.result-downloads {
  flex-shrink: 0;
}
.download-link {
  font-size: 13px;
  color: #1677ff;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.download-link:hover {
  color: #4096ff;
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
.resume-hint {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
  display: block;
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
.log-prompt-preview,
.log-tool-preview {
  width: 100%;
  margin-top: 6px;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
}
.log-prompt-preview {
  background: rgba(22, 119, 255, 0.06);
  border-left: 3px solid #1677ff;
}
.log-tool-preview {
  background: rgba(82, 196, 26, 0.08);
  border-left: 3px solid #52c41a;
}
.log-prompt-label,
.log-tool-label {
  color: rgba(0, 0, 0, 0.45);
  display: block;
  margin-bottom: 4px;
  font-weight: 600;
}
.log-prompt-slot {
  display: inline-block;
  font-size: 11px;
  color: #0958d9;
  background: rgba(22, 119, 255, 0.12);
  padding: 1px 6px;
  border-radius: 4px;
  margin-bottom: 4px;
}
.log-tool-name {
  display: inline-block;
  font-size: 11px;
  color: #237804;
  background: rgba(82, 196, 26, 0.15);
  padding: 1px 6px;
  border-radius: 4px;
  margin-bottom: 4px;
}
.log-prompt-content,
.log-tool-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
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
