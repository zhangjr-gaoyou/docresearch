<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Card, Table, Button, Select, Modal, Input, message, Space, Tag } from 'ant-design-vue'
import { PlusOutlined, EditOutlined, DeleteOutlined, CheckCircleOutlined } from '@ant-design/icons-vue'
import { api } from '@/api/client'

type PromptItem = { id: string; slot_key: string; title: string; content: string; published: boolean; created_at: string; updated_at: string }
const slots = ref<{ slot_key: string; name: string; placeholders: string[] }[]>([])
const prompts = ref<PromptItem[]>([])
const loading = ref(false)
const slotFilter = ref<string | undefined>()
const modalVisible = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const editingId = ref<string | null>(null)
const formSlot = ref('')
const formTitle = ref('')
const formContent = ref('')

const columns = [
  { title: '槽位', dataIndex: 'slot_key', key: 'slot_key' },
  { title: '标题', dataIndex: 'title', key: 'title' },
  { title: '状态', key: 'published', width: 100 },
  { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180 },
  { title: '操作', key: 'actions', width: 220 },
]

async function loadSlots() {
  slots.value = await api.prompts.listSlots()
}

async function loadPrompts() {
  loading.value = true
  try {
    prompts.value = await api.prompts.list(slotFilter.value)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  modalMode.value = 'create'
  editingId.value = null
  formSlot.value = slots.value[0]?.slot_key ?? ''
  formTitle.value = ''
  formContent.value = ''
  modalVisible.value = true
}

function openEdit(p: PromptItem) {
  modalMode.value = 'edit'
  editingId.value = p.id
  formSlot.value = p.slot_key
  formTitle.value = p.title
  formContent.value = p.content
  modalVisible.value = true
}
function onEdit(record: unknown) {
  openEdit(record as PromptItem)
}

async function savePrompt() {
  if (modalMode.value === 'create') {
    if (!formSlot.value || !formTitle.value.trim()) {
      message.error('请选择槽位并填写标题')
      return
    }
    await api.prompts.create(formSlot.value, formTitle.value.trim(), formContent.value)
    message.success('已创建')
  } else if (editingId.value) {
    await api.prompts.update(editingId.value, formTitle.value.trim(), formContent.value)
    message.success('已保存')
  }
  modalVisible.value = false
  loadPrompts()
}

async function doDelete(p: PromptItem) {
  modalVisible.value = false
  await api.prompts.delete(p.id)
  message.success('已删除')
  loadPrompts()
}

async function doPublish(p: PromptItem) {
  await api.prompts.publish(p.id)
  message.success('已上架')
  loadPrompts()
}

function handleDelete(record: unknown) {
  const p = record as PromptItem
  Modal.confirm({
    title: '确认删除',
    content: `确定要删除「${p.title}」吗？`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => doDelete(p),
  })
}
function onPublish(record: unknown) {
  doPublish(record as PromptItem)
}

onMounted(() => {
  loadSlots().then(loadPrompts)
})
</script>

<template>
  <div class="prompts-view">
    <Card title="提示词管理" size="small">
      <div class="toolbar">
        <Space>
          <Select
            v-model:value="slotFilter"
            placeholder="全部槽位"
            allow-clear
            style="width: 200px"
            :options="[{ value: undefined, label: '全部槽位' }, ...slots.map((s) => ({ value: s.slot_key, label: s.name }))]"
            @change="loadPrompts"
          />
          <Button type="primary" @click="openCreate">
            <template #icon><PlusOutlined /></template>
            新增提示词
          </Button>
        </Space>
      </div>
      <Table
        :data-source="prompts"
        :columns="columns"
        :loading="loading"
        row-key="id"
        size="small"
        :pagination="{ pageSize: 20 }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'slot_key'">
            {{ slots.find((s) => s.slot_key === record.slot_key)?.name ?? record.slot_key }}
          </template>
          <template v-else-if="column.key === 'published'">
            <Tag v-if="record.published" color="green">已上架</Tag>
            <Tag v-else color="default">未上架</Tag>
          </template>
          <template v-else-if="column.key === 'actions'">
            <Space>
              <Button type="link" size="small" @click="onEdit(record)">
                <EditOutlined /> 编辑
              </Button>
              <Button
                v-if="!record.published"
                type="link"
                size="small"
                @click="onPublish(record)"
              >
                <CheckCircleOutlined /> 上架
              </Button>
              <Button type="link" danger size="small" @click="handleDelete(record)">
                <DeleteOutlined /> 删除
              </Button>
            </Space>
          </template>
        </template>
      </Table>
    </Card>

    <Modal
      v-model:open="modalVisible"
      :title="modalMode === 'create' ? '新增提示词' : '编辑提示词'"
      width="800px"
      :footer="null"
    >
      <div class="modal-form">
        <div class="form-row">
          <span class="label">槽位：</span>
          <Select
            v-model:value="formSlot"
            :disabled="modalMode === 'edit'"
            style="width: 100%"
            :options="slots.map((s) => ({ value: s.slot_key, label: s.name }))"
          />
        </div>
        <div class="form-row">
          <span class="label">标题：</span>
          <Input v-model:value="formTitle" placeholder="便于识别的名称" />
        </div>
        <div class="form-row">
          <span class="label">内容：</span>
          <Input.TextArea
            v-model:value="formContent"
            :rows="12"
            placeholder="提示词内容，支持 {topic}、{doc_list_str} 等占位符"
          />
        </div>
        <div class="form-actions">
          <Space>
            <Button @click="modalVisible = false">取消</Button>
            <Button type="primary" @click="savePrompt">保存</Button>
          </Space>
        </div>
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.prompts-view {
  padding: 0;
}
.toolbar {
  margin-bottom: 16px;
}
.modal-form .form-row {
  margin-bottom: 16px;
}
.modal-form .label {
  display: inline-block;
  width: 60px;
  flex-shrink: 0;
}
.form-actions {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
</style>
