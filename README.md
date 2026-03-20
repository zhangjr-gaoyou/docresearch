# 文档深度研究服务

基于 Vue + FastAPI 的文档深度研究服务，支持文档集管理、向量检索、Rerank 排序与深度研究流程。

## 技术栈

- **前端**: Vue 3 + TypeScript + Vite
- **后端**: FastAPI + Python
- **向量库**: 本地 FAISS
- **模型**: 阿里云百炼 - text-embedding-v3（嵌入）、qwen3-rerank（排序）、qwen-plus（研究计划与文档分析）

## 快速开始

### 1. 配置环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY（阿里云百炼 API Key）
```

### 2. 一键启动 / 停止

```bash
# 若 pip install 报架构冲突（Miniconda 混用），先执行：
./setup_venv.sh

# 启动（后端 + 前端）
./start.sh

# 停止
./stop.sh
```

启动后：前端 http://localhost:5173，后端 http://localhost:8000。

### 3. 手动启动（可选）

```bash
# 后端
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（新终端）
cd frontend
npm install
npm run dev
```

前端默认运行在 http://localhost:5173，API 请求会代理到 http://127.0.0.1:8000。

## 功能说明

### 文档集管理

- 创建文档集
- 上传 PDF / DOCX 文档（自动切片、向量化、写入 FAISS）
- 选择文档集进行向量查询，可配置 top_k
- 查询结果经 qwen3-rerank 排序后展示

### 文档研究

- 选择文档集并输入研究主题
- 点击「制定研究计划」生成步骤化计划（计划生成时会注入文档集内文档名称）
- 支持编辑、增加、删除步骤
- 点击「执行研究计划」按文档依次执行，合并结果
- 最终结果以 Markdown 预览展示

### 研究输出目录结构

每次研究任务在 `data/research_output/{job_id}/` 下生成：

```
{job_id}/
├── plan.md           # 研究计划（主题、步骤、时间）
├── final.md          # 合并后的最终报告
└── steps/            # 步骤级中间结果
    ├── {doc_key_1}/  # 按文档分目录（doc_key 为文件 stem）
    │   ├── step_00.md
    │   ├── step_01.md
    │   └── ...
    └── {doc_key_2}/
        ├── step_00.md
        └── ...
```

- `step_{idx:02d}.md`：该文档第 `idx` 步（0-based）的执行结果
- 合并阶段仅使用各文档**最后一步**的结果，生成 `final.md`

### 研究调用时序

1. **计划生成**：`plan_agent` 根据主题 + 文档集内文档名称列表生成研究步骤
2. **执行调度**：`scheduler_agent` 遍历「文档 × 步骤」
   - 对每步：路由 LLM 判断是否需要引用该文档全文
   - 若需要：`read_collection_document_text` 加载文档
   - 否则：不引用全文（仅用 prior 步骤结果）
   - `step_execution_agent` 执行单步，输出写入 `steps/{doc_key}/step_{idx}.md`
3. **合并**：收集各文档最后一步的 Markdown，调用 LLM 合并为 `final.md`

### 工具 API

- `POST /api/v1/tools/documents:read`：读取并返回文档内容
- `POST /api/v1/tools/documents:analyze`：对文档内容进行分析（支持 map-reduce）

## 目录结构

```
research2/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/   # REST 路由
│   │   ├── core/     # 配置
│   │   ├── models/   # 请求/响应模型
│   │   └── services/ # 业务逻辑
│   │       └── research/  # 研究 Agent 模块
│   │           ├── tools.py           # 列文档、读集合文档、读/写步骤结果
│   │           ├── plan_agent.py      # 计划生成
│   │           ├── step_execution_agent.py  # 单步执行
│   │           └── scheduler_agent.py # 文档×步骤调度、路由、合并
│   └── requirements.txt
├── frontend/         # Vue 前端
├── data/             # 上传文件、FAISS 索引、研究输出
└── README.md
```

## 生产化演进

### 稳定性与并发
- 将研究任务改为后台队列（Celery/RQ）+ 任务状态持久化
- 大文档处理增加超时、重试、断点恢复

### 安全与治理
- 鉴权（JWT/API Key）与租户隔离（按用户/空间隔离 collection）
- 上传文件白名单、大小限制、恶意内容扫描

### 可观测性与运维
- 结构化日志、请求链路 ID、模型调用耗时监控
- 关键指标：索引耗时、检索延迟、研究任务成功率

### 质量保障
- 单测：文档解析、检索、重排、计划编排
- 集成测试：模型接口 Mock + API 回归
- 前端 E2E：关键流程自动化测试

## 版本与发布

- **V0.1**（标签 `v0.1`）：首个可运行版本——文档集、向量检索、研究计划与后台任务、提示词管理、任务中止等。

### 推送到 GitHub（`docresearch`）

1. 在 GitHub 上新建空仓库 **docresearch**（不要初始化 README，避免冲突）。
2. 若你的账号不是 `zhangjr`，请改远程地址：

   ```bash
   git remote set-url origin https://github.com/<你的用户名>/docresearch.git
   ```

3. 推送分支与标签：

   ```bash
   git push -u origin main
   git push origin v0.1
   ```

### 仓库忽略内容说明

- `backend/.venv/`、`frontend/node_modules/`、`frontend/dist/`、`.env` 不纳入版本库。
- `data/faiss_index/*`、`data/uploads/*`、`data/research_output/` 为本地运行生成，由 `.gitignore` 排除；首次使用请通过界面上传文档重建索引。
