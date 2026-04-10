# ZeroCloud GATE (MAGI v3.2 / Alpha_260410)

这是按你的 POOL-GATE-KIT 文档与 ESP32-C6 协议升级后的 **Python-first** 版本：

- 不依赖 Docker，直接 Python 启动，兼容 x86-64 与 ARM64（Radxa A7Z）。
- 支持 GATE 新配置时发现周边 POOL、加入已有 POOL、或新建 POOL。
- 支持 POOL/GATE/KIT 个性化命名，并同步到运行状态与管理表。
- 支持离线 KIT 强制删除。
- EVENT 管理支持表单模式 + 代码模式 + 内置模板，SKILL 不存在会直接报错。

---

## 1. 目录结构

```text
GATE/
├── backend/
│   ├── app/
│   │   ├── api.py
│   │   ├── config.py
│   │   ├── engine.py
│   │   ├── event_templates.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── mqtt_gateway.py
│   │   ├── schemas.py
│   │   ├── state.py
│   │   └── storage.py
│   ├── data/
│   ├── tests/
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.js
├── scripts/
│   ├── start-gate.sh
│   └── start-console.sh
└── .env.example
```

---

## 2. 协议与发现机制

### 2.1 KIT 生命周期（兼容原文档）

- 发现新设备：`[POOL]/PENDING/{uid}`
- 收编下发：`[POOL]/PROVISION/{uid}`
- 心跳与自描述：`[POOL]/[GATE]/[KIT]/STATUS`
- 技能上报：`[POOL]/[GATE]/[KIT]/[SKILL]`
- 控制下发：`[POOL]/[GATE]/[KIT]/[SKILL]/[ACTION]`

### 2.2 POOL/GATE 发现广播

为支持 GATE 首次配置时自动发现周边池，新增广播：

`[POOL]/[GATE]/SYS_GATE/PROFILE/ANNOUNCE`

载荷示例：

```json
{
  "kind": "GATE_PROFILE",
  "pool_id": "POOL_ZC",
  "pool_name": "ZeroCloud Main Pool",
  "gate_id": "GATE_01",
  "gate_name": "MAGI-01"
}
```

---

## 3. 快速启动（无 Docker）

### 3.1 后端

```bash
cd GATE
cp .env.example .env
./scripts/start-gate.sh
```

后端默认：`http://0.0.0.0:8080`

> 已包含预编译好的 `frontend/dist`，仅启动后端也可直接访问控制台（由 FastAPI 静态托管）。

> 若你希望手动方式，也可使用：
>
> ```bash
> cd GATE/backend
> export PYTHONPATH="$PYTHONPATH:."
> python3 -m app.main
> ```

### 3.2 前端

另开终端：

```bash
cd GATE
./scripts/start-console.sh
```

前端默认：`http://0.0.0.0:5173`

> 前端开发时走 Vite 代理；生产可执行 `npm run build` 后由后端静态托管 `frontend/dist`。

### 3.3 一键注销/初始化本 GATE

```bash
cd GATE
./scripts/reset-gate.sh
```

该脚本会清理本机 GATE 的持久化配置（profile/kits/events），并把 `ZC_PROFILE_CONFIGURED` 置回 `0`。

---

## 4. 配置项（.env）

关键变量：

- `ZC_POOL_ID` / `ZC_POOL_NAME`
- `ZC_GATE_ID` / `ZC_GATE_NAME`
- `MQTT_HOST` / `MQTT_PORT`
- `MAGI_FRAME_HZ`（默认 60）
- `OFFLINE_TIMEOUT_SEC`（默认 10 秒）
- `POOL_ANNOUNCE_INTERVAL_SEC`（默认 5 秒）

建议使用带双引号的写法（尤其值里可能有空格时）：

```bash
ZC_POOL_ID="POOL_ZC"
ZC_POOL_NAME="ZeroCloud_Main_Pool"
ZC_GATE_ID="GATE_01"
ZC_GATE_NAME="MAGI-01"
```

---

## 5. 主要 API

### 5.1 组网与命名

- `GET /api/v1/profile`
- `PUT /api/v1/profile`（仅更新 POOL/GATE 显示名称）
- `GET /api/v1/pools/discovered`（周边 POOL 列表）
- `POST /api/v1/setup/join`（首次启动时加入已存在 POOL）
- `POST /api/v1/setup/create`（首次启动时创建新 POOL）

> 一个 GATE 仅允许绑定一个 POOL。首次组网完成后，setup 接口会被锁定；后续仅可改名称。

### 5.2 KIT 管理

- `GET /api/v1/pending`
- `POST /api/v1/pending/{uid}/adopt`（支持 `pending_pool_id` + `kit_id` + `kit_name`）
- `GET /api/v1/kits`
- `PATCH /api/v1/kits/{kit_id}/name`
- `DELETE /api/v1/kits/{kit_id}?force=true`（离线强删）
- `POST /api/v1/kits/{kit_id}/display`
- `POST /api/v1/kits/{kit_id}/reset`

> 若新 KIT 的 UID 与旧设备一致，系统会自动合并为旧 KIT 记录并更新 SKILL 表（视为设备重上线）。

### 5.3 EVENT 管理

- `GET /api/v1/events`
- `GET /api/v1/events/skills`（完整 SKILL 列表）
- `GET /api/v1/events/templates`
- `GET /api/v1/events/code-framework`
- `POST /api/v1/events`
- `PUT /api/v1/events/{event_id}`
- `POST /api/v1/events/{event_id}/enabled`
- `DELETE /api/v1/events/{event_id}`

### 5.4 状态流

- `GET /api/v1/state`
- `GET /api/v1/stream`（SSE）

---

## 6. EVENT 双模式说明

### 表单模式（mode=form）

- 通过 Source KIT/SKILL + Operator + Threshold + Target KIT/SKILL 配置。
- Source/Target SKILL 必须来自已发现技能列表，否则接口直接报错。

### 代码模式（mode=code）

- 代码需定义：`def evaluate(ctx): ...`
- 可返回 `bool` 或 `{trigger: bool, actions: [...]}`。
- `ctx["get"](kit_id, skill_id)` 查询不存在 SKILL 会直接抛错，EVENT 状态转为 `ERROR`。
- 可使用 `required_skills` 声明依赖，后台持续校验。

---

## 7. 持久化

- `backend/data/profile.json`：POOL/GATE 配置
- `backend/data/kits.json`：KIT 命名映射
- `backend/data/events.json`：EVENT 规则

---

## 8. 测试

```bash
cd GATE/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
