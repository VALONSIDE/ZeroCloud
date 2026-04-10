<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

const snapshot = ref({
  revision: 0,
  profile: {
    pool_id: "POOL_ZC",
    pool_name: "ZeroCloud_Main_Pool",
    gate_id: "GATE_01",
    gate_name: "MAGI-01",
    configured: false
  },
  metrics: {
    frame_tps: 0,
    kits_total: 0,
    kits_online: 0,
    pending_total: 0,
    events_total: 0,
    events_locked: 0,
    events_error: 0,
    events_dead: 0,
    discovered_pools_total: 0,
    mqtt_connected: false
  },
  runtime_errors: {},
  discovered_pools: [],
  pending: [],
  kits: [],
  skills: { grouped: [], flat: [] },
  events: []
});

const notice = ref("");
const errorText = ref("");
const streamConnected = ref(false);
const namesDirty = ref(false);

const activeTab = ref("setup");
const eventEditorTab = ref("form");
const uiTheme = ref(localStorage.getItem("zc_console_theme") || "blue");

const busy = reactive({
  loading: false,
  save_names: false,
  setup_join: false,
  setup_create: false,
  adopt: "",
  rename_kit: "",
  delete_kit: "",
  display_send: false,
  reset_kit: "",
  save_form_event: false,
  save_code_event: false,
  test_code: false,
  toggle_event: "",
  delete_event: "",
  gate_reset_code: false,
  gate_reset_confirm: false
});

const namesForm = reactive({
  pool_name: "",
  gate_name: ""
});

const setupJoinForm = reactive({
  pool_code: "",
  pool_name: ""
});

const setupCreateForm = reactive({
  pool_code: "",
  pool_name: ""
});
const setupStep = ref(1);
const setupMode = ref("join");
const setupGateCode = ref("");
const setupGateName = ref("");
const setupGateCodeInitialized = ref(false);

const pendingInput = reactive({});
const kitNameInput = reactive({});

const displayForm = reactive({
  kit_id: "",
  skill_id: "",
  action: "SET"
});

const formEventEditor = reactive({
  event_id: "",
  name: "",
  enabled: true,
  cooldown_ms: 1500,
  source_kit_id: "",
  source_skill: "",
  operator: ">",
  threshold: 30,
  target_kit_id: "",
  target_skill: "",
  action: "SET"
});

const codeEventEditor = reactive({
  event_id: "",
  name: "",
  enabled: true,
  cooldown_ms: 1500,
  code: "",
  required_keys: [],
  fallback_enabled: false,
  target_kit_id: "",
  target_skill: "",
  action: "SET"
});

const directActionPayload = reactive({});
const directActionPayloadRaw = ref("{}");
const formActionPayload = reactive({});
const formActionPayloadRaw = ref("{}");
const codeActionPayload = reactive({});
const codeActionPayloadRaw = ref("{}");

const gateReset = reactive({
  challenge_code: "",
  input_code: ""
});

const eventTemplates = ref([]);
const codeFramework = ref("");
const DEFAULT_CODE_SKELETON = `def evaluate(ctx):
    # 读取输入技能值:
    # value = ctx["get"]("KIT_001", "SKILL_TEMP", default=None)
    # 返回结构:
    # {"trigger": True, "actions": [{"target_kit_id":"KIT_002","target_skill":"SKILL_DISPLAY","action":"SET","payload":{"msg":"HELLO"}}]}
    return {"trigger": False}
`;

const noticeFeed = ref([]);
let noticeSeq = 1;
const runtimeErrorCache = new Map();

const codeSkillTool = reactive({
  kit_id: "",
  skill_id: ""
});

const lifecycleClasses = {
  NEW: "state-new",
  WORKING: "state-working",
  DYING: "state-dying",
  IDLE: "state-idle"
};

const eventClasses = {
  DEAD: "event-dead",
  LOCKED: "event-locked",
  WORKING: "event-working",
  ERROR: "event-error",
  IDLE: "event-idle"
};

let eventSource = null;
let pollTimer = null;
const ID3_PATTERN = /^[A-Z0-9]{3}$/;

const isConfigured = computed(() => Boolean(snapshot.value.profile?.configured));

const visibleTabs = computed(() => {
  const base = [];
  if (!isConfigured.value) {
    base.push({ id: "setup", label: "首次组网" });
  }
  if (isConfigured.value) {
    base.push({ id: "config", label: "配置页面" });
  }
  base.push({ id: "kits", label: "设备管理" });
  base.push({ id: "events", label: "EVENT 管理" });
  base.push({ id: "skills", label: "SKILL 总览" });
  return base;
});

const kits = computed(() => snapshot.value.kits ?? []);
const pendingKits = computed(() => snapshot.value.pending ?? []);
const events = computed(() => snapshot.value.events ?? []);
const metrics = computed(() => snapshot.value.metrics ?? {});
const discoveredPools = computed(() => snapshot.value.discovered_pools ?? []);
const skillGrouped = computed(() => snapshot.value.skills?.grouped ?? []);
const skillFlat = computed(() => snapshot.value.skills?.flat ?? []);
const inputSkillFlat = computed(() =>
  skillFlat.value.filter((item) => item.io_type !== "output")
);
const onlineKits = computed(() => kits.value.filter((item) => item.status === "ONLINE"));

const skillsMetaByKit = computed(() => {
  const map = {};
  for (const group of skillGrouped.value) {
    map[group.kit_id] = group.skills ?? [];
  }
  return map;
});

function normalizeCodeInput(text) {
  return String(text || "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, 3);
}

function appendNoticeFeed(level, message) {
  const text = String(message || "").trim();
  if (!text) return;
  noticeFeed.value.unshift({
    id: noticeSeq++,
    level,
    message: text,
    at: new Date().toISOString()
  });
  if (noticeFeed.value.length > 80) {
    noticeFeed.value = noticeFeed.value.slice(0, 80);
  }
}

function clearNoticeFeed() {
  noticeFeed.value = [];
  runtimeErrorCache.clear();
}

watch(notice, (value) => {
  if (value?.trim()) appendNoticeFeed("notice", value);
});

watch(errorText, (value) => {
  if (value?.trim()) appendNoticeFeed("error", value);
});

watch(
  () => setupJoinForm.pool_code,
  (value) => {
    const normalized = normalizeCodeInput(value);
    if (normalized !== value) setupJoinForm.pool_code = normalized;
  }
);

watch(
  () => setupCreateForm.pool_code,
  (value) => {
    const normalized = normalizeCodeInput(value);
    if (normalized !== value) setupCreateForm.pool_code = normalized;
  }
);

watch(setupGateCode, (value) => {
  const normalized = normalizeCodeInput(value);
  if (normalized !== value) setupGateCode.value = normalized;
});

watch(
  () => snapshot.value.runtime_errors,
  (errors) => {
    const entries = Object.entries(errors || {});
    for (const [key, message] of entries) {
      const text = String(message || "").trim();
      if (!text) continue;
      if (runtimeErrorCache.get(key) === text) continue;
      runtimeErrorCache.set(key, text);
      appendNoticeFeed("error", `${key}: ${text}`);
    }
  },
  { deep: true }
);

function lifecycleClass(state) {
  return lifecycleClasses[state] ?? lifecycleClasses.IDLE;
}

function eventClass(state) {
  return eventClasses[state] ?? eventClasses.IDLE;
}

function inputSkillOptions(kitId) {
  if (!kitId) return [];
  return (skillsMetaByKit.value[kitId] ?? [])
    .filter((item) => item.io_type !== "output")
    .map((item) => item.skill_id);
}

function outputSkillOptions(kitId) {
  if (!kitId) return [];
  return (skillsMetaByKit.value[kitId] ?? [])
    .filter((item) => item.io_type === "output")
    .map((item) => item.skill_id);
}

function outputSkillActions(kitId, skillId) {
  if (!kitId || !skillId) return ["SET"];
  const meta = (skillsMetaByKit.value[kitId] ?? []).find(
    (item) => item.skill_id === skillId
  );
  const actions = Array.isArray(meta?.actions)
    ? meta.actions
        .map((item) => String(item || "").trim().toUpperCase())
        .filter(Boolean)
    : [];
  return actions.length ? actions : ["SET"];
}

function outputActionSpecs(kitId, skillId) {
  if (!kitId || !skillId) return {};
  const meta = (skillsMetaByKit.value[kitId] ?? []).find(
    (item) => item.skill_id === skillId
  );
  const rawSpecs = meta?.action_specs;
  if (!rawSpecs || typeof rawSpecs !== "object") return {};
  const normalized = {};
  for (const [actionName, rawFields] of Object.entries(rawSpecs)) {
    const action = String(actionName || "").trim().toUpperCase();
    if (!action || !Array.isArray(rawFields)) continue;
    normalized[action] = rawFields
      .filter((raw) => raw && typeof raw === "object")
      .map((raw) => {
        const type = ["string", "number", "boolean", "enum", "json"].includes(
          String(raw.type || "").toLowerCase()
        )
          ? String(raw.type || "").toLowerCase()
          : "string";
        const options = Array.isArray(raw.options)
          ? raw.options.map((item) => String(item)).filter(Boolean)
          : [];
        return {
          key: String(raw.key || raw.name || raw.id || "").trim(),
          label: String(raw.label || raw.key || raw.name || "").trim(),
          type,
          required: Boolean(raw.required),
          default: raw.default,
          min: typeof raw.min === "number" ? raw.min : null,
          max: typeof raw.max === "number" ? raw.max : null,
          options,
          placeholder: String(raw.placeholder || "").trim()
        };
      })
      .filter((field) => field.key);
  }
  return normalized;
}

function actionFieldsFor(kitId, skillId, action) {
  const normalizedAction = String(action || "SET").trim().toUpperCase();
  const specs = outputActionSpecs(kitId, skillId);
  if (Array.isArray(specs[normalizedAction]) && specs[normalizedAction].length) {
    return specs[normalizedAction];
  }
  return [];
}

function clearReactiveObject(target) {
  for (const key of Object.keys(target)) {
    delete target[key];
  }
}

function syncPayloadWithFields(target, fields, existingPayload = {}) {
  const previous = { ...target, ...existingPayload };
  clearReactiveObject(target);
  for (const field of fields) {
    const key = field.key;
    if (Object.prototype.hasOwnProperty.call(previous, key)) {
      target[key] = previous[key];
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(field, "default")) {
      target[key] = field.default;
      continue;
    }
    if (field.type === "boolean") {
      target[key] = false;
    } else if (field.type === "json") {
      target[key] = "{}";
    } else if (field.type === "number") {
      target[key] = field.min ?? 0;
    } else {
      target[key] = "";
    }
  }
}

function parsePayloadRaw(rawText, label) {
  const text = String(rawText || "").trim();
  if (!text) return {};
  try {
    const value = JSON.parse(text);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return value;
    }
    throw new Error(`${label} 必须是 JSON 对象`);
  } catch (err) {
    throw new Error(`${label} 解析失败: ${err.message}`);
  }
}

function toBooleanValue(value, key) {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const lowered = value.trim().toLowerCase();
    if (["true", "1", "yes", "on"].includes(lowered)) return true;
    if (["false", "0", "no", "off"].includes(lowered)) return false;
  }
  throw new Error(`字段 ${key} 必须是布尔值`);
}

function buildPayloadFromFields(values, fields) {
  const payload = {};
  for (const field of fields) {
    const key = field.key;
    const rawValue = values[key];
    const empty =
      rawValue === undefined
      || rawValue === null
      || (typeof rawValue === "string" && rawValue.trim() === "");
    if (empty) {
      if (field.required) {
        throw new Error(`字段 ${field.label || key} 为必填项`);
      }
      continue;
    }

    if (field.type === "number") {
      const num = Number(rawValue);
      if (!Number.isFinite(num)) {
        throw new Error(`字段 ${field.label || key} 必须是数字`);
      }
      if (typeof field.min === "number" && num < field.min) {
        throw new Error(`字段 ${field.label || key} 不能小于 ${field.min}`);
      }
      if (typeof field.max === "number" && num > field.max) {
        throw new Error(`字段 ${field.label || key} 不能大于 ${field.max}`);
      }
      payload[key] = num;
      continue;
    }

    if (field.type === "boolean") {
      payload[key] = toBooleanValue(rawValue, key);
      continue;
    }

    if (field.type === "enum") {
      const text = String(rawValue);
      if (Array.isArray(field.options) && field.options.length && !field.options.includes(text)) {
        throw new Error(`字段 ${field.label || key} 选项无效`);
      }
      payload[key] = text;
      continue;
    }

    if (field.type === "json") {
      if (typeof rawValue === "string") {
        try {
          payload[key] = JSON.parse(rawValue);
        } catch (err) {
          throw new Error(`字段 ${field.label || key} JSON 解析失败: ${err.message}`);
        }
      } else if (rawValue && typeof rawValue === "object") {
        payload[key] = rawValue;
      } else {
        throw new Error(`字段 ${field.label || key} 必须是 JSON`);
      }
      continue;
    }

    payload[key] = String(rawValue);
  }
  return payload;
}

function friendlyTime(ts) {
  if (!ts) return "--";
  return new Date(ts).toLocaleString();
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep fallback message.
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function ensureSkillSelections() {
  const sourceOptions = inputSkillOptions(formEventEditor.source_kit_id);
  if (!sourceOptions.includes(formEventEditor.source_skill)) {
    formEventEditor.source_skill = "";
  }

  const targetOptions = outputSkillOptions(formEventEditor.target_kit_id);
  if (!targetOptions.includes(formEventEditor.target_skill)) {
    formEventEditor.target_skill = "";
  }
  const formActions = outputSkillActions(
    formEventEditor.target_kit_id,
    formEventEditor.target_skill
  );
  formEventEditor.action = formActions.includes(formEventEditor.action)
    ? formEventEditor.action
    : (formActions[0] || "SET");

  const codeTargetOptions = outputSkillOptions(codeEventEditor.target_kit_id);
  if (!codeTargetOptions.includes(codeEventEditor.target_skill)) {
    codeEventEditor.target_skill = "";
  }
  const codeActions = outputSkillActions(
    codeEventEditor.target_kit_id,
    codeEventEditor.target_skill
  );
  codeEventEditor.action = codeActions.includes(codeEventEditor.action)
    ? codeEventEditor.action
    : (codeActions[0] || "SET");

  const directTargetOptions = outputSkillOptions(displayForm.kit_id);
  if (!directTargetOptions.includes(displayForm.skill_id)) {
    displayForm.skill_id = "";
  }
  const directActions = outputSkillActions(displayForm.kit_id, displayForm.skill_id);
  displayForm.action = directActions.includes(displayForm.action)
    ? displayForm.action
    : (directActions[0] || "SET");

  syncPayloadWithFields(
    directActionPayload,
    actionFieldsFor(displayForm.kit_id, displayForm.skill_id, displayForm.action)
  );
  syncPayloadWithFields(
    formActionPayload,
    actionFieldsFor(
      formEventEditor.target_kit_id,
      formEventEditor.target_skill,
      formEventEditor.action
    )
  );
  syncPayloadWithFields(
    codeActionPayload,
    actionFieldsFor(
      codeEventEditor.target_kit_id,
      codeEventEditor.target_skill,
      codeEventEditor.action
    )
  );
}

const formActionOptions = computed(() =>
  outputSkillActions(formEventEditor.target_kit_id, formEventEditor.target_skill)
);

const codeActionOptions = computed(() =>
  outputSkillActions(codeEventEditor.target_kit_id, codeEventEditor.target_skill)
);

const directActionOptions = computed(() =>
  outputSkillActions(displayForm.kit_id, displayForm.skill_id)
);

const directActionFields = computed(() =>
  actionFieldsFor(displayForm.kit_id, displayForm.skill_id, displayForm.action)
);

const formActionFields = computed(() =>
  actionFieldsFor(
    formEventEditor.target_kit_id,
    formEventEditor.target_skill,
    formEventEditor.action
  )
);

const codeActionFields = computed(() =>
  actionFieldsFor(
    codeEventEditor.target_kit_id,
    codeEventEditor.target_skill,
    codeEventEditor.action
  )
);

const codeToolSkills = computed(() => {
  if (!codeSkillTool.kit_id) return [];
  const raw = skillsMetaByKit.value[codeSkillTool.kit_id] ?? [];
  return raw.map((item) =>
    typeof item === "string" ? { skill_id: item, io_type: "", actions: ["SET"], action_specs: {} } : item
  );
});

const codeToolUsage = computed(() => {
  if (!codeSkillTool.kit_id || !codeSkillTool.skill_id) {
    return "# 选择 KIT 与 SKILL 后显示调用示例";
  }
  const meta = codeToolSkills.value.find((item) => item.skill_id === codeSkillTool.skill_id);
  if (!meta) {
    return "# 该 SKILL 不存在";
  }
  if (meta.io_type !== "output") {
    return [
      `# Input SKILL 示例: ${codeSkillTool.kit_id}/${codeSkillTool.skill_id}`,
      `value = ctx["get"]("${codeSkillTool.kit_id}", "${codeSkillTool.skill_id}", default=None)`,
      "if value is None:",
      "    return {\"trigger\": False}",
      "",
      "# 在你的逻辑中使用 value",
      "return {\"trigger\": False}"
    ].join("\n");
  }

  const actions = Array.isArray(meta.actions) && meta.actions.length ? meta.actions : ["SET"];
  const chosenAction = actions[0];
  const specs = meta.action_specs?.[chosenAction] ?? [];
  const payload = {};
  for (const field of specs) {
    if (field.type === "number") payload[field.key] = field.default ?? 0;
    else if (field.type === "boolean") payload[field.key] = Boolean(field.default ?? false);
    else if (field.type === "enum") payload[field.key] = field.default ?? field.options?.[0] ?? "";
    else if (field.type === "json") payload[field.key] = field.default ?? {};
    else payload[field.key] = field.default ?? "";
  }
  const payloadText = JSON.stringify(payload, null, 4)
    .split("\n")
    .map((line) => (line ? `        ${line}` : ""))
    .join("\n");
  return [
    `# Output SKILL 示例: ${codeSkillTool.kit_id}/${codeSkillTool.skill_id}`,
    "return {",
    "    \"trigger\": True,",
    "    \"actions\": [",
    "        {",
    `            \"target_kit_id\": \"${codeSkillTool.kit_id}\",`,
    `            \"target_skill\": \"${codeSkillTool.skill_id}\",`,
    `            \"action\": \"${chosenAction}\",`,
    `            \"payload\": ${payloadText || "{}"}`,
    "        }",
    "    ]",
    "}"
  ].join("\n");
});

function canToggleEvent(item) {
  return item.status !== "LOCKED" && item.status !== "DEAD";
}

function setTheme(theme) {
  uiTheme.value = theme;
  localStorage.setItem("zc_console_theme", theme);
}

function syncFormsFromSnapshot(data) {
  snapshot.value = data;
  if (!namesDirty.value) {
    namesForm.pool_name = data.profile?.pool_name ?? namesForm.pool_name;
    namesForm.gate_name = data.profile?.gate_name ?? namesForm.gate_name;
  }

  for (const item of data.kits ?? []) {
    if (!Object.prototype.hasOwnProperty.call(kitNameInput, item.kit_id)) {
      kitNameInput[item.kit_id] = item.display_name;
    }
  }

  if (!data.profile?.configured) {
    const gateId = String(data.profile?.gate_id || "").toUpperCase();
    const gateMatch = gateId.match(/^GATE_([A-Z0-9]{3})$/);
    if (!setupGateCodeInitialized.value) {
      setupGateCode.value = gateMatch ? gateMatch[1] : normalizeCodeInput(gateId);
      setupGateCodeInitialized.value = true;
    }
    activeTab.value = "setup";
  } else if (activeTab.value === "setup") {
    activeTab.value = "config";
    setupStep.value = 1;
  }

  ensureSkillSelections();
}

async function loadSnapshot() {
  busy.loading = true;
  try {
    const data = await apiRequest("/api/v1/state");
    syncFormsFromSnapshot(data);
    errorText.value = "";
  } catch (err) {
    errorText.value = err.message;
  } finally {
    busy.loading = false;
  }
}

async function loadEventMeta() {
  try {
    const [templates, framework] = await Promise.all([
      apiRequest("/api/v1/events/templates"),
      apiRequest("/api/v1/events/code-framework")
    ]);
    eventTemplates.value = templates.items ?? [];
    codeFramework.value = framework.code || DEFAULT_CODE_SKELETON;
    if (!codeEventEditor.code.trim()) {
      codeEventEditor.code = codeFramework.value;
    }
  } catch (err) {
    errorText.value = `加载 EVENT 元数据失败: ${err.message}`;
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPollingFallback() {
  if (pollTimer) return;
  pollTimer = setInterval(loadSnapshot, 2000);
}

function connectStream() {
  if (eventSource) {
    eventSource.close();
  }
  eventSource = new EventSource("/api/v1/stream");
  eventSource.addEventListener("state", (event) => {
    streamConnected.value = true;
    stopPolling();
    try {
      syncFormsFromSnapshot(JSON.parse(event.data));
      errorText.value = "";
    } catch (err) {
      errorText.value = `SSE parse failed: ${err.message}`;
    }
  });
  eventSource.onerror = () => {
    streamConnected.value = false;
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    startPollingFallback();
  };
}

async function saveNames() {
  busy.save_names = true;
  notice.value = "";
  errorText.value = "";
  try {
    await apiRequest("/api/v1/profile", {
      method: "PUT",
      body: JSON.stringify({
        pool_name: namesForm.pool_name,
        gate_name: namesForm.gate_name
      })
    });
    namesDirty.value = false;
    notice.value = "POOL/GATE 名称已更新";
  } catch (err) {
    errorText.value = `名称更新失败: ${err.message}`;
  } finally {
    busy.save_names = false;
  }
}

function applyDiscoveredPool(item) {
  const normalizedPoolId = String(item.pool_id || "").toUpperCase();
  const match = normalizedPoolId.match(/^POOL_([A-Z0-9]{3})$/);
  setupJoinForm.pool_code = match ? match[1] : normalizeCodeInput(normalizedPoolId);
  setupJoinForm.pool_name = item.pool_name || item.pool_id;
}

function beginSetup(mode) {
  if (mode === "join" && !ID3_PATTERN.test(normalizeCodeInput(setupJoinForm.pool_code))) {
    errorText.value = "请输入 3 位 POOL 编号（大写字母或数字）。";
    return;
  }
  if (mode === "create" && !ID3_PATTERN.test(normalizeCodeInput(setupCreateForm.pool_code))) {
    errorText.value = "请输入 3 位新 POOL 编号（大写字母或数字）。";
    return;
  }
  setupMode.value = mode;
  setupStep.value = 2;
}

async function finalizeSetup() {
  const busyKey = setupMode.value === "join" ? "setup_join" : "setup_create";
  busy[busyKey] = true;
  notice.value = "";
  errorText.value = "";
  try {
    const endpoint =
      setupMode.value === "join" ? "/api/v1/setup/join" : "/api/v1/setup/create";
    const poolCode = normalizeCodeInput(
      setupMode.value === "join" ? setupJoinForm.pool_code : setupCreateForm.pool_code
    );
    const gateCode = normalizeCodeInput(setupGateCode.value);
    if (!ID3_PATTERN.test(poolCode)) {
      throw new Error("POOL 编号必须为 3 位大写字母或数字");
    }
    if (!ID3_PATTERN.test(gateCode)) {
      throw new Error("GATE 编号必须为 3 位大写字母或数字");
    }
    const poolPayload =
      setupMode.value === "join"
        ? {
            pool_id: `POOL_${poolCode}`,
            pool_name: setupJoinForm.pool_name
          }
        : {
            pool_id: `POOL_${poolCode}`,
            pool_name: setupCreateForm.pool_name
          };
    await apiRequest(endpoint, {
      method: "POST",
      body: JSON.stringify({
        ...poolPayload,
        gate_id: `GATE_${gateCode}`,
        gate_name: setupGateName.value
      })
    });
    notice.value =
      setupMode.value === "join"
        ? `已绑定到 POOL_${poolCode}`
        : `已创建并绑定 POOL_${poolCode}`;
  } catch (err) {
    errorText.value = `首次组网失败: ${err.message}`;
  } finally {
    busy[busyKey] = false;
  }
}

function pendingKey(item) {
  return `${item.pool_id}:${item.uid}`;
}

function pendingForm(item) {
  const key = pendingKey(item);
  if (!pendingInput[key]) {
    pendingInput[key] = { kit_id: "", kit_name: "" };
  }
  return pendingInput[key];
}

async function adoptPending(item) {
  const key = pendingKey(item);
  const input = pendingForm(item);
  busy.adopt = key;
  notice.value = "";
  errorText.value = "";
  try {
    const result = await apiRequest(`/api/v1/pending/${item.uid}/adopt`, {
      method: "POST",
      body: JSON.stringify({
        pending_pool_id: item.pool_id,
        kit_id: input.kit_id || null,
        kit_name: input.kit_name || null
      })
    });
    notice.value = result.merged_existing
      ? `ADOPT 成功: ${item.uid} → ${result.kit_id}（UID 命中旧 KIT，已合并）`
      : `ADOPT 成功: ${item.uid} → ${result.kit_id}`;
    pendingInput[key] = { kit_id: "", kit_name: "" };
  } catch (err) {
    errorText.value = `ADOPT 失败: ${err.message}`;
  } finally {
    busy.adopt = "";
  }
}

async function renameKit(kitId) {
  busy.rename_kit = kitId;
  notice.value = "";
  errorText.value = "";
  try {
    await apiRequest(`/api/v1/kits/${kitId}/name`, {
      method: "PATCH",
      body: JSON.stringify({ name: kitNameInput[kitId] || kitId })
    });
    notice.value = `${kitId} 命名已更新`;
  } catch (err) {
    errorText.value = `KIT 命名失败: ${err.message}`;
  } finally {
    busy.rename_kit = "";
  }
}

async function forceDeleteKit(kitId) {
  if (
    !window.confirm(
      `确认删除 ${kitId}？删除后该 KIT 会进入死亡身份，直接重连将被忽略。`
    )
  ) {
    return;
  }
  busy.delete_kit = kitId;
  notice.value = "";
  errorText.value = "";
  try {
    await apiRequest(`/api/v1/kits/${kitId}?force=true`, { method: "DELETE" });
    notice.value = `${kitId} 已强制删除`;
  } catch (err) {
    errorText.value = `强制删除失败: ${err.message}`;
  } finally {
    busy.delete_kit = "";
  }
}

async function sendDisplay() {
  if (!displayForm.kit_id || !displayForm.skill_id) return;
  busy.display_send = true;
  notice.value = "";
  errorText.value = "";
  try {
    const payload = directActionFields.value.length
      ? buildPayloadFromFields(directActionPayload, directActionFields.value)
      : parsePayloadRaw(directActionPayloadRaw.value, "C2 Payload");
    await apiRequest(`/api/v1/kits/${displayForm.kit_id}/invoke`, {
      method: "POST",
      body: JSON.stringify({
        skill_id: displayForm.skill_id,
        action: displayForm.action,
        payload
      })
    });
    notice.value = `输出指令已下发到 ${displayForm.kit_id}/${displayForm.skill_id}`;
  } catch (err) {
    errorText.value = `输出指令失败: ${err.message}`;
  } finally {
    busy.display_send = false;
  }
}

async function resetKit(kitId) {
  busy.reset_kit = kitId;
  notice.value = "";
  errorText.value = "";
  try {
    await apiRequest(`/api/v1/kits/${kitId}/reset`, { method: "POST" });
    notice.value = `已下发 SYS/RESET 到 ${kitId}`;
  } catch (err) {
    errorText.value = `RESET 失败: ${err.message}`;
  } finally {
    busy.reset_kit = "";
  }
}

function clearFormEditor() {
  formEventEditor.event_id = "";
  formEventEditor.name = "";
  formEventEditor.enabled = true;
  formEventEditor.cooldown_ms = 1500;
  formEventEditor.source_kit_id = "";
  formEventEditor.source_skill = "";
  formEventEditor.target_kit_id = "";
  formEventEditor.target_skill = "";
  formEventEditor.action = "SET";
  formEventEditor.operator = ">";
  formEventEditor.threshold = 30;
  formActionPayloadRaw.value = "{}";
  clearReactiveObject(formActionPayload);
  ensureSkillSelections();
}

function clearCodeEditor() {
  codeEventEditor.event_id = "";
  codeEventEditor.name = "";
  codeEventEditor.enabled = true;
  codeEventEditor.cooldown_ms = 1500;
  codeEventEditor.code = codeFramework.value || DEFAULT_CODE_SKELETON;
  codeEventEditor.required_keys = [];
  codeEventEditor.fallback_enabled = false;
  codeEventEditor.target_kit_id = "";
  codeEventEditor.target_skill = "";
  codeEventEditor.action = "SET";
  codeActionPayloadRaw.value = "{}";
  clearReactiveObject(codeActionPayload);
  ensureSkillSelections();
}

function formEventPayload() {
  const actionPayload = formActionFields.value.length
    ? buildPayloadFromFields(formActionPayload, formActionFields.value)
    : parsePayloadRaw(formActionPayloadRaw.value, "表单 ACTION Payload");

  return {
    name: formEventEditor.name,
    mode: "form",
    enabled: formEventEditor.enabled,
    cooldown_ms: Number(formEventEditor.cooldown_ms),
    condition: {
      source_kit_id: formEventEditor.source_kit_id,
      source_skill: formEventEditor.source_skill,
      operator: formEventEditor.operator,
      threshold: Number(formEventEditor.threshold)
    },
    action: {
      target_kit_id: formEventEditor.target_kit_id,
      target_skill: formEventEditor.target_skill,
      action: formEventEditor.action,
      payload: actionPayload
    },
    required_skills: [],
    code: ""
  };
}

function codeEventPayload() {
  return {
    name: codeEventEditor.name,
    mode: "code",
    enabled: codeEventEditor.enabled,
    cooldown_ms: Number(codeEventEditor.cooldown_ms),
    condition: null,
    action: null,
    required_skills: [],
    code: codeEventEditor.code
  };
}

async function saveFormEvent() {
  busy.save_form_event = true;
  notice.value = "";
  errorText.value = "";
  try {
    const payload = formEventPayload();
    if (formEventEditor.event_id) {
      await apiRequest(`/api/v1/events/${formEventEditor.event_id}`, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      notice.value = "表单 EVENT 已更新";
    } else {
      await apiRequest("/api/v1/events", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      notice.value = "表单 EVENT 已创建";
    }
    clearFormEditor();
  } catch (err) {
    errorText.value = `表单 EVENT 失败: ${err.message}`;
  } finally {
    busy.save_form_event = false;
  }
}

async function saveCodeEvent() {
  busy.save_code_event = true;
  notice.value = "";
  errorText.value = "";
  try {
    const payload = codeEventPayload();
    if (codeEventEditor.event_id) {
      await apiRequest(`/api/v1/events/${codeEventEditor.event_id}`, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      notice.value = "代码 EVENT 已更新";
    } else {
      await apiRequest("/api/v1/events", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      notice.value = "代码 EVENT 已创建";
    }
    clearCodeEditor();
  } catch (err) {
    errorText.value = `代码 EVENT 失败: ${err.message}`;
  } finally {
    busy.save_code_event = false;
  }
}

function insertSkillUsageSnippet() {
  if (!codeSkillTool.kit_id || !codeSkillTool.skill_id) {
    errorText.value = "请先在 SKILL 方法查看工具中选择 KIT 和 SKILL。";
    return;
  }
  const snippet = codeToolUsage.value;
  const code = codeEventEditor.code || "";
  codeEventEditor.code = code.trim()
    ? `${code.trim()}\n\n${snippet}\n`
    : `${snippet}\n`;
  notice.value = `已插入 ${codeSkillTool.kit_id}/${codeSkillTool.skill_id} 调用示例`;
}

async function testCodeEvent() {
  if (!codeEventEditor.code.trim()) {
    errorText.value = "请先填写代码。";
    return;
  }
  busy.test_code = true;
  notice.value = "";
  errorText.value = "";
  try {
    const result = await apiRequest("/api/v1/events/code-test", {
      method: "POST",
      body: JSON.stringify({ code: codeEventEditor.code })
    });
    if (result.ok) {
      notice.value = `代码测试通过（phase=${result.phase}）`;
    } else {
      errorText.value = `代码测试失败（${result.phase}）: ${result.error}`;
    }
  } catch (err) {
    errorText.value = `代码测试失败: ${err.message}`;
  } finally {
    busy.test_code = false;
  }
}

async function toggleEvent(item, enabled) {
  if (!canToggleEvent(item)) return;
  busy.toggle_event = item.event_id;
  notice.value = "";
  errorText.value = "";
  try {
    await apiRequest(`/api/v1/events/${item.event_id}/enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled })
    });
    notice.value = `${item.name} 已${enabled ? "启用" : "停用"}`;
  } catch (err) {
    errorText.value = `切换 EVENT 失败: ${err.message}`;
  } finally {
    busy.toggle_event = "";
  }
}

async function removeEvent(item) {
  busy.delete_event = item.event_id;
  notice.value = "";
  errorText.value = "";
  try {
    await apiRequest(`/api/v1/events/${item.event_id}`, { method: "DELETE" });
    notice.value = `${item.name} 已删除`;
  } catch (err) {
    errorText.value = `删除 EVENT 失败: ${err.message}`;
  } finally {
    busy.delete_event = "";
  }
}

async function requestGateResetCode() {
  busy.gate_reset_code = true;
  notice.value = "";
  errorText.value = "";
  try {
    const result = await apiRequest("/api/v1/gate/reset/challenge", {
      method: "POST"
    });
    gateReset.challenge_code = String(result.code || "");
    gateReset.input_code = "";
    notice.value = "已生成重置验证码，请输入后确认重置。";
  } catch (err) {
    errorText.value = `生成重置验证码失败: ${err.message}`;
  } finally {
    busy.gate_reset_code = false;
  }
}

async function confirmGateReset() {
  if (!gateReset.challenge_code) {
    errorText.value = "请先生成重置验证码。";
    return;
  }
  if (!gateReset.input_code.trim()) {
    errorText.value = "请输入验证码。";
    return;
  }
  if (
    !window.confirm(
      "将清空本 GATE 的全部配置（POOL/KIT/EVENT），并回到首次组网页面。确认继续？"
    )
  ) {
    return;
  }
  busy.gate_reset_confirm = true;
  notice.value = "";
  errorText.value = "";
  try {
    await apiRequest("/api/v1/gate/reset/confirm", {
      method: "POST",
      body: JSON.stringify({ code: gateReset.input_code.trim() })
    });
    gateReset.challenge_code = "";
    gateReset.input_code = "";
    setupJoinForm.pool_code = "";
    setupJoinForm.pool_name = "";
    setupCreateForm.pool_code = "";
    setupCreateForm.pool_name = "";
    setupGateCode.value = "";
    setupGateCodeInitialized.value = false;
    setupGateName.value = "";
    setupStep.value = 1;
    activeTab.value = "setup";
    await loadSnapshot();
    notice.value = "本 GATE 已重置，已回到首次组网页面。";
    setTimeout(() => {
      window.location.reload();
    }, 300);
  } catch (err) {
    errorText.value = `重置失败: ${err.message}`;
  } finally {
    busy.gate_reset_confirm = false;
  }
}

function loadEventToEditor(item) {
  if (item.mode === "form") {
    eventEditorTab.value = "form";
    formEventEditor.event_id = item.event_id;
    formEventEditor.name = item.name;
    formEventEditor.enabled = item.enabled;
    formEventEditor.cooldown_ms = item.cooldown_ms;
    formEventEditor.source_kit_id = item.condition?.source_kit_id || "";
    formEventEditor.source_skill = item.condition?.source_skill || "";
    formEventEditor.operator = item.condition?.operator || ">";
    formEventEditor.threshold = item.condition?.threshold ?? 0;
    formEventEditor.target_kit_id = item.action?.target_kit_id || "";
    formEventEditor.target_skill = item.action?.target_skill || "";
    formEventEditor.action = item.action?.action || "SET";
    const nextFields = actionFieldsFor(
      formEventEditor.target_kit_id,
      formEventEditor.target_skill,
      formEventEditor.action
    );
    if (nextFields.length) {
      syncPayloadWithFields(formActionPayload, nextFields, item.action?.payload || {});
      formActionPayloadRaw.value = "{}";
    } else {
      clearReactiveObject(formActionPayload);
      formActionPayloadRaw.value = JSON.stringify(item.action?.payload || {}, null, 2);
    }
    ensureSkillSelections();
    return;
  }

  eventEditorTab.value = "code";
  codeEventEditor.event_id = item.event_id;
  codeEventEditor.name = item.name;
  codeEventEditor.enabled = item.enabled;
  codeEventEditor.cooldown_ms = item.cooldown_ms;
  codeEventEditor.code = item.code || codeFramework.value || DEFAULT_CODE_SKELETON;
  codeEventEditor.required_keys = [];
  codeEventEditor.fallback_enabled = false;
  codeEventEditor.target_kit_id = "";
  codeEventEditor.target_skill = "";
  codeEventEditor.action = "SET";
  clearReactiveObject(codeActionPayload);
  codeActionPayloadRaw.value = "{}";
  ensureSkillSelections();
}

function applyTemplate(template) {
  if (template.mode === "form") {
    eventEditorTab.value = "form";
    formEventEditor.event_id = "";
    formEventEditor.name = template.name;
    formEventEditor.cooldown_ms = template.payload?.cooldown_ms ?? 1500;
    formEventEditor.operator = template.payload?.condition?.operator ?? ">";
    formEventEditor.threshold = template.payload?.condition?.threshold ?? 30;
    formEventEditor.source_skill = template.payload?.condition?.source_skill ?? "";
    formEventEditor.target_skill = template.payload?.action?.target_skill ?? "";
    formEventEditor.action = template.payload?.action?.action ?? "SET";
    const templatePayload = template.payload?.action?.payload ?? {};
    const nextFields = actionFieldsFor(
      formEventEditor.target_kit_id,
      formEventEditor.target_skill,
      formEventEditor.action
    );
    if (nextFields.length) {
      syncPayloadWithFields(formActionPayload, nextFields, templatePayload);
      formActionPayloadRaw.value = "{}";
    } else {
      clearReactiveObject(formActionPayload);
      formActionPayloadRaw.value = JSON.stringify(templatePayload, null, 2);
    }
    ensureSkillSelections();
    return;
  }

  eventEditorTab.value = "code";
  codeEventEditor.event_id = "";
  codeEventEditor.name = template.name;
  codeEventEditor.cooldown_ms = template.payload?.cooldown_ms ?? 1500;
  codeEventEditor.code = template.payload?.code || codeFramework.value || DEFAULT_CODE_SKELETON;
  codeEventEditor.action = "SET";
  clearReactiveObject(codeActionPayload);
  codeActionPayloadRaw.value = "{}";
  codeEventEditor.required_keys = [];
  codeEventEditor.fallback_enabled = false;
  codeEventEditor.target_kit_id = "";
  codeEventEditor.target_skill = "";
}

onMounted(async () => {
  await loadSnapshot();
  await loadEventMeta();
  connectStream();
});

onBeforeUnmount(() => {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  stopPolling();
});
</script>

<template>
  <main :class="['metro-shell', uiTheme === 'blue' ? 'theme-blue' : 'theme-mono']">
    <header class="metro-header">
      <div class="metro-header-main">
        <div class="metro-brand">
          <h1>ZeroCloud · MAGI Console</h1>
          <p>
            {{ snapshot.profile.pool_name }} ({{ snapshot.profile.pool_id }}) /
            {{ snapshot.profile.gate_name }} ({{ snapshot.profile.gate_id }})
          </p>
        </div>
        <div class="metro-header-actions">
          <span class="metro-pill" :class="metrics.mqtt_connected ? 'badge-online' : 'badge-offline'">
            MQTT {{ metrics.mqtt_connected ? "ONLINE" : "OFFLINE" }}
          </span>
          <span class="metro-pill" :class="streamConnected ? 'badge-live' : 'badge-fallback'">
            {{ streamConnected ? "STREAM LIVE" : "POLLING MODE" }}
          </span>
          <button
            v-if="isConfigured"
            class="metro-danger-btn"
            @click="activeTab = 'danger'"
          >
            重置本 GATE
          </button>
          <button class="metro-theme-btn" :class="{ 'is-active': uiTheme === 'blue' }" @click="setTheme('blue')">
            Blue
          </button>
          <button class="metro-theme-btn" :class="{ 'is-active': uiTheme === 'mono' }" @click="setTheme('mono')">
            Mono
          </button>
        </div>
      </div>

      <div class="metro-tile-strip">
        <article class="metro-tile metro-tile-small">
          <p class="metro-tile-label">TPS</p>
          <h3>{{ Number(metrics.frame_tps || 0).toFixed(1) }}</h3>
        </article>
        <article class="metro-tile metro-tile-pool">
          <p class="metro-tile-label">POOL</p>
          <h3>{{ snapshot.profile.pool_name || snapshot.profile.pool_id }}</h3>
        </article>
        <article class="metro-tile metro-tile-small">
          <p class="metro-tile-label">KITS</p>
          <h3>{{ metrics.kits_total || 0 }}</h3>
        </article>
        <article class="metro-tile metro-tile-small">
          <p class="metro-tile-label">ONLINE</p>
          <h3>{{ metrics.kits_online || 0 }}</h3>
        </article>
        <article class="metro-tile metro-tile-small">
          <p class="metro-tile-label">PENDING</p>
          <h3>{{ metrics.pending_total || 0 }}</h3>
        </article>
        <article class="metro-tile metro-tile-small">
          <p class="metro-tile-label">EVENTS</p>
          <h3>{{ metrics.events_total || 0 }}</h3>
        </article>
        <article class="metro-tile metro-tile-small">
          <p class="metro-tile-label">LOCKED</p>
          <h3>{{ metrics.events_locked || 0 }}</h3>
        </article>
        <article class="metro-tile metro-tile-small">
          <p class="metro-tile-label">DEAD</p>
          <h3>{{ metrics.events_dead || 0 }}</h3>
        </article>
      </div>
    </header>

    <nav class="metro-tabbar">
      <button
        v-for="item in visibleTabs"
        :key="item.id"
        class="metro-tab"
        :class="{ 'is-active': activeTab === item.id }"
        @click="activeTab = item.id"
      >
        {{ item.label }}
      </button>
      <button
        class="metro-tab metro-sync"
        :disabled="busy.loading"
        @click="loadSnapshot"
      >
        {{ busy.loading ? "SYNC..." : "SYNC NOW" }}
      </button>
    </nav>

    <section v-if="activeTab === 'setup'" class="mx-auto grid max-w-[1680px] gap-4 xl:grid-cols-12">
      <article class="rounded-2xl border border-amber-400/50 bg-amber-500/10 p-4 xl:col-span-12">
        <p class="text-sm text-amber-100">
          首次启动引导：Step 1 选 POOL，Step 2 仅命名 GATE。完成后该页面自动隐藏。
        </p>
      </article>

      <article v-if="setupStep === 1" class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-6">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">Step 1 · 加入已存在 POOL</h2>
        <div class="mt-3 grid gap-2">
          <div class="grid grid-cols-[auto,1fr] gap-2">
            <div class="rounded-md border border-slate-600 bg-slate-900/80 px-2 py-2 text-sm text-slate-300">POOL_</div>
            <input
              v-model="setupJoinForm.pool_code"
              maxlength="3"
              class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm uppercase outline-none focus:border-magi-neon"
              placeholder="三位编号（如 A1B）"
            />
          </div>
          <input v-model="setupJoinForm.pool_name" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="POOL 名称" />
          <button class="rounded-md border border-emerald-400/70 bg-emerald-500/15 px-3 py-2 text-sm text-emerald-100 transition hover:bg-emerald-500/25" @click="beginSetup('join')">
            选择加入此 POOL
          </button>
        </div>
      </article>

      <article v-if="setupStep === 1" class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-6">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">Step 1 · 创建新 POOL</h2>
        <div class="mt-3 grid gap-2">
          <div class="grid grid-cols-[auto,1fr] gap-2">
            <div class="rounded-md border border-slate-600 bg-slate-900/80 px-2 py-2 text-sm text-slate-300">POOL_</div>
            <input
              v-model="setupCreateForm.pool_code"
              maxlength="3"
              class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm uppercase outline-none focus:border-magi-neon"
              placeholder="三位编号（如 1A9）"
            />
          </div>
          <input v-model="setupCreateForm.pool_name" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="新 POOL 名称" />
          <button class="rounded-md border border-blue-400/70 bg-blue-500/15 px-3 py-2 text-sm text-blue-100 transition hover:bg-blue-500/25" @click="beginSetup('create')">
            选择创建此 POOL
          </button>
        </div>
      </article>

      <article v-if="setupStep === 2" class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-12">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">Step 2 · 命名 GATE</h2>
        <div class="mt-3 max-w-xl grid gap-2">
          <div class="grid grid-cols-[auto,1fr] gap-2">
            <div class="rounded-md border border-slate-600 bg-slate-900/80 px-2 py-2 text-sm text-slate-300">GATE_</div>
            <input
              v-model="setupGateCode"
              maxlength="3"
              class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm uppercase outline-none focus:border-magi-neon"
              placeholder="三位编号（如 N01）"
            />
          </div>
          <input v-model="setupGateName" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="GATE 名称" />
          <div class="flex flex-wrap gap-2">
            <button class="rounded-md border border-magi-neon/70 bg-magi-neon/15 px-3 py-2 text-sm text-magi-neon transition hover:bg-magi-neon/25 disabled:opacity-50" :disabled="(setupMode === 'join' && busy.setup_join) || (setupMode === 'create' && busy.setup_create)" @click="finalizeSetup">
              {{
                setupMode === "join"
                  ? (busy.setup_join ? "APPLYING..." : "完成绑定")
                  : (busy.setup_create ? "APPLYING..." : "创建并绑定")
              }}
            </button>
            <button class="rounded-md border border-slate-500 px-3 py-2 text-sm text-slate-300 transition hover:border-slate-300" @click="setupStep = 1">
              返回上一步
            </button>
          </div>
        </div>
      </article>

      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-12">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">附近 POOL</h2>
        <div class="mt-3 overflow-x-auto">
          <table class="w-full min-w-[680px] text-left text-xs">
            <thead>
              <tr class="border-b border-slate-700 text-slate-300">
                <th class="py-2">POOL</th>
                <th class="py-2">GATE 列表</th>
                <th class="py-2">最近发现</th>
                <th class="py-2">动作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in discoveredPools" :key="item.pool_id" class="border-b border-slate-800/80 text-slate-100">
                <td class="py-2">{{ item.pool_name }} ({{ item.pool_id }})</td>
                <td class="py-2">
                  <span v-for="gate in item.gates" :key="`${item.pool_id}-${gate.gate_id}`" class="mr-1 rounded border border-blue-400/40 bg-blue-400/10 px-2 py-0.5 text-[11px]">
                    {{ gate.gate_name }} ({{ gate.gate_id }})
                  </span>
                </td>
                <td class="py-2">{{ friendlyTime(item.last_seen) }}</td>
                <td class="py-2">
                  <button class="rounded border border-emerald-400/70 bg-emerald-500/15 px-2 py-1 text-[11px] text-emerald-100" @click="applyDiscoveredPool(item)">
                    填入“加入 POOL”
                  </button>
                </td>
              </tr>
              <tr v-if="!discoveredPools.length">
                <td colspan="4" class="py-3 text-slate-500">暂无发现记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </section>

    <section v-if="activeTab === 'config'" class="mx-auto grid max-w-[1680px] gap-4 xl:grid-cols-12">
      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-6">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">POOL/GATE 名称配置</h2>
        <div class="mt-3 grid gap-2">
          <div class="rounded-md border border-slate-700 bg-slate-900/50 px-2 py-2 text-xs text-slate-300">
            POOL_ID: {{ snapshot.profile.pool_id }}
          </div>
          <div class="rounded-md border border-slate-700 bg-slate-900/50 px-2 py-2 text-xs text-slate-300">
            GATE_ID: {{ snapshot.profile.gate_id }}
          </div>
          <input v-model="namesForm.pool_name" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="POOL 显示名称" @input="namesDirty = true" />
          <input v-model="namesForm.gate_name" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="GATE 显示名称" @input="namesDirty = true" />
          <button class="rounded-md border border-magi-neon/70 bg-magi-neon/15 px-3 py-2 text-sm text-magi-neon transition hover:bg-magi-neon/25 disabled:opacity-50" :disabled="busy.save_names" @click="saveNames">
            {{ busy.save_names ? "SAVING..." : "保存名称" }}
          </button>
        </div>
      </article>

      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-6">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">POOL 可视表</h2>
        <div class="mt-3 overflow-x-auto">
          <table class="w-full min-w-[560px] text-left text-xs">
            <thead>
              <tr class="border-b border-slate-700 text-slate-300">
                <th class="py-2">POOL</th>
                <th class="py-2">GATE 数</th>
                <th class="py-2">最近发现</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in discoveredPools" :key="item.pool_id" class="border-b border-slate-800/80 text-slate-100">
                <td class="py-2">{{ item.pool_name }} ({{ item.pool_id }})</td>
                <td class="py-2">{{ item.gates_total }}</td>
                <td class="py-2">{{ friendlyTime(item.last_seen) }}</td>
              </tr>
              <tr v-if="!discoveredPools.length">
                <td colspan="3" class="py-3 text-slate-500">暂无数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

    </section>

    <section v-if="activeTab === 'danger'" class="mx-auto grid max-w-[1680px] gap-4 xl:grid-cols-12">
      <article class="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 xl:col-span-12">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-semibold tracking-wider text-rose-200">重置本 GATE（危险操作）</h2>
          <button class="rounded border border-slate-400 px-2 py-1 text-xs text-slate-200" @click="activeTab = isConfigured ? 'config' : 'setup'">
            返回
          </button>
        </div>
        <p class="mt-2 text-xs text-rose-100/90">
          将删除本 GATE 的全部配置（POOL/KIT/EVENT），并回到首次组网页面。请先生成随机验证码，再输入验证码确认。
        </p>
        <div class="mt-3 grid gap-2 sm:grid-cols-3">
          <button
            class="rounded-md border border-rose-300/70 bg-rose-500/20 px-3 py-2 text-sm text-rose-100 transition hover:bg-rose-500/30 disabled:opacity-50"
            :disabled="busy.gate_reset_code"
            @click="requestGateResetCode"
          >
            {{ busy.gate_reset_code ? "生成中..." : "生成随机验证码" }}
          </button>
          <input
            :value="gateReset.challenge_code"
            readonly
            class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm text-amber-200 outline-none"
            placeholder="验证码将在此显示"
          />
          <input
            v-model="gateReset.input_code"
            class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-rose-300"
            placeholder="输入上方验证码"
          />
        </div>
        <div class="mt-2">
          <button
            class="rounded-md border border-rose-300/70 bg-rose-500/25 px-3 py-2 text-sm text-rose-100 transition hover:bg-rose-500/35 disabled:opacity-50"
            :disabled="busy.gate_reset_confirm || !gateReset.challenge_code || !gateReset.input_code.trim()"
            @click="confirmGateReset"
          >
            {{ busy.gate_reset_confirm ? "重置中..." : "确认重置本 GATE" }}
          </button>
        </div>
      </article>
    </section>

    <section v-if="activeTab === 'kits'" class="mx-auto grid max-w-[1680px] gap-4 xl:grid-cols-12">
      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-4">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">待收编 KIT（兼容 ESP32 PENDING）</h2>
        <div class="mt-3 space-y-3">
          <div v-for="item in pendingKits" :key="pendingKey(item)" class="rounded-xl border border-amber-400/30 bg-amber-500/5 p-3">
            <p class="text-xs text-slate-300">POOL: {{ item.pool_id }}</p>
            <p class="mt-1 break-all text-xs text-amber-100">UID: {{ item.uid }}</p>
            <p class="mt-1 text-xs text-slate-100">SKILLS: {{ item.skills.join(" · ") || "--" }}</p>
            <input v-model="pendingForm(item).kit_id" class="mt-2 w-full rounded-md border border-slate-600 bg-slate-950/80 px-2 py-1 text-xs outline-none focus:border-magi-neon" placeholder="KIT_XXXXX（1-5位大写字母/数字）" />
            <input v-model="pendingForm(item).kit_name" class="mt-2 w-full rounded-md border border-slate-600 bg-slate-950/80 px-2 py-1 text-xs outline-none focus:border-magi-neon" placeholder="KIT 名称（可选）" />
            <button class="mt-2 w-full rounded-md border border-emerald-400/70 bg-emerald-500/20 px-2 py-1 text-xs text-emerald-100 transition hover:bg-emerald-500/30 disabled:opacity-50" :disabled="busy.adopt === pendingKey(item)" @click="adoptPending(item)">
              {{ busy.adopt === pendingKey(item) ? "ADOPTING..." : "ADOPT" }}
            </button>
          </div>
          <p v-if="!pendingKits.length" class="text-xs text-slate-500">当前没有待收编设备</p>
        </div>
      </article>

      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-4">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">C2 OUTPUT 接管</h2>
        <div class="mt-3 grid gap-2">
          <select v-model="displayForm.kit_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="ensureSkillSelections">
            <option disabled value="">选择在线 KIT</option>
            <option v-for="item in onlineKits" :key="item.kit_id" :value="item.kit_id">
              {{ item.display_name }} ({{ item.kit_id }})
            </option>
          </select>
          <select v-model="displayForm.skill_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="ensureSkillSelections">
            <option disabled value="">选择 Output SKILL</option>
            <option v-for="skill in outputSkillOptions(displayForm.kit_id)" :key="`c2-skill-${skill}`" :value="skill">
              {{ skill }}
            </option>
          </select>
          <select v-model="displayForm.action" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="ensureSkillSelections">
            <option v-for="action in directActionOptions" :key="`c2-action-${action}`" :value="action">
              {{ action }}
            </option>
          </select>
          <div v-if="directActionFields.length" class="grid gap-2 sm:grid-cols-2">
            <div v-for="field in directActionFields" :key="`c2-field-${field.key}`" class="grid gap-1">
              <label class="text-[11px] text-slate-300">{{ field.label || field.key }}</label>
              <input
                v-if="field.type === 'number'"
                v-model.number="directActionPayload[field.key]"
                type="number"
                :min="field.min ?? undefined"
                :max="field.max ?? undefined"
                class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon"
                :placeholder="field.placeholder || field.key"
              />
              <select
                v-else-if="field.type === 'enum'"
                v-model="directActionPayload[field.key]"
                class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon"
              >
                <option disabled value="">选择 {{ field.label || field.key }}</option>
                <option v-for="item in field.options" :key="`c2-opt-${field.key}-${item}`" :value="item">{{ item }}</option>
              </select>
              <label
                v-else-if="field.type === 'boolean'"
                class="flex items-center gap-2 rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm"
              >
                <input type="checkbox" v-model="directActionPayload[field.key]" />
                {{ field.label || field.key }}
              </label>
              <textarea
                v-else-if="field.type === 'json'"
                v-model="directActionPayload[field.key]"
                rows="3"
                class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-xs outline-none focus:border-magi-neon"
                :placeholder="field.placeholder || 'JSON payload'"
              />
              <input
                v-else
                v-model="directActionPayload[field.key]"
                type="text"
                class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon"
                :placeholder="field.placeholder || field.key"
              />
            </div>
          </div>
          <textarea
            v-else
            v-model="directActionPayloadRaw"
            rows="4"
            class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-xs outline-none focus:border-magi-neon"
            placeholder='自定义 Payload JSON，例如 {"msg":"HELLO","duration":5000}'
          />
          <button class="rounded-md border border-emerald-400/70 bg-emerald-500/20 px-3 py-2 text-sm text-emerald-100 transition hover:bg-emerald-500/30 disabled:opacity-50" :disabled="!displayForm.kit_id || !displayForm.skill_id || busy.display_send" @click="sendDisplay">
            {{ busy.display_send ? "SENDING..." : "发送 OUTPUT 指令" }}
          </button>
        </div>
      </article>

      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-4">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">KIT 管理</h2>
        <div class="mt-3 space-y-2">
          <div v-for="item in kits" :key="item.kit_id" class="rounded-xl border border-slate-700/90 bg-slate-900/50 p-3">
            <div class="flex items-center justify-between gap-2">
              <p class="text-sm text-slate-100">{{ item.display_name }} ({{ item.kit_id }})</p>
              <span class="rounded-full border px-2 py-0.5 text-[11px]" :class="lifecycleClass(item.lifecycle_state)">
                {{ item.lifecycle_state }}
              </span>
            </div>
            <p class="mt-1 text-[11px] text-slate-400">UID: {{ item.uid || "--" }}</p>
            <p class="text-[11px] text-slate-400">Last Seen: {{ friendlyTime(item.last_seen) }}</p>
            <input v-model="kitNameInput[item.kit_id]" class="mt-2 w-full rounded border border-slate-600 bg-slate-950/80 px-2 py-1 text-xs outline-none focus:border-magi-neon" placeholder="KIT 名称" />
            <button class="mt-2 rounded border border-blue-400/70 bg-blue-500/20 px-2 py-1 text-xs text-blue-100 transition hover:bg-blue-500/30 disabled:opacity-50" :disabled="busy.rename_kit === item.kit_id" @click="renameKit(item.kit_id)">
              {{ busy.rename_kit === item.kit_id ? "SAVING..." : "保存命名" }}
            </button>
            <div class="mt-2 flex flex-wrap gap-1">
              <span v-for="skill in item.skills" :key="`${item.kit_id}-${skill}`" class="rounded border border-blue-400/40 bg-blue-400/10 px-2 py-0.5 text-[11px] text-blue-100">
                {{ skill }}: {{ item.skill_values?.[skill] ?? "--" }}
              </span>
            </div>
            <div class="mt-3 flex flex-wrap gap-2">
              <button class="rounded border border-amber-400/70 bg-amber-500/15 px-2 py-1 text-[11px] text-amber-100 transition hover:bg-amber-500/25 disabled:opacity-50" :disabled="busy.reset_kit === item.kit_id" @click="resetKit(item.kit_id)">
                {{ busy.reset_kit === item.kit_id ? "SENDING..." : "SYS/RESET" }}
              </button>
              <button class="rounded border border-rose-400/70 bg-rose-500/15 px-2 py-1 text-[11px] text-rose-100 transition hover:bg-rose-500/25 disabled:opacity-50" :disabled="busy.delete_kit === item.kit_id" @click="forceDeleteKit(item.kit_id)">
                {{ busy.delete_kit === item.kit_id ? "DELETING..." : "删除 KIT（强制）" }}
              </button>
            </div>
          </div>
          <p v-if="!kits.length" class="text-xs text-slate-500">暂无已接入 KIT</p>
        </div>
      </article>
    </section>

    <section v-if="activeTab === 'events'" class="mx-auto grid max-w-[1680px] gap-4 xl:grid-cols-12">
      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-8">
        <div class="mb-3 flex flex-wrap items-center gap-2">
          <button class="rounded border px-3 py-1 text-xs transition" :class="eventEditorTab === 'form' ? 'border-magi-neon bg-magi-neon/15 text-magi-neon' : 'border-slate-600 text-slate-300'" @click="eventEditorTab = 'form'">简单逻辑（表单）</button>
          <button class="rounded border px-3 py-1 text-xs transition" :class="eventEditorTab === 'code' ? 'border-magi-neon bg-magi-neon/15 text-magi-neon' : 'border-slate-600 text-slate-300'" @click="eventEditorTab = 'code'">复杂逻辑（代码）</button>
          <button class="rounded border px-3 py-1 text-xs transition" :class="eventEditorTab === 'templates' ? 'border-magi-neon bg-magi-neon/15 text-magi-neon' : 'border-slate-600 text-slate-300'" @click="eventEditorTab = 'templates'">内置模板</button>
        </div>

        <div v-if="eventEditorTab === 'form'" class="grid gap-2">
          <h3 class="text-sm font-semibold text-magi-neon">表单 EVENT 编辑器</h3>
          <input v-model="formEventEditor.name" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="事件名称" />
          <div class="grid gap-2 sm:grid-cols-2">
            <select v-model="formEventEditor.source_kit_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="ensureSkillSelections">
              <option disabled value="">Source KIT（原因设备）</option>
              <option v-for="item in kits" :key="`src-${item.kit_id}`" :value="item.kit_id">{{ item.display_name }} ({{ item.kit_id }})</option>
            </select>
            <select v-model="formEventEditor.source_skill" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon">
              <option disabled value="">Input SKILL（原因）</option>
              <option v-for="skill in inputSkillOptions(formEventEditor.source_kit_id)" :key="`src-skill-${skill}`" :value="skill">{{ skill }}</option>
            </select>
          </div>
          <div class="grid gap-2 sm:grid-cols-3">
            <select v-model="formEventEditor.operator" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon">
              <option value=">">&gt;</option>
              <option value=">=">&gt;=</option>
              <option value="<">&lt;</option>
              <option value="<=">&lt;=</option>
              <option value="==">==</option>
              <option value="!=">!=</option>
            </select>
            <input v-model.number="formEventEditor.threshold" type="number" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="阈值" />
            <input v-model.number="formEventEditor.cooldown_ms" type="number" min="100" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="冷却(ms)" />
          </div>
          <div class="grid gap-2 sm:grid-cols-2">
            <select v-model="formEventEditor.target_kit_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="ensureSkillSelections">
              <option disabled value="">Target KIT（结果设备）</option>
              <option v-for="item in kits" :key="`dst-${item.kit_id}`" :value="item.kit_id">{{ item.display_name }} ({{ item.kit_id }})</option>
            </select>
            <select v-model="formEventEditor.target_skill" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="ensureSkillSelections">
              <option disabled value="">Output SKILL（结果）</option>
              <option v-for="skill in outputSkillOptions(formEventEditor.target_kit_id)" :key="`dst-skill-${skill}`" :value="skill">{{ skill }}</option>
            </select>
          </div>
          <div class="grid gap-2 sm:grid-cols-3">
            <select v-model="formEventEditor.action" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="ensureSkillSelections">
              <option v-for="action in formActionOptions" :key="`form-action-${action}`" :value="action">{{ action }}</option>
            </select>
            <div
              v-if="formActionFields.length"
              class="grid gap-2 sm:col-span-2 sm:grid-cols-2"
            >
              <div v-for="field in formActionFields" :key="`form-field-${field.key}`" class="grid gap-1">
                <label class="text-[11px] text-slate-300">{{ field.label || field.key }}</label>
                <input
                  v-if="field.type === 'number'"
                  v-model.number="formActionPayload[field.key]"
                  type="number"
                  :min="field.min ?? undefined"
                  :max="field.max ?? undefined"
                  class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon"
                  :placeholder="field.placeholder || field.key"
                />
                <select
                  v-else-if="field.type === 'enum'"
                  v-model="formActionPayload[field.key]"
                  class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon"
                >
                  <option disabled value="">选择 {{ field.label || field.key }}</option>
                  <option v-for="item in field.options" :key="`form-opt-${field.key}-${item}`" :value="item">{{ item }}</option>
                </select>
                <label
                  v-else-if="field.type === 'boolean'"
                  class="flex items-center gap-2 rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm"
                >
                  <input type="checkbox" v-model="formActionPayload[field.key]" />
                  {{ field.label || field.key }}
                </label>
                <textarea
                  v-else-if="field.type === 'json'"
                  v-model="formActionPayload[field.key]"
                  rows="3"
                  class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-xs outline-none focus:border-magi-neon"
                  :placeholder="field.placeholder || 'JSON payload'"
                />
                <input
                  v-else
                  v-model="formActionPayload[field.key]"
                  type="text"
                  class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon"
                  :placeholder="field.placeholder || field.key"
                />
              </div>
            </div>
            <textarea
              v-else
              v-model="formActionPayloadRaw"
              rows="4"
              class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-xs outline-none focus:border-magi-neon sm:col-span-2"
              placeholder='自定义 Payload JSON，例如 {"value":1}'
            />
          </div>
          <label class="flex items-center gap-2 text-xs text-slate-300"><input v-model="formEventEditor.enabled" type="checkbox" /> 启用</label>
          <div class="flex flex-wrap gap-2">
            <button class="rounded-md border border-magi-neon/70 bg-magi-neon/15 px-3 py-2 text-sm text-magi-neon transition hover:bg-magi-neon/25 disabled:opacity-50" :disabled="busy.save_form_event || !formEventEditor.source_skill || !formEventEditor.target_skill" @click="saveFormEvent">
              {{ busy.save_form_event ? "SAVING..." : formEventEditor.event_id ? "更新 EVENT" : "创建 EVENT" }}
            </button>
            <button class="rounded-md border border-slate-500 px-3 py-2 text-sm text-slate-300 transition hover:border-slate-300" @click="clearFormEditor">清空</button>
          </div>
        </div>

        <div v-if="eventEditorTab === 'code'" class="grid gap-2">
          <h3 class="text-sm font-semibold text-magi-neon">代码 EVENT 编辑器</h3>
          <input v-model="codeEventEditor.name" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="事件名称" />
          <input v-model.number="codeEventEditor.cooldown_ms" type="number" min="100" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="冷却(ms)" />
          <label class="flex items-center gap-2 text-xs text-slate-300"><input v-model="codeEventEditor.enabled" type="checkbox" /> 启用</label>
          <div class="rounded-xl border border-slate-700 bg-slate-950/40 p-3">
            <p class="mb-2 text-xs text-slate-300">SKILL 方法查看工具</p>
            <div class="grid gap-2 sm:grid-cols-2">
              <select v-model="codeSkillTool.kit_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="codeSkillTool.skill_id = ''">
                <option disabled value="">选择 KIT</option>
                <option v-for="item in kits" :key="`tool-kit-${item.kit_id}`" :value="item.kit_id">{{ item.display_name }} ({{ item.kit_id }})</option>
              </select>
              <select v-model="codeSkillTool.skill_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon">
                <option disabled value="">选择 SKILL</option>
                <option v-for="skill in codeToolSkills" :key="`tool-skill-${codeSkillTool.kit_id}-${skill.skill_id}`" :value="skill.skill_id">
                  {{ skill.skill_id }} / {{ (skill.io_type || '--').toUpperCase() }}
                </option>
              </select>
            </div>
            <pre class="mt-2 overflow-x-auto rounded-md border border-slate-700 bg-slate-950/80 p-2 text-[11px] text-slate-200">{{ codeToolUsage }}</pre>
            <button class="mt-2 rounded border border-blue-400/70 bg-blue-500/20 px-2 py-1 text-xs text-blue-100 transition hover:bg-blue-500/30" @click="insertSkillUsageSnippet">
              插入示例到代码编辑框
            </button>
          </div>

          <textarea v-model="codeEventEditor.code" rows="18" class="w-full rounded-md border border-slate-600 bg-slate-950/90 px-3 py-2 text-xs leading-relaxed text-slate-100 outline-none focus:border-magi-neon" placeholder="def evaluate(ctx): ..." />
          <div class="flex flex-wrap gap-2">
            <button class="rounded-md border border-sky-300/70 bg-sky-500/20 px-3 py-2 text-sm text-sky-100 transition hover:bg-sky-500/30 disabled:opacity-50" :disabled="busy.test_code || !codeEventEditor.code.trim()" @click="testCodeEvent">
              {{ busy.test_code ? "TESTING..." : "测试代码（本地编译）" }}
            </button>
            <button class="rounded-md border border-magi-neon/70 bg-magi-neon/15 px-3 py-2 text-sm text-magi-neon transition hover:bg-magi-neon/25 disabled:opacity-50" :disabled="busy.save_code_event || !codeEventEditor.code.trim()" @click="saveCodeEvent">
              {{ busy.save_code_event ? "SUBMITTING..." : codeEventEditor.event_id ? "更新并提交编译 EVENT" : "提交编译 EVENT" }}
            </button>
            <button class="rounded-md border border-slate-500 px-3 py-2 text-sm text-slate-300 transition hover:border-slate-300" @click="clearCodeEditor">清空</button>
          </div>
        </div>

        <div v-if="eventEditorTab === 'templates'" class="space-y-2">
          <h3 class="text-sm font-semibold text-magi-neon">内置 EVENT 模板</h3>
          <div v-for="item in eventTemplates" :key="item.template_id" class="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
            <p class="text-sm text-slate-100">{{ item.name }} ({{ item.mode }})</p>
            <p class="mt-1 text-xs text-slate-400">{{ item.description }}</p>
            <button class="mt-2 rounded border border-blue-400/70 bg-blue-500/20 px-2 py-1 text-xs text-blue-100 transition hover:bg-blue-500/30" @click="applyTemplate(item)">套用模板</button>
          </div>
          <p v-if="!eventTemplates.length" class="text-xs text-slate-500">暂无模板</p>
        </div>
      </article>

      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-4">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">EVENT 列表</h2>
        <div class="mt-3 space-y-3">
          <div v-for="item in events" :key="item.event_id" class="rounded-xl border p-3" :class="eventClass(item.status)">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <p class="text-sm">{{ item.name }}</p>
              <span class="rounded-full border border-current/40 px-2 py-0.5 text-[11px]">{{ item.mode }} / {{ item.status }}</span>
            </div>
            <p class="mt-1 text-[11px] text-slate-200" v-if="item.mode === 'form'">
              IF {{ item.condition?.source_kit_id }}/{{ item.condition?.source_skill }}
              {{ item.condition?.operator }} {{ item.condition?.threshold }}
            </p>
            <p class="mt-1 text-[11px] text-slate-200" v-if="item.mode === 'code'">
              Code Skills:
              {{ (item.required_skills ?? []).map((ref) => `${ref.kit_id}/${ref.skill_id}`).join(" · ") || "--" }}
            </p>
            <p class="text-[11px] text-slate-200" v-if="item.action">
              Action: {{ item.action.target_kit_id }}/{{ item.action.target_skill }}/{{ item.action.action }}
            </p>
            <p v-if="item.lock_reason" class="mt-1 text-[11px] text-rose-200">{{ item.lock_reason }}</p>
            <p class="mt-1 text-[11px] text-slate-300">Last Trigger: {{ friendlyTime(item.last_triggered_at) }}</p>
            <div class="mt-2 flex flex-wrap gap-2">
              <button class="rounded border border-blue-300/60 bg-blue-500/20 px-2 py-1 text-[11px] text-blue-100" @click="loadEventToEditor(item)">编辑</button>
              <button v-if="canToggleEvent(item)" class="rounded border border-emerald-300/60 bg-emerald-500/20 px-2 py-1 text-[11px] text-emerald-100 disabled:opacity-50" :disabled="busy.toggle_event === item.event_id" @click="toggleEvent(item, !item.enabled)">{{ item.enabled ? "停用" : "启用" }}</button>
              <span v-else class="rounded border border-slate-500/60 bg-slate-700/20 px-2 py-1 text-[11px] text-slate-300">仅可修改/删除</span>
              <button class="rounded border border-rose-300/60 bg-rose-500/20 px-2 py-1 text-[11px] text-rose-100 disabled:opacity-50" :disabled="busy.delete_event === item.event_id" @click="removeEvent(item)">删除</button>
            </div>
          </div>
          <p v-if="!events.length" class="text-xs text-slate-500">暂无 EVENT</p>
        </div>
      </article>
    </section>

    <section v-if="activeTab === 'skills'" class="mx-auto grid max-w-[1680px] gap-4 xl:grid-cols-12">
      <article class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-12">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">完整 SKILL 清单</h2>
        <p class="mt-1 text-xs text-slate-400">表单模式仅能选此处已有 SKILL；代码模式建议直接复用此清单。</p>
        <div class="mt-3 overflow-x-auto">
          <table class="w-full min-w-[1120px] text-left text-xs">
            <thead>
              <tr class="border-b border-slate-700 text-slate-300">
                <th class="py-2">KIT</th>
                <th class="py-2">KIT 名称</th>
                <th class="py-2">状态</th>
                <th class="py-2">SKILL</th>
                <th class="py-2">I/O</th>
                <th class="py-2">ACTION</th>
                <th class="py-2">DURATION</th>
                <th class="py-2">最近值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in skillFlat" :key="`${item.kit_id}-${item.skill_id}`" class="border-b border-slate-800/80 text-slate-100">
                <td class="py-2">{{ item.kit_id }}</td>
                <td class="py-2">{{ item.kit_name }}</td>
                <td class="py-2">{{ item.status }}</td>
                <td class="py-2">{{ item.skill_id }}</td>
                <td class="py-2">{{ (item.io_type || "--").toUpperCase() }}</td>
                <td class="py-2">{{ (item.actions || []).join(" / ") || "--" }}</td>
                <td class="py-2">{{ item.supports_duration ? "YES" : "NO" }}</td>
                <td class="py-2">{{ item.last_value ?? "--" }}</td>
              </tr>
              <tr v-if="!skillFlat.length">
                <td colspan="8" class="py-3 text-slate-500">暂无 SKILL 数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </section>

    <footer class="mx-auto mt-4 max-w-[1680px] rounded-xl border border-magi-line bg-slate-950/50 px-4 py-3 text-xs">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-slate-300">任务通知</p>
        <button
          class="rounded border border-slate-500 px-2 py-1 text-[11px] text-slate-300 transition hover:border-slate-300"
          :disabled="!noticeFeed.length"
          @click="clearNoticeFeed"
        >
          清空通知
        </button>
      </div>
      <div class="mt-2 max-h-48 space-y-1 overflow-y-auto">
        <p v-if="!noticeFeed.length" class="text-slate-500">暂无通知</p>
        <p
          v-for="item in noticeFeed"
          :key="item.id"
          :class="item.level === 'error' ? 'text-rose-200' : 'text-emerald-200'"
        >
          [{{ friendlyTime(item.at) }}] {{ item.message }}
        </p>
      </div>
      <p class="mt-2 text-slate-500">
        Revision {{ snapshot.revision }} · {{ friendlyTime(new Date().toISOString()) }}
      </p>
    </footer>
  </main>
</template>
