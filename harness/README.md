# 部门助手 Harness 配置

本目录只保存部门 AI 使用的 overlay、preset 和启动适配，不包含官方 Harness 源码。

- `cordis.yml`：将新会话的默认 Agent preset 设为 `department`；
- `presets/department/`：部门助手模式的源配置；启动时同步到项目运行目录；
- `start.sh`：从兄弟目录 `../../deepseek-harness/` 启动官方 Harness；
- 项目私有配置统一读取 `../.env`。

## 部门助手模式

自定义 preset 的源文件位于 `presets/department/`，启动时同步到 `../runtime-data/dsh-home/.agent-presets/department/`：

- `preset.yml`：显示名称和用途说明；
- `agent.cordis.yml`：部门 persona、文件与 Skills 能力、上下文压缩、用户选择，以及 Python MCP 连接。

部门 MCP 只在该模式中注册。标准、PTC、极简和创造模式保持官方配置，不会看到部门业务工具。新建会话默认使用“部门助手模式”；已有会话继续使用创建时的模式。

部门模式不再挂载 Harness 自带的互联网搜索，避免无效凭据和敏感文档触发不必要的外部请求。后续可安装独立联网搜索插件；内部流程、模板和知识检索继续由部门 MCP 提供。

先启动 Python 服务：

```bash
cd "/Users/liao/Desktop/Department Knowledge Base/department-ai/backend"
./start.sh
```

再启动 Harness：

```bash
cd "/Users/liao/Desktop/Department Knowledge Base/department-ai/harness"
./start.sh
```

日常使用打开 <http://127.0.0.1:3081/department>。管理页面由 Python 提供，AI 助手 iframe 使用 Harness；部门助手模式通过 `http://127.0.0.1:3081/mcp` 调用六个只读业务工具。

当前已验证 Harness 版本见 `HARNESS_VERSION`。升级时先把官方新版本克隆到另一个目录并用 `DEPARTMENT_HARNESS_DIR` 测试，不要覆盖 `department-ai/`。部门 preset 不会被覆盖，但新版公共接口仍需经过兼容性验证。
