<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Card, Form, Input, Select, Button, Alert, List, Space, InputNumber, message, Popconfirm, Spin } from 'ant-design-vue'
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
const loading = ref(false)
const uploadLoading = ref(false)
const documentsLoading = ref(false)
const deletingDocId = ref<string | null>(null)
const documents = ref<{ id: string; filename: string; file_type: string }[]>([])
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

async function search() {
  if (!selectedId.value || !query.value.trim()) return
  try {
    error.value = ''
    loading.value = true
    const res = await api.search.search(selectedId.value, query.value.trim(), topK.value)
    searchResults.value = res.results
    message.success(`检索到 ${res.results.length} 条结果`)
  } catch (e) {
    error.value = (e as Error).message
    searchResults.value = []
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

      <Card title="上传文档 (PDF / DOCX)" size="small">
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
          <span v-if="uploadFiles.length" class="file-count">
            已选 {{ uploadFiles.length }} 个文件
          </span>
          <Button
            type="primary"
            :loading="uploadLoading"
            :disabled="!selectedId || !uploadFiles.length"
            @click="upload"
          >
            上传
          </Button>
        </Space>
      </Card>

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
</style>
