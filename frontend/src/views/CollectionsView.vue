<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Card, Form, Input, Select, Button, Alert, List, Space, InputNumber, message, Popconfirm, Spin, Row, Col } from 'ant-design-vue'
import { PlusOutlined, UploadOutlined, SearchOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import { api } from '@/api/client'

const fileInput = ref<HTMLInputElement>()

const collections = ref<{ id: string; name: string }[]>([])
const selectedId = ref<string>()
const newName = ref('')
const uploadFiles = ref<File[]>([])
const query = ref('')
const topK = ref(10)
const searchResults = ref<{ content: string; score: number; document_id: string }[]>([])
const searchLlmSummary = ref('')
const loading = ref(false)
const uploadLoading = ref(false)
const crawlLoading = ref(false)
const documentsLoading = ref(false)
const deletingDocId = ref<string | null>(null)
const documents = ref<{ id: string; filename: string; file_type: string }[]>([])
const sourceUrl = ref('')
const error = ref('')

async function loadCollections() {
  try {
    collections.value = await api.collections.list()
    const first = collections.value[0]
    if (first && !selectedId.value) selectedId.value = first.id
  } catch (e) {
    error.value = (e as Error).message
  }
}

async function createCollection() {
  if (!newName.value.trim()) return
  try {
    error.value = ''
    const c = await api.collections.create(newName.value.trim())
    collections.value.push(c)
    selectedId.value = c.id
    newName.value = ''
    message.success('文档集创建成功')
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error)?.message ?? '操作失败')
  }
}

async function upload() {
  if (!selectedId.value || !uploadFiles.value.length) return
  try {
    error.value = ''
    uploadLoading.value = true
    await api.collections.upload(selectedId.value, uploadFiles.value)
    uploadFiles.value = []
    await loadDocuments()
    message.success('文档上传成功')
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error)?.message ?? '操作失败')
  } finally {
    uploadLoading.value = false
  }
}

function isValidHttpUrl(value: string): boolean {
  try {
    const u = new URL(value)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch (_) {
    return false
  }
}

async function crawlFromUrl() {
  if (!selectedId.value || !sourceUrl.value.trim()) return
  const url = sourceUrl.value.trim()
  if (!isValidHttpUrl(url)) {
    message.error('请输入有效的网页地址（http/https）')
    return
  }
  try {
    error.value = ''
    crawlLoading.value = true
    await api.collections.crawlDocument(selectedId.value, url)
    sourceUrl.value = ''
    await loadDocuments()
    message.success('网页抓取并入库成功')
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error)?.message ?? '抓取失败')
  } finally {
    crawlLoading.value = false
  }
}

async function search() {
  if (!selectedId.value || !query.value.trim()) return
  try {
    error.value = ''
    loading.value = true
    const res = await api.search.search(selectedId.value, query.value.trim(), topK.value)
    searchResults.value = res.results
    searchLlmSummary.value = (res.llm_summary || '').trim()
    message.success(`检索到 ${res.results.length} 条结果`)
  } catch (e) {
    error.value = (e as Error).message
    searchResults.value = []
    searchLlmSummary.value = ''
    message.error((e as Error)?.message ?? '操作失败')
  } finally {
    loading.value = false
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files) uploadFiles.value = Array.from(input.files)
}

const collectionOptions = computed(() =>
  collections.value.map((c) => ({ value: c.id, label: c.name }))
)

async function loadDocuments() {
  if (!selectedId.value) {
    documents.value = []
    return
  }
  try {
    documentsLoading.value = true
    documents.value = await api.collections.listDocuments(selectedId.value)
  } catch (e) {
    documents.value = []
    error.value = (e as Error).message
  } finally {
    documentsLoading.value = false
  }
}

async function deleteDocument(docId: string) {
  if (!selectedId.value) return
  try {
    error.value = ''
    deletingDocId.value = docId
    await api.collections.deleteDocument(selectedId.value, docId)
    await loadDocuments()
    message.success('已从文档集与向量库中删除')
  } catch (e) {
    error.value = (e as Error).message
    message.error((e as Error)?.message ?? '删除失败')
  } finally {
    deletingDocId.value = null
  }
}

watch(selectedId, () => {
  loadDocuments()
})

onMounted(async () => {
  await loadCollections()
  await loadDocuments()
})
</script>

<template>
  <div class="collections-view">
    <Alert v-if="error" type="error" :message="error" show-icon closable class="mb-24" />

    <Space direction="vertical" :size="24" style="width: 100%">
      <Card title="创建文档集" size="small">
        <Form layout="inline" :label-col="{ span: 0 }">
          <Form.Item>
            <Input
              v-model:value="newName"
              placeholder="文档集名称"
              style="width: 240px"
              @press-enter="createCollection"
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" @click="createCollection">
            <template #icon><PlusOutlined /></template>
              创建
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="选择文档集" size="small">
        <Select
          v-model:value="selectedId"
          placeholder="请选择文档集"
          style="width: 280px"
          :options="collectionOptions"
          allow-clear
        />
      </Card>

      <Card
        v-if="selectedId"
        title="当前文档集内的文档"
        size="small"
      >
        <Spin :spinning="documentsLoading">
          <List
            v-if="documents.length"
            :data-source="documents"
            size="small"
            bordered
            class="doc-list"
          >
            <template #renderItem="{ item }">
              <List.Item class="doc-list-item">
                <span class="doc-name" :title="item.filename">{{ item.filename }}</span>
                <span class="doc-meta">{{ item.file_type }}</span>
                <Popconfirm
                  title="确定删除该文档？将从文档集与向量库中移除。"
                  ok-text="删除"
                  cancel-text="取消"
                  @confirm="deleteDocument(item.id)"
                >
                  <Button
                    type="text"
                    danger
                    size="small"
                    :loading="deletingDocId === item.id"
                  >
                    <template #icon><DeleteOutlined /></template>
                  </Button>
                </Popconfirm>
              </List.Item>
            </template>
          </List>
          <div v-else-if="!documentsLoading" class="doc-list-empty">暂无文档，请上传</div>
        </Spin>
      </Card>

      <Row :gutter="[16, 16]">
        <Col :xs="24" :md="12">
          <Card title="上传文档 (PDF / DOCX / MD)" size="small" class="full-height-card">
            <Space direction="vertical" style="width: 100%">
              <Space>
                <input
                  ref="fileInput"
                  type="file"
                  multiple
                  accept=".pdf,.docx,.md"
                  @change="onFileChange"
                  style="display: none"
                />
                <Button
                  :disabled="!selectedId"
                  @click="fileInput?.click()"
                >
                  <template #icon><UploadOutlined /></template>
                  选择文件
                </Button>
                <Button
                  type="primary"
                  :loading="uploadLoading"
                  :disabled="!selectedId || !uploadFiles.length"
                  @click="upload"
                >
                  上传
                </Button>
              </Space>
              <span v-if="uploadFiles.length" class="file-count">
                已选 {{ uploadFiles.length }} 个文件
              </span>
              <span v-else class="file-count">支持 .pdf / .docx / .md</span>
            </Space>
          </Card>
        </Col>
        <Col :xs="24" :md="12">
          <Card title="增加网页源" size="small" class="full-height-card">
            <Space direction="vertical" style="width: 100%">
              <Input
                v-model:value="sourceUrl"
                :disabled="!selectedId"
                placeholder="输入网页地址，如 https://example.com/article"
                @press-enter="crawlFromUrl"
              />
              <Space>
                <Button
                  type="primary"
                  :loading="crawlLoading"
                  :disabled="!selectedId || !sourceUrl.trim()"
                  @click="crawlFromUrl"
                >
                  爬取
                </Button>
                <span class="file-count">将提取正文并保存为 Markdown 文档</span>
              </Space>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card title="向量查询" size="small">
        <Form layout="inline" :label-col="{ span: 0 }" class="search-form">
          <Form.Item>
            <Input
              v-model:value="query"
              placeholder="输入查询文本"
              style="width: 320px"
              @press-enter="search"
            />
          </Form.Item>
          <Form.Item label="Top K">
            <InputNumber v-model:value="topK" :min="1" :max="100" style="width: 80px" />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              :loading="loading"
              :disabled="!selectedId || !query.trim()"
              @click="search"
            >
              <template #icon><SearchOutlined /></template>
              查询
            </Button>
          </Form.Item>
        </Form>
        <div v-if="searchLlmSummary && searchResults.length" class="search-llm-summary">
          <div class="search-llm-summary-title">大模型总结（基于下列检索片段）</div>
          <div class="search-llm-summary-body">{{ searchLlmSummary }}</div>
        </div>
        <List
          v-if="searchResults.length"
          :data-source="searchResults"
          class="result-list"
          bordered
        >
          <template #header>
            <div class="result-header">Rerank 排序结果</div>
          </template>
          <template #renderItem="{ item, index }">
            <List.Item>
              <List.Item.Meta>
                <template #title>
                  <Space>
                    <span class="result-score">相关度: {{ item.score.toFixed(4) }}</span>
                  </Space>
                </template>
                <template #description>
                  <div class="result-content">{{ item.content }}</div>
                </template>
              </List.Item.Meta>
            </List.Item>
          </template>
        </List>
      </Card>
    </Space>
  </div>
</template>

<style scoped>
.collections-view {
  padding: 0;
}
.mb-24 {
  margin-bottom: 24px;
}
.file-count {
  color: rgba(0, 0, 0, 0.45);
  font-size: 14px;
}
.search-form :deep(.ant-form-item) {
  margin-bottom: 0;
}
.result-list {
  margin-top: 16px;
}
.search-llm-summary {
  margin-top: 16px;
  padding: 12px 14px;
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  border-radius: 8px;
}
.search-llm-summary-title {
  font-weight: 500;
  font-size: 13px;
  color: rgba(0, 0, 0, 0.75);
  margin-bottom: 8px;
}
.search-llm-summary-body {
  font-size: 14px;
  line-height: 1.65;
  color: rgba(0, 0, 0, 0.88);
  white-space: pre-wrap;
}
.result-header {
  font-weight: 500;
}
.result-score {
  font-size: 13px;
  color: #1677ff;
}
.result-content {
  font-size: 14px;
  line-height: 1.6;
  color: rgba(0, 0, 0, 0.88);
}
.doc-list {
  max-height: 320px;
  overflow-y: auto;
}
.doc-list-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.doc-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-meta {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
  flex-shrink: 0;
}
.doc-list-empty {
  font-size: 13px;
  color: rgba(0, 0, 0, 0.45);
  padding: 8px 0;
}
.full-height-card {
  height: 100%;
}
</style>
