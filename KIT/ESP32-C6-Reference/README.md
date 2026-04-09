# ZeroCloud KIT Reference (ESP32-C6)

> SPDX-License-Identifier: GPL-3.0-only  
> Version: Alpha_260409  
> Author: Lei Wu

本目录是 ZeroCloud 标准 KIT 参考实现，后续 KIT 开发应遵循该协议规范。

---

## 1. 目标

该参考实现用于提供一个“可运行 + 可扩展 + 可复用”的 KIT 基线，覆盖以下流程：

1. 未收编阶段：发布 `POOL_ZC/PENDING/{uid}`
2. 收编阶段：接收 `POOL_ZC/PROVISION/{uid}`
3. 正式上线：发布 `{POOL}/{GATE}/{KIT}/STATUS`
4. 周期上报：`SKILL_TEMP` / `SKILL_HUM`
5. 控制执行：`SKILL_DISPLAY/SET`、`SYS/RESET`
6. 本地恢复：长按按键清理配置

---

## 2. 配置说明

编辑 `src/main.cpp`：

- `WIFI_SSID`
- `WIFI_PASS`
- `MQTT_BROKER`

这三个参数必须按你的现场网络修改。

---

## 3. 编译与烧录

```bash
cd KIT/ESP32-C6-Reference
pio run
pio run -t upload
pio device monitor
```

---

## 4. 开发规范（必须遵守）

1. SKILL 命名统一大写前缀 `SKILL_`。
2. 未收编引导通道保持 `POOL_ZC/PENDING` 与 `POOL_ZC/PROVISION`。
3. STATUS 载荷必须包含 `status` 与 `skills`，建议包含 `uid`。
4. 控制路径必须遵循 `{POOL}/{GATE}/{KIT}/{SKILL}/{ACTION}`。
5. 保留本地恢复能力（物理按键或等价机制）。

---

## 5. 与 GATE 的兼容要点

Alpha_260409 的 GATE 已支持：

- pending 按 `pending_pool_id` 收编；
- UID 重合并逻辑（视为旧 KIT 重上线）；
- SKILL 严格校验；
- EVENT 表单/代码双模式。

因此，后续 KIT 只要遵守本参考协议，即可接入现有 GATE。
