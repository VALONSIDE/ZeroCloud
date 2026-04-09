# ZeroCloud Alpha_260409

**Author:** Lei Wu  
**License:** GPL-3.0-only  
**Release:** Alpha_260409

ZeroCloud Alpha_260409 是一个可直接开源发布的边缘集群示例项目，包含：

1. `GATE/`：标准化边缘控制中枢（FastAPI + MQTT + Vue3）。
2. `KIT/ESP32-C6-Reference/`：标准化 KIT 参考实现（ESP32-C6，后续 KIT 开发应遵守此规范）。
3. `LICENSE`：GPLv3 完整协议文本。
4. `AUTHORS` / `VERSION`：版本与作者元数据。

---

## 项目结构

```text
ZeroCloud_Alpha_260409/
├── AUTHORS
├── LICENSE
├── README.md
├── VERSION
├── GATE/
└── KIT/
    └── ESP32-C6-Reference/
        ├── README.md
        ├── platformio.ini
        └── src/main.cpp
```

---

## 快速开始

### 1) 启动 GATE

```bash
cd GATE
cp .env.example .env
./scripts/start-gate.sh
```

或你习惯的方式：

```bash
cd GATE/backend
export PYTHONPATH="$PYTHONPATH:."
python3 -m app.main
```

### 2) 打开控制台

- 若 `GATE/frontend/dist` 已存在（本版本已内置）：直接访问 `http://<GATE_IP>:8080`
- 若你做前端开发：`cd GATE && ./scripts/start-console.sh`

### 3) 上电 KIT 并收编

- KIT 未收编时会发布 `POOL_ZC/PENDING/{uid}`；
- 控制台待收编列表会出现该 UID；
- 点击 ADOPT 后，GATE 下发 `POOL_ZC/PROVISION/{uid}`；
- KIT 保存目标 `pool_id/gate_id/kit_id` 并重启进入正式链路。

---

## 标准化约束（本版本）

1. 一个 GATE 只绑定一个 POOL（首次组网一次性绑定）。
2. KIT ID 命名规范：`KIT_[A-Z0-9]{1,5}`。
3. 同 UID 新请求会自动合并到旧 KIT 记录并更新 SKILL 表。
4. EVENT 支持表单模式与代码模式，SKILL 不存在会报错。
5. 支持一键重置脚本：`GATE/scripts/reset-gate.sh`。

---

## 文档入口

- 根目录总文档：`../ZeroCloud_Alpha_260409_Project_Manual.md`
- GATE 文档：`GATE/README.md`
- KIT 文档：`KIT/ESP32-C6-Reference/README.md`

---

## 开源声明

本项目采用 GPLv3 协议发布。你可以修改、分发、二次开发，但必须遵守 GPLv3 条款，并保留版权与许可信息。
