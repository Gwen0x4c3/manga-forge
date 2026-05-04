## 1. 产品概述（Overview）

### 1.1 产品名称（暂定）

**MangaForge**

### 1.2 一句话描述

用户导入既有漫画（图片/分集）与世界观资料后，系统自动完成“剧情理解 → 资产化（人物/服装/场景/道具/画风）→ 长期记忆 → 分镜脚本 → 生图 → 漫画排版”，并支持按集数进行 **版本控制（branch/fork/merge）** 的开源 AI 漫画续画系统。

### 1.3 目标用户

- 追更读者：作者更新慢，想生成“同人续集”
- 同人创作者：需要保持角色一致、画风一致的流水线
- 研究者/开发者：多模态 RAG、角色一致性、长篇叙事生成

### 1.4 关键指标（KPI）

- **一致性**：主角脸/发型/服装在连续 3–5 集内不崩坏的比例
- **连贯性**：剧情设定冲突（前后矛盾）发生率
- **可控性**：用户指定“主线/日常/填坑”目标达成率
- **可复用性**：导入一次后，后续生成无需重复上传设定资料

---

## 2. 核心使用流程（User Journey）

### 2.1 初始化（Import & Bootstrap）

1. 创建作品 Project
2. 导入历史漫画资源（图片/分集/zip/文件夹/URL爬取）
3. 导入文本资料（故事简介、人物介绍、世界观设定等）
4. 系统自动：

- OCR & 分镜切分（可选）
- 角色/场景/道具资产发现与归档
- 生成“分集摘要/人物卡/世界观卡”
- 建立长期记忆库（RAG）

### 2.2 续集生成（Generate New Episode）

1. 用户选择从哪一集继续（例如从 55 继续生成 56）
2. 选择策略：主线/日常比例、是否填坑、节奏模板
3. 系统输出：

- 本集大纲（可审阅）
- 分镜脚本（结构化 JSON）
- 每格提示词（含人物、服装、场景、镜头、情绪）

4. 调用生图后端生成单格 → 自动排版成页 → 叠加气泡与文字
5. 用户局部重绘/抽卡/编辑 → 发布为新集

### 2.3 分支管理（Fork/Branch/Merge）

- 从 55 fork 出 “fan-56”
- 后续作者官方 56 更新：导入后生成 diff，对比你的 fan-56 与 official-56
- 选择：保持平行宇宙 or 将官方设定 merge 到你的分支并更新知识库/资产

---

## 3. 需求范围（Scope）

### 3.1 MVP（最小可行版本）必须有

**目标：先跑通“导入 → 记忆 → 分镜脚本 → 生图 → 排版 → 保存”的闭环**

#### A. 项目与数据管理

- Project（作品）管理：创建/删除/导出
- Episode（集）管理：导入/生成/浏览/导出
- Asset（资产）管理：人物/服装/场景/道具/风格
- 存储：本地文件系统 + 元数据 DB（SQLite/Postgres）

#### B. 记忆系统（文本侧）

- 分集摘要自动生成（每集：梗概、关键事件、角色状态变更）
- 人物卡（姓名、性格、口癖、动机、关系）
- 世界观卡（规则、阵营、地点）
- RAG：向量库（Qdrant/Chroma/PGVector）检索用于续写

#### C. 剧情与脚本生成（LLM）

- 支持“主线/日常”节奏控制（至少二选一）
- 支持“埋坑列表/填坑列表”的记忆与调用
- 输出结构化分镜脚本（JSON），包含：
  - panel_id
  - 场景
  - 角色与状态（衣服/情绪/姿态）
  - 镜头语言（远景/近景/俯视/仰视）
  - 对白与旁白
  - 生图提示词（prompt/negative prompt/seed 可选）

#### D. 生图与排版（图像侧）

- 可插拔的 Image Backend 接口（先支持一种：ComfyUI / SD WebUI / 自定义 HTTP）
- 面板生成（单格图）
- 基础排版模板（例如：2x2、3格、4格、跨页可后续）
- 气泡叠加：文字渲染不交给生图模型（程序画泡泡+字体）
- 导出：PNG/JPG/PDF（至少 PNG）

#### E. 生成内容回写

- 新生成集自动进入数据库：脚本、摘要、资产引用、图片文件路径
- 自动更新记忆库：把新集摘要/状态变更写回

---

### 3.2 V1（增强版）建议加入

- 资产自动发现增强：角色聚类、同一人物跨集识别
- 角色一致性策略：参考图/embedding 检索 + IP-Adapter（或相似模块）
- 局部重绘（inpainting）与多次抽卡
- 分支 diff 工具：剧情差异、设定差异、资产差异
- 自动训练 LoRA（“炼丹炉”）：检测到足够样本自动触发训练任务并注册到后端
- 多语言支持（中/日/英）与翻译工作流

### 3.3 明确不做（Out of scope，避免爆炸）

- 完全自动生成“100%像原作者”的商业级替代（会很难且法律风险更高）
- 端到端无人工审阅直接发布（会导致质量不可控）
- 强依赖某一家闭源模型（开源项目应可替换后端）

---

## 4. 功能需求详述（FRD，按模块）

### 4.1 导入与爬取

**FR-IM-01** 导入本地目录/zip，按文件夹或命名规则识别集数  
**FR-IM-02** URL 爬取导入（可选，需要插件化，默认关闭）  
**FR-IM-03** 支持增量导入：导入官方新一集后触发“理解与补充”流程  
**FR-IM-04** 导入时生成标准化元数据：来源、版权提示、hash、页码

### 4.2 漫画理解（Vision → Text）

**FR-VI-01** OCR 提取文字（可选）  
**FR-VI-02** 面板切分（可选）：页→格，存 panel 图片  
**FR-VI-03** 每集自动生成：

- 梗概 summary
- 事件列表 events
- 状态变更 state_changes（谁受伤、谁获得道具、关系变化）
- 新资产发现 new_assets（人物/场景/道具候选）

### 4.3 长期记忆（Memory）

**FR-ME-01** 三层记忆模型：

- Canon rules（硬设定）
- Long summary（历史压缩）
- Recent window（最近 N 集详细）
  **FR-ME-02** 埋坑系统：
- pit_id、描述、出现集、优先级、触发条件、已回收/未回收
  **FR-ME-03** 节奏系统：
- 集级标签：主线/日常/番外/高潮/填坑
- 用户可指定未来 K 集的节奏模板

### 4.4 分镜脚本生成（Script）

**FR-SC-01** 输出结构化 JSON（作为后续生图唯一输入源）  
**FR-SC-02** 对白风格保持：口癖、礼貌程度、情绪强度  
**FR-SC-03** 自动检查一致性：与世界观/状态冲突则重写或报警

### 4.5 资产系统（Assets）

**FR-AS-01** 资产类型：

- Character（人物）
- Outfit（服装，可挂在人物之下）
- Location/Scene（地点/场景）
- Item（道具）
- Style（画风参考图/LoRA/关键词）
  **FR-AS-02** 资产描述词：
- text prompt tags（可多语言）
- reference images（若有）
- embeddings（可选）
  **FR-AS-03** 生成时自动拼 prompt：`Style + Scene + Characters(with outfit/state) + Camera + Mood`

### 4.6 生图后端（Rendering）

**FR-RE-01** Image Backend 抽象接口：

- generate_image(prompt, refs, seed, size, loras, control, …)
- inpaint(mask, …)
  **FR-RE-02** 批量生成面板：按分镜并发、失败重试、缓存  
  **FR-RE-03** 后处理：黑白网点/速度线滤镜（可选）

### 4.7 排版与输出（Layout）

**FR-LA-01** 模板化排版：格子布局 + 留白 + 阅读顺序  
**FR-LA-02** 气泡引擎：自动放置、避免遮挡脸（可简化为规则引擎）  
**FR-LA-03** 导出 PDF/PNG，带版本号与分支名

### 4.8 分支与版本控制（Branching）

**FR-BR-01** Episode 支持 parent 指针（形成有向无环图 DAG）  
**FR-BR-02** 从任意集 fork：复制记忆快照、资产引用、状态  
**FR-BR-03** merge：将官方集导入后，生成 diff 并选择性合并到 fan 分支  
**FR-BR-04** 每次生成写入 commit-like 记录（时间、模型、参数、prompt）

---

## 5. 非功能需求（NFR）

- **可复现性**：同一脚本/同一 seed 能复现图片（尽量）
- **可插拔**：LLM backend / image backend / vector DB 可替换
- **离线优先**：默认本地运行（开源用户友好）
- **任务队列**：生图、训练、OCR 走队列（Celery/RQ/Arq）
- **隐私**：默认不上传用户漫画到第三方（可选云端模式）
- **审计日志**：记录生成参数，便于 debug 和复现

---

## 6. 技术架构建议（实现路线）

### 6.1 推荐分层

- **UI**：Web（Next.js/Vue）或桌面（Tauri/Electron）
- **API**：FastAPI（Python）
- **Worker**：Celery/RQ + Redis
- **DB**：Postgres/SQLite
- **Vector DB**：Qdrant/Chroma
- **Image Backend**：ComfyUI（本地）优先
- **LLM Backend**：可选 OpenAI/Anthropic/本地 Qwen（抽象接口）

### 6.2 核心数据结构（最少要有）

- Project(id, title, language, created_at)
- Episode(id, project_id, number, branch, parent_episode_id, status)
- EpisodeMemory(episode_id, summary, events, state_snapshot_json)
- Pit(id, project_id, description, introduced_episode, priority, resolved_episode)
- Asset(id, project_id, type, name, tags_json, refs, embedding)
- Panel(id, episode_id, index, script_json, image_path)
- GenerationRun(id, episode_id, model_versions, prompts, seeds, params_json)

---

## 7. 风险与注意事项（你开源时必须写清楚）

- **版权与合规**：导入原作用于“训练/续画”存在灰区甚至风险。开源项目建议：
  - 默认仅支持用户本地使用
  - 强调“仅供学习研究，不提供盗版素材”
  - 爬虫模块做成插件并默认关闭
- **画风一致性**：最难点在视觉侧（LoRA/控制/数据清洗），PRD 里应承认质量需要迭代
- **长篇一致性**：需要持续做一致性检查与回写，不能只靠一次 prompt

---

## 8. 里程碑（Milestones）

**M0（1–2 周）**：项目骨架 + Episode/Asset 数据模型 + 导入本地资源  
**M1（2–4 周）**：记忆库（RAG）+ 分镜脚本 JSON 生成（可只输出文本）  
**M2（4–6 周）**：接入 ComfyUI 生成单格 + 简单 2x2 排版导出 PNG  
**M3（6–10 周）**：气泡引擎 + 回写新集摘要 + “从某集继续生成”  
**M4（10+ 周）**：分支 fork + diff + merge + 自动资产发现增强

---

## 9. 开源仓库建议结构（从零起步）

- `apps/web`（UI）
- `apps/api`（FastAPI）
- `workers/`（队列任务）
- `packages/core`（数据模型、pipeline、prompt 组装）
- `packages/backends/llm-*`（各类 LLM 适配器）
- `packages/backends/image-*`（ComfyUI/SDWebUI 适配器）
- `docs/`（PRD、架构、插件协议、免责声明）
- `examples/`（示例数据与 demo pipeline）
