<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";

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
  toggle_event: "",
  delete_event: ""
});

const namesForm = reactive({
  pool_name: "",
  gate_name: ""
});

const setupJoinForm = reactive({
  pool_id: "",
  pool_name: ""
});

const setupCreateForm = reactive({
  pool_id: "POOL_NEW",
  pool_name: "New_Pool"
});
const setupStep = ref(1);
const setupMode = ref("join");
const setupGateName = ref("MAGI-01");

const pendingInput = reactive({});
const kitNameInput = reactive({});

const displayForm = reactive({
  kit_id: "",
  msg: "WARN",
  duration: 5000
});

const formEventEditor = reactive({
  event_id: "",
  name: "TEMP_ALERT",
  enabled: true,
  cooldown_ms: 1500,
  source_kit_id: "",
  source_skill: "",
  operator: ">",
  threshold: 30,
  target_kit_id: "",
  target_skill: "",
  message: "ALERT",
  duration: 5000
});

const codeEventEditor = reactive({
  event_id: "",
  name: "CODE_EVENT",
  enabled: true,
  cooldown_ms: 1500,
  code: "",
  required_keys: [],
  fallback_enabled: true,
  target_kit_id: "",
  target_skill: "",
  message: "CODE ALERT",
  duration: 5000
});

const eventTemplates = ref([]);
const codeFramework = ref("");

const lifecycleClasses = {
  NEW: "border-emerald-400/80 bg-emerald-500/10 text-emerald-200 animate-pulse",
  WORKING: "border-amber-300/80 bg-amber-400/10 text-amber-100 animate-pulse",
  DYING: "border-rose-400/80 bg-rose-500/10 text-rose-200 animate-pulse",
  IDLE: "border-blue-400/70 bg-blue-500/10 text-blue-100"
};

const eventClasses = {
  LOCKED: "border-amber-400/70 bg-amber-500/10 text-amber-100",
  WORKING: "border-blue-400/70 bg-blue-500/10 text-blue-100",
  ERROR: "border-rose-500/80 bg-rose-500/10 text-rose-100",
  IDLE: "border-slate-500/70 bg-slate-500/10 text-slate-200"
};

let eventSource = null;
let pollTimer = null;

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
const onlineKits = computed(() => kits.value.filter((item) => item.status === "ONLINE"));

const skillsByKit = computed(() => {
  const map = {};
  for (const group of skillGrouped.value) {
    map[group.kit_id] = (group.skills ?? []).map((item) => item.skill_id);
  }
  return map;
});

function lifecycleClass(state) {
  return lifecycleClasses[state] ?? lifecycleClasses.IDLE;
}

function eventClass(state) {
  return eventClasses[state] ?? eventClasses.IDLE;
}

function skillOptions(kitId) {
  if (!kitId) return [];
  return skillsByKit.value[kitId] ?? [];
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
  const sourceOptions = skillOptions(formEventEditor.source_kit_id);
  if (sourceOptions.length && !sourceOptions.includes(formEventEditor.source_skill)) {
    formEventEditor.source_skill = sourceOptions[0];
  }
  if (!sourceOptions.length) formEventEditor.source_skill = "";

  const targetOptions = skillOptions(formEventEditor.target_kit_id);
  if (targetOptions.length && !targetOptions.includes(formEventEditor.target_skill)) {
    formEventEditor.target_skill = targetOptions[0];
  }
  if (!targetOptions.length) formEventEditor.target_skill = "";

  const codeTargetOptions = skillOptions(codeEventEditor.target_kit_id);
  if (
    codeTargetOptions.length &&
    !codeTargetOptions.includes(codeEventEditor.target_skill)
  ) {
    codeEventEditor.target_skill = codeTargetOptions[0];
  }
  if (!codeTargetOptions.length) codeEventEditor.target_skill = "";
}

function syncFormsFromSnapshot(data) {
  snapshot.value = data;
  if (!namesDirty.value) {
    namesForm.pool_name = data.profile?.pool_name ?? namesForm.pool_name;
    namesForm.gate_name = data.profile?.gate_name ?? namesForm.gate_name;
  }

  if (!setupJoinForm.pool_id) {
    setupJoinForm.pool_id = data.profile?.pool_id ?? "POOL_ZC";
    setupJoinForm.pool_name = data.profile?.pool_name ?? "ZeroCloud_Main_Pool";
  }
  if (!setupGateName.value) {
    setupGateName.value = data.profile?.gate_name ?? "MAGI-01";
  }

  if (!displayForm.kit_id && data.kits?.length) {
    displayForm.kit_id = data.kits[0].kit_id;
  }
  if (!formEventEditor.source_kit_id && data.kits?.length) {
    formEventEditor.source_kit_id = data.kits[0].kit_id;
  }
  if (!formEventEditor.target_kit_id && data.kits?.length) {
    formEventEditor.target_kit_id = data.kits[0].kit_id;
  }
  if (!codeEventEditor.target_kit_id && data.kits?.length) {
    codeEventEditor.target_kit_id = data.kits[0].kit_id;
  }

  for (const item of data.kits ?? []) {
    if (!kitNameInput[item.kit_id]) {
      kitNameInput[item.kit_id] = item.display_name;
    }
  }

  if (!data.profile?.configured) {
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
    codeFramework.value = framework.code || "";
    if (!codeEventEditor.code) {
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
  setupJoinForm.pool_id = item.pool_id;
  setupJoinForm.pool_name = item.pool_name || item.pool_id;
}

function beginSetup(mode) {
  if (mode === "join" && !setupJoinForm.pool_id.trim()) {
    errorText.value = "请先选择或填写要加入的 POOL。";
    return;
  }
  if (mode === "create" && !setupCreateForm.pool_id.trim()) {
    errorText.value = "请先填写新 POOL_ID。";
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
    const poolPayload =
      setupMode.value === "join"
        ? {
            pool_id: setupJoinForm.pool_id,
            pool_name: setupJoinForm.pool_name
          }
        : {
            pool_id: setupCreateForm.pool_id,
            pool_name: setupCreateForm.pool_name
          };
    await apiRequest(endpoint, {
      method: "POST",
      body: JSON.stringify({
        ...poolPayload,
        gate_id: snapshot.value.profile?.gate_id || "GATE_01",
        gate_name: setupGateName.value
      })
    });
    notice.value =
      setupMode.value === "join"
        ? `已绑定到 POOL ${setupJoinForm.pool_id}`
        : `已创建并绑定 POOL ${setupCreateForm.pool_id}`;
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
  if (!displayForm.kit_id) return;
  busy.display_send = true;
  notice.value = "";
  errorText.value = "";
  try {
    await apiRequest(`/api/v1/kits/${displayForm.kit_id}/display`, {
      method: "POST",
      body: JSON.stringify({
        msg: displayForm.msg,
        duration: Number(displayForm.duration)
      })
    });
    notice.value = `显示指令已下发到 ${displayForm.kit_id}`;
  } catch (err) {
    errorText.value = `显示指令失败: ${err.message}`;
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
  formEventEditor.name = "TEMP_ALERT";
  formEventEditor.enabled = true;
  formEventEditor.cooldown_ms = 1500;
  formEventEditor.operator = ">";
  formEventEditor.threshold = 30;
  formEventEditor.message = "ALERT";
  formEventEditor.duration = 5000;
  if (kits.value.length) {
    formEventEditor.source_kit_id = kits.value[0].kit_id;
    formEventEditor.target_kit_id = kits.value[0].kit_id;
  }
  ensureSkillSelections();
}

function clearCodeEditor() {
  codeEventEditor.event_id = "";
  codeEventEditor.name = "CODE_EVENT";
  codeEventEditor.enabled = true;
  codeEventEditor.cooldown_ms = 1500;
  codeEventEditor.required_keys = [];
  codeEventEditor.fallback_enabled = true;
  if (kits.value.length) {
    codeEventEditor.target_kit_id = kits.value[0].kit_id;
  }
  ensureSkillSelections();
  codeEventEditor.message = "CODE ALERT";
  codeEventEditor.duration = 5000;
  codeEventEditor.code = codeFramework.value || codeEventEditor.code;
}

function formEventPayload() {
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
      action: "SET",
      payload: {
        msg: formEventEditor.message,
        duration: Number(formEventEditor.duration)
      }
    },
    required_skills: [],
    code: ""
  };
}

function codeEventPayload() {
  const required = codeEventEditor.required_keys.map((key) => {
    const [kit_id, skill_id] = key.split("/");
    return { kit_id, skill_id };
  });

  const action = codeEventEditor.fallback_enabled
    ? {
        target_kit_id: codeEventEditor.target_kit_id,
        target_skill: codeEventEditor.target_skill,
        action: "SET",
        payload: {
          msg: codeEventEditor.message,
          duration: Number(codeEventEditor.duration)
        }
      }
    : null;

  return {
    name: codeEventEditor.name,
    mode: "code",
    enabled: codeEventEditor.enabled,
    cooldown_ms: Number(codeEventEditor.cooldown_ms),
    condition: null,
    action,
    required_skills: required,
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

async function toggleEvent(item, enabled) {
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
    formEventEditor.message = item.action?.payload?.msg ?? "ALERT";
    formEventEditor.duration = item.action?.payload?.duration ?? 5000;
    ensureSkillSelections();
    return;
  }

  eventEditorTab.value = "code";
  codeEventEditor.event_id = item.event_id;
  codeEventEditor.name = item.name;
  codeEventEditor.enabled = item.enabled;
  codeEventEditor.cooldown_ms = item.cooldown_ms;
  codeEventEditor.code = item.code || codeFramework.value;
  codeEventEditor.required_keys = (item.required_skills ?? []).map(
    (ref) => `${ref.kit_id}/${ref.skill_id}`
  );
  if (item.action) {
    codeEventEditor.fallback_enabled = true;
    codeEventEditor.target_kit_id = item.action.target_kit_id;
    codeEventEditor.target_skill = item.action.target_skill;
    codeEventEditor.message = item.action.payload?.msg ?? "CODE ALERT";
    codeEventEditor.duration = item.action.payload?.duration ?? 5000;
  } else {
    codeEventEditor.fallback_enabled = false;
  }
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
    formEventEditor.message = template.payload?.action?.payload?.msg ?? "ALERT";
    formEventEditor.duration = template.payload?.action?.payload?.duration ?? 5000;
    ensureSkillSelections();
    return;
  }

  eventEditorTab.value = "code";
  codeEventEditor.event_id = "";
  codeEventEditor.name = template.name;
  codeEventEditor.cooldown_ms = template.payload?.cooldown_ms ?? 1500;
  codeEventEditor.code = template.payload?.code || codeFramework.value;
  codeEventEditor.required_keys = (template.payload?.required_skills ?? []).map(
    (ref) => `${ref.kit_id}/${ref.skill_id}`
  );
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
  <main class="min-h-screen px-4 py-5 md:px-6">
    <header class="mx-auto mb-4 max-w-[1680px] rounded-2xl border border-magi-line bg-magi-panel/90 p-4 shadow-neon">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 class="text-2xl font-semibold tracking-wide text-magi-neon">
            🛰️ ZeroCloud · MAGI Control Console
          </h1>
          <p class="mt-1 text-sm text-slate-300">
            {{ snapshot.profile.pool_name }} ({{ snapshot.profile.pool_id }}) /
            {{ snapshot.profile.gate_name }} ({{ snapshot.profile.gate_id }})
          </p>
        </div>
        <div class="flex items-center gap-2 text-xs">
          <span
            class="rounded-full border px-3 py-1"
            :class="
              metrics.mqtt_connected
                ? 'border-emerald-400/70 bg-emerald-500/20 text-emerald-100'
                : 'border-rose-400/70 bg-rose-500/20 text-rose-100'
            "
          >
            MQTT {{ metrics.mqtt_connected ? "ONLINE" : "OFFLINE" }}
          </span>
          <span
            class="rounded-full border px-3 py-1"
            :class="
              streamConnected
                ? 'border-blue-400/70 bg-blue-500/20 text-blue-100'
                : 'border-amber-400/70 bg-amber-500/20 text-amber-100'
            "
          >
            {{ streamConnected ? "STREAM LIVE" : "POLLING MODE" }}
          </span>
        </div>
      </div>

      <div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-8">
        <div class="rounded-xl border border-magi-line bg-slate-900/40 p-3">
          <p class="text-xs text-slate-400">TPS</p>
          <p class="mt-1 text-xl text-magi-neon">{{ Number(metrics.frame_tps || 0).toFixed(1) }}</p>
        </div>
        <div class="rounded-xl border border-magi-line bg-slate-900/40 p-3">
          <p class="text-xs text-slate-400">POOL</p>
          <p class="mt-1 truncate text-base text-blue-100">
            {{ snapshot.profile.pool_name || snapshot.profile.pool_id }}
          </p>
        </div>
        <div class="rounded-xl border border-magi-line bg-slate-900/40 p-3">
          <p class="text-xs text-slate-400">KITS</p>
          <p class="mt-1 text-xl text-slate-100">{{ metrics.kits_total || 0 }}</p>
        </div>
        <div class="rounded-xl border border-magi-line bg-slate-900/40 p-3">
          <p class="text-xs text-slate-400">ONLINE</p>
          <p class="mt-1 text-xl text-magi-success">{{ metrics.kits_online || 0 }}</p>
        </div>
        <div class="rounded-xl border border-magi-line bg-slate-900/40 p-3">
          <p class="text-xs text-slate-400">PENDING</p>
          <p class="mt-1 text-xl text-magi-warn">{{ metrics.pending_total || 0 }}</p>
        </div>
        <div class="rounded-xl border border-magi-line bg-slate-900/40 p-3">
          <p class="text-xs text-slate-400">EVENTS</p>
          <p class="mt-1 text-xl text-slate-100">{{ metrics.events_total || 0 }}</p>
        </div>
        <div class="rounded-xl border border-magi-line bg-slate-900/40 p-3">
          <p class="text-xs text-slate-400">LOCKED</p>
          <p class="mt-1 text-xl text-amber-200">{{ metrics.events_locked || 0 }}</p>
        </div>
        <div class="rounded-xl border border-magi-line bg-slate-900/40 p-3">
          <p class="text-xs text-slate-400">ERROR</p>
          <p class="mt-1 text-xl text-rose-200">{{ metrics.events_error || 0 }}</p>
        </div>
      </div>
    </header>

    <nav class="mx-auto mb-4 flex max-w-[1680px] flex-wrap gap-2">
      <button
        v-for="item in visibleTabs"
        :key="item.id"
        class="rounded-lg border px-4 py-2 text-sm transition"
        :class="
          activeTab === item.id
            ? 'border-magi-neon bg-magi-neon/15 text-magi-neon'
            : 'border-slate-600 bg-slate-900/40 text-slate-300 hover:border-magi-neon/60'
        "
        @click="activeTab = item.id"
      >
        {{ item.label }}
      </button>
      <button
        class="rounded-lg border border-magi-neon/70 px-4 py-2 text-sm text-magi-neon transition hover:bg-magi-neon/10"
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
          <input v-model="setupJoinForm.pool_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="POOL_ID" />
          <input v-model="setupJoinForm.pool_name" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="POOL 名称" />
          <button class="rounded-md border border-emerald-400/70 bg-emerald-500/15 px-3 py-2 text-sm text-emerald-100 transition hover:bg-emerald-500/25" @click="beginSetup('join')">
            选择加入此 POOL
          </button>
        </div>
      </article>

      <article v-if="setupStep === 1" class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-6">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">Step 1 · 创建新 POOL</h2>
        <div class="mt-3 grid gap-2">
          <input v-model="setupCreateForm.pool_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="新 POOL_ID" />
          <input v-model="setupCreateForm.pool_name" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="新 POOL 名称" />
          <button class="rounded-md border border-blue-400/70 bg-blue-500/15 px-3 py-2 text-sm text-blue-100 transition hover:bg-blue-500/25" @click="beginSetup('create')">
            选择创建此 POOL
          </button>
        </div>
      </article>

      <article v-if="setupStep === 2" class="rounded-2xl border border-magi-line bg-magi-panel/90 p-4 xl:col-span-12">
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">Step 2 · 命名 GATE</h2>
        <div class="mt-3 max-w-xl grid gap-2">
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
        <h2 class="text-sm font-semibold tracking-wider text-magi-neon">C2 DISPLAY 接管</h2>
        <div class="mt-3 grid gap-2">
          <select v-model="displayForm.kit_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon">
            <option disabled value="">选择在线 KIT</option>
            <option v-for="item in onlineKits" :key="item.kit_id" :value="item.kit_id">
              {{ item.display_name }} ({{ item.kit_id }})
            </option>
          </select>
          <input v-model="displayForm.msg" maxlength="64" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="显示文本" />
          <input v-model.number="displayForm.duration" type="number" min="500" max="60000" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="持续时长(ms)" />
          <button class="rounded-md border border-emerald-400/70 bg-emerald-500/20 px-3 py-2 text-sm text-emerald-100 transition hover:bg-emerald-500/30 disabled:opacity-50" :disabled="!displayForm.kit_id || busy.display_send" @click="sendDisplay">
            {{ busy.display_send ? "SENDING..." : "发送 DISPLAY 指令" }}
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
              <button class="rounded border border-rose-400/70 bg-rose-500/15 px-2 py-1 text-[11px] text-rose-100 transition hover:bg-rose-500/25 disabled:opacity-50" :disabled="busy.delete_kit === item.kit_id || item.status === 'ONLINE'" @click="forceDeleteKit(item.kit_id)">
                {{ busy.delete_kit === item.kit_id ? "DELETING..." : "离线强制删除" }}
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
              <option disabled value="">Source KIT</option>
              <option v-for="item in kits" :key="`src-${item.kit_id}`" :value="item.kit_id">{{ item.display_name }} ({{ item.kit_id }})</option>
            </select>
            <select v-model="formEventEditor.source_skill" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon">
              <option disabled value="">Source SKILL</option>
              <option v-for="skill in skillOptions(formEventEditor.source_kit_id)" :key="`src-skill-${skill}`" :value="skill">{{ skill }}</option>
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
              <option disabled value="">Target KIT</option>
              <option v-for="item in kits" :key="`dst-${item.kit_id}`" :value="item.kit_id">{{ item.display_name }} ({{ item.kit_id }})</option>
            </select>
            <select v-model="formEventEditor.target_skill" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon">
              <option disabled value="">Target SKILL</option>
              <option v-for="skill in skillOptions(formEventEditor.target_kit_id)" :key="`dst-skill-${skill}`" :value="skill">{{ skill }}</option>
            </select>
          </div>
          <div class="grid gap-2 sm:grid-cols-2">
            <input v-model="formEventEditor.message" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="消息文本" />
            <input v-model.number="formEventEditor.duration" type="number" min="500" max="60000" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="持续时长(ms)" />
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
            <p class="mb-2 text-xs text-slate-300">依赖 SKILL（完整清单）</p>
            <div class="grid max-h-40 grid-cols-1 gap-1 overflow-y-auto sm:grid-cols-2">
              <label v-for="item in skillFlat" :key="`required-${item.kit_id}-${item.skill_id}`" class="flex items-center gap-2 rounded border border-slate-700 px-2 py-1 text-xs">
                <input type="checkbox" :value="`${item.kit_id}/${item.skill_id}`" v-model="codeEventEditor.required_keys" />
                <span>{{ item.kit_name }} / {{ item.skill_id }}</span>
              </label>
            </div>
          </div>

          <div class="rounded-xl border border-slate-700 bg-slate-950/40 p-3">
            <label class="mb-2 flex items-center gap-2 text-xs text-slate-300"><input v-model="codeEventEditor.fallback_enabled" type="checkbox" /> 使用默认动作（可选）</label>
            <div class="grid gap-2 sm:grid-cols-2" v-if="codeEventEditor.fallback_enabled">
              <select v-model="codeEventEditor.target_kit_id" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" @change="ensureSkillSelections">
                <option disabled value="">Target KIT</option>
                <option v-for="item in kits" :key="`code-target-${item.kit_id}`" :value="item.kit_id">{{ item.display_name }} ({{ item.kit_id }})</option>
              </select>
              <select v-model="codeEventEditor.target_skill" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon">
                <option disabled value="">Target SKILL</option>
                <option v-for="skill in skillOptions(codeEventEditor.target_kit_id)" :key="`code-target-skill-${skill}`" :value="skill">{{ skill }}</option>
              </select>
              <input v-model="codeEventEditor.message" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="消息文本" />
              <input v-model.number="codeEventEditor.duration" type="number" min="500" max="60000" class="rounded-md border border-slate-600 bg-slate-950/80 px-2 py-2 text-sm outline-none focus:border-magi-neon" placeholder="持续时长(ms)" />
            </div>
          </div>

          <textarea v-model="codeEventEditor.code" rows="15" class="w-full rounded-md border border-slate-600 bg-slate-950/90 px-3 py-2 text-xs leading-relaxed text-slate-100 outline-none focus:border-magi-neon" placeholder="def evaluate(ctx): ..." />
          <div class="flex flex-wrap gap-2">
            <button class="rounded-md border border-magi-neon/70 bg-magi-neon/15 px-3 py-2 text-sm text-magi-neon transition hover:bg-magi-neon/25 disabled:opacity-50" :disabled="busy.save_code_event || !codeEventEditor.code.trim()" @click="saveCodeEvent">
              {{ busy.save_code_event ? "SAVING..." : codeEventEditor.event_id ? "更新 EVENT" : "创建 EVENT" }}
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
              <button class="rounded border border-emerald-300/60 bg-emerald-500/20 px-2 py-1 text-[11px] text-emerald-100 disabled:opacity-50" :disabled="busy.toggle_event === item.event_id" @click="toggleEvent(item, !item.enabled)">{{ item.enabled ? "停用" : "启用" }}</button>
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
          <table class="w-full min-w-[960px] text-left text-xs">
            <thead>
              <tr class="border-b border-slate-700 text-slate-300">
                <th class="py-2">KIT</th>
                <th class="py-2">KIT 名称</th>
                <th class="py-2">状态</th>
                <th class="py-2">SKILL</th>
                <th class="py-2">最近值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in skillFlat" :key="`${item.kit_id}-${item.skill_id}`" class="border-b border-slate-800/80 text-slate-100">
                <td class="py-2">{{ item.kit_id }}</td>
                <td class="py-2">{{ item.kit_name }}</td>
                <td class="py-2">{{ item.status }}</td>
                <td class="py-2">{{ item.skill_id }}</td>
                <td class="py-2">{{ item.last_value ?? "--" }}</td>
              </tr>
              <tr v-if="!skillFlat.length">
                <td colspan="5" class="py-3 text-slate-500">暂无 SKILL 数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </section>

    <footer class="mx-auto mt-4 max-w-[1680px] space-y-1 rounded-xl border border-magi-line bg-slate-950/50 px-4 py-2 text-xs">
      <p v-if="notice" class="text-emerald-200">{{ notice }}</p>
      <p v-if="errorText" class="text-rose-200">{{ errorText }}</p>
      <p v-for="(message, key) in snapshot.runtime_errors" :key="key" class="text-amber-200">
        {{ key }}: {{ message }}
      </p>
      <p class="text-slate-500">
        Revision {{ snapshot.revision }} · {{ friendlyTime(new Date().toISOString()) }}
      </p>
    </footer>
  </main>
</template>
