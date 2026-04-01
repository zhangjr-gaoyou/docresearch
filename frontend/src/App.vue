<script setup lang="ts">
import { ref, computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ConfigProvider, Layout, Menu, MenuItem } from 'ant-design-vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { FileTextOutlined, SearchOutlined, MenuFoldOutlined, MenuUnfoldOutlined, FormOutlined, ApartmentOutlined } from '@ant-design/icons-vue'

const route = useRoute()
const selectedKeys = computed(() => [route.path])
const collapsed = ref(false)
const toggleCollapsed = () => { collapsed.value = !collapsed.value }
</script>

<template>
  <ConfigProvider :locale="zhCN">
    <Layout class="app-layout">
      <Layout.Sider v-model:collapsed="collapsed" collapsible theme="dark" width="220">
        <div class="logo">
          <FileTextOutlined class="logo-icon" />
          <span v-show="!collapsed" class="logo-title">文档深度研究服务</span>
        </div>
        <Menu
          :selectedKeys="selectedKeys"
          mode="inline"
          theme="dark"
          :inline-collapsed="collapsed"
          class="app-menu"
        >
          <MenuItem key="/">
            <RouterLink to="/">
              <FileTextOutlined />
              <span>文档集管理</span>
            </RouterLink>
          </MenuItem>
          <MenuItem key="/research">
            <RouterLink to="/research">
              <SearchOutlined />
              <span>文档研究</span>
            </RouterLink>
          </MenuItem>
          <MenuItem key="/knowledge">
            <RouterLink to="/knowledge">
              <ApartmentOutlined />
              <span>知识提取</span>
            </RouterLink>
          </MenuItem>
          <MenuItem key="/prompts">
            <RouterLink to="/prompts">
              <FormOutlined />
              <span>提示词管理</span>
            </RouterLink>
          </MenuItem>
        </Menu>
      </Layout.Sider>
      <Layout>
        <Layout.Header class="app-header">
          <span class="header-trigger" @click="toggleCollapsed">
            <MenuUnfoldOutlined v-if="collapsed" />
            <MenuFoldOutlined v-else />
          </span>
          <span class="header-title">{{
            route.path === '/'
              ? '文档集管理'
              : route.path === '/research'
                ? '文档研究'
                : route.path === '/knowledge'
                  ? '知识提取'
                  : '提示词管理'
          }}</span>
        </Layout.Header>
        <Layout.Content class="app-content">
          <div class="content-inner">
            <RouterView />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  </ConfigProvider>
</template>

<style scoped>
.app-layout {
  min-height: 100vh;
}
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 16px;
  font-weight: 600;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.logo-icon {
  font-size: 24px;
  flex-shrink: 0;
}
.logo-title {
  overflow: hidden;
  white-space: nowrap;
}
.app-menu {
  margin-top: 8px;
}
.app-menu a {
  color: inherit;
  text-decoration: none;
}
.app-header {
  background: #fff;
  padding: 0 24px;
  height: 64px;
  line-height: 64px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  display: flex;
  align-items: center;
  gap: 16px;
}
.header-trigger {
  font-size: 20px;
  cursor: pointer;
  color: rgba(0, 0, 0, 0.65);
  transition: color 0.2s;
}
.header-trigger:hover {
  color: rgba(0, 0, 0, 0.88);
}
.header-title {
  font-size: 18px;
  font-weight: 500;
  color: rgba(0, 0, 0, 0.88);
}
.app-content {
  padding: 24px;
  background: #f0f2f5;
  min-height: calc(100vh - 64px);
}
.content-inner {
  max-width: 1200px;
  margin: 0 auto;
}
</style>
