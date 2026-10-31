# EDP 全量导航 HTML 原型设计

## 目标

基于现有 EDP 系统设计、前端设计和开发计划，生成一个单文件、高保真、可点击的 HTML 原型，用于展示 AEOS 第一阶段 EDP 数据与证据平台的全量导航、核心工作流和多租户运营能力。

## 范围

覆盖四类路由与页面：

- CASES：案例列表、案例全景与证据链
- ADMIN：总览、对象注册、事件、证据、决策、行动、质量、审计、适配器、系统、工具、记忆、Trace、演练
- TENANTS：租户列表、开通向导、租户详情、成员、配额、用量
- ERROR：登录、403、404、500 及租户暂停/注销状态提示

原型不实现真实后端、鉴权、数据库或 API 请求；使用确定性 mock 数据模拟状态与交互。

## 视觉方向

采用现代 SaaS 风格，同时保留 EDP 文档定义的企业级信息架构：

- 浅色内容区、深色或深色偏蓝的紧凑导航壳层
- 低装饰、低渐变；颜色主要表达状态、风险和动作
- 主色蓝色，成功/警告/错误/信息状态与设计文档保持一致
- 8px 间距体系、8/12px 圆角、细边框、轻阴影
- 中文优先，关键技术标识、ID、checksum 使用等宽字体
- 桌面端优先，同时在窄屏下保持导航和表格可用

## 信息架构与交互

### 全局壳层

- 顶栏：品牌、面包屑、全局搜索、当前租户徽标、刷新、用户菜单
- 侧栏：CASES、ADMIN、TENANTS 分组；当前页面高亮；支持折叠
- 租户切换：切换面板更新当前上下文并刷新页面 mock 数据
- 全局搜索：按对象、事件、证据、决策、行动分类返回结果并跳转
- 通知：以轻量 toast/banner 呈现保存成功、限流、权限拒绝等状态

### 列表页通用模式

- 页头标题、说明、主操作
- 搜索框、状态/风险/来源等 filter pill
- Filter 与 Display options 分离
- 表格列显示控制、排序、行点击详情抽屉
- 空态、加载态和错误态均提供可见反馈

### 详情与闭环

- 右侧抽屉或内容页展示多 Tab 详情
- 案例页以横向链路表达：源事件 → 能力结果 → Decision Case → Decision Record → Action → Verified Event
- 节点可点击聚焦；证据节点显示 checksum 校验状态
- Action 页面展示 9 态状态机；Human-Only 操作显示禁用态和原因

### 质量与运维

- 总览显示覆盖率、Outbox、同步量、校验失败、HA 和备份卡片
- 质量页采用健康徽标 → Incident 列表 → Incident 详情三级结构
- 系统页展示 PostgreSQL primary/replica、复制延迟、Worker、备份恢复
- 演练页展示 HA 切换、PITR、租户级恢复的记录与结果

### 租户运营

- 租户列表展示 plan、生命周期状态、最近用量和健康度
- 开通向导模拟四步：基本信息、管理员、配额、确认
- 详情页支持暂停、恢复、注销等 mock 操作
- 配额页展示六维配额与 80%/100% 水位提示
- 用量页展示 API 调用、事件、存储、限流次数趋势

## Mock 数据

使用与现有文档一致的实体和状态：

- 租户：ACME Manufacturing、Northstar Components、内部演示租户
- 对象：订单、客户、物料、库存、供应商
- 风险：P0-P3；能力风险：L0-L3
- Action：PROPOSED、ASSIGNED、ACCEPTED、APPROVED、EXECUTING、COMPLETED、VERIFIED、CANCELLED、REJECTED
- Decision：OPEN、DECIDED、CANCELLED
- 租户：PROVISIONING、ACTIVE、SUSPENDED、CANCELLED
- 数据源：ERP、MES、PLM；适配器模式：Mock/Real

## 技术形式

- 单个自包含 HTML 文件
- 原生 HTML、CSS、JavaScript，不引入未经项目确认的依赖
- 页面通过客户端路由或导航状态切换
- 交互至少包括：侧栏导航、搜索、筛选 pill、表格行详情、Tab、抽屉、Modal、租户切换、状态操作、证据校验、Action 状态转移、配额编辑 mock
- 不添加代码注释

## 网上案例借鉴

- DataHub / OpenMetadata：资产搜索、facet 筛选、详情与血缘聚焦
- Grafana：健康卡、面板式监控、告警生命周期
- Linear：filter 与 display options 分离、紧凑列表、状态编码
- Vercel Geist：低装饰、颜色服务于状态、清晰的空/错态
- Notion：inline filter token 与轻量状态反馈

## 验收标准

1. 打开 HTML 后无需构建即可浏览。
2. 所有主要导航分组均可进入，页面标题和内容随路由变化。
3. 案例闭环、证据链、质量告警、租户切换、Action 状态转移等核心演示可点击完成。
4. 页面视觉统一，符合现代 SaaS 与 EDP 设计文档 token。
5. 不依赖真实后端或网络资源也能运行。
