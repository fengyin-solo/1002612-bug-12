<template>
  <section class="page" data-module="marshalling">
    <header class="page-head">
      <div>
        <h2>引导入位管理</h2>
        <p class="page-desc">引导单按待下达、已下达、已到位、已取消流转；每次流转落库后同步刷新队列面板与看板计数。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记引导任务</button>
        <button class="btn" type="button" @click="exportRows">导出引导入位清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="refresh">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>引导状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td>
            <div class="row-actions">
              <button
                v-for="action in availableActions(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
              <span v-if="!availableActions(row).length && !rowErrors[rowKey(row)]">—</span>
            </div>
            <div v-if="rowErrors[rowKey(row)]" class="row-error">
              <span class="error-text">{{ rowErrors[rowKey(row)].message }}</span>
              <button class="link" type="button" @click="retryAction(row)">重试</button>
            </div>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无引导入位数据，可先登记引导任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条引导入位记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type RowError = { message: string; action: string; values: Record<string, unknown> }

const ENDPOINT = '/api/marshalling'
const columns = ["引导编号", "对应航班", "机位编号", "引导车编号", "引导员", "预计到位", "实际到位", "引导状态", "取消原因"]
const statuses = ["待下达", "已下达", "已到位", "已取消"]
// 每个状态只放行状态机允许的动作，已到位、已取消是终态
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  '待下达': ['下达引导', '取消引导'],
  '已下达': ['确认到位', '取消引导'],
  '已到位': [],
  '已取消': [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const statusFilter = ref('')
const stats = ref([
  { label: '待下达', value: 0 },
  { label: '在途引导（已下达）', value: 0 },
  { label: '已到位', value: 0 },
  { label: '已取消', value: 0 },
])
// 服务端没响应或被拦下的动作：原因写在队列行上，并保留原始请求用于重试
const rowErrors = reactive<Record<string, RowError>>({})

function rowKey(row: Row) {
  return String(row.id)
}

function availableActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row['引导状态'] ?? '')] ?? []
}

function resetFilters() {
  filters.value = {}
  statusFilter.value = ''
  void refresh()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '引导任务登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row, presetValues?: Record<string, unknown>) {
  const key = rowKey(row)
  delete rowErrors[key]
  errorMessage.value = ''
  const values: Record<string, unknown> = { action, ...(presetValues ?? {}) }
  if (action === '取消引导' && !values['取消原因']) {
    const reason = window.prompt(`取消引导任务 ${row['引导编号'] ?? row.id}，请填写取消原因`)
    if (reason === null) {
      return
    }
    if (!reason.trim()) {
      rowErrors[key] = { message: '取消引导必须填写取消原因', action, values }
      return
    }
    values['取消原因'] = reason.trim()
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? payload?.detail ?? `接口返回 ${response.status}，动作未生效`)
    }
    applyEntry(payload.entry as Row | null)
    await refresh()
  } catch (error) {
    rowErrors[key] = {
      message: error instanceof Error ? error.message : '引导入位操作失败',
      action,
      values,
    }
  }
}

function retryAction(row: Row) {
  const failed = rowErrors[rowKey(row)]
  if (failed) {
    void runAction(failed.action, row, failed.values)
  }
}

function applyEntry(entry: Row | null) {
  if (!entry || entry.id == null) {
    return
  }
  const index = rows.value.findIndex((row) => String(row.id) === String(entry.id))
  if (index >= 0) {
    rows.value.splice(index, 1, entry)
  }
}

async function refresh() {
  await Promise.all([reload(), loadStats()])
}

async function loadStats() {
  try {
    const payload = await fetchJson<Record<string, number>>(`${ENDPOINT}/stats`)
    stats.value = [
      { label: '待下达', value: payload['待下达'] ?? 0 },
      { label: '在途引导（已下达）', value: payload['在途引导'] ?? 0 },
      { label: '已到位', value: payload['已到位'] ?? 0 },
      { label: '已取消', value: payload['已取消'] ?? 0 },
    ]
  } catch {
    // 看板计数读取失败时保留旧值，等下一次流转后重算
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value['引导编号']) query.set('keyword', filters.value['引导编号'])
  if (filters.value['对应航班']) query.set('flight', filters.value['对应航班'])
  if (filters.value['机位编号']) query.set('stand', filters.value['机位编号'])
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('引导任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '引导入位列表读取失败'
  }
}

onMounted(refresh)
</script>

<style scoped>
.row-error {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 4px;
  font-size: 12px;
}
</style>
