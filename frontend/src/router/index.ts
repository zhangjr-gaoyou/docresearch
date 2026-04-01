import { createRouter, createWebHistory } from 'vue-router'
import CollectionsView from '../views/CollectionsView.vue'
import ResearchView from '../views/ResearchView.vue'
import PromptsView from '../views/PromptsView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'collections',
      component: CollectionsView,
    },
    {
      path: '/research',
      name: 'research',
      component: ResearchView,
    },
    {
      path: '/knowledge',
      name: 'knowledge',
      component: KnowledgeView,
    },
    {
      path: '/prompts',
      name: 'prompts',
      component: PromptsView,
    },
  ],
})

export default router
