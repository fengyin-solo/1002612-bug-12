<template>
  <section class="page" data-module="marshalling">
    <header class="page-head">
      <div>
        <h2>引导入位管理</h2>
        <p class="page-desc">维护引导任务，围绕引导编号、对应航班、机位编号、引导车编号做登记、筛选与状态流转。</p>
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

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
        <template v-for="row in rows" :key="String(row.id)">
          <tr>
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button
                v-for="action in actionsFor(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
              <span v-if="!actionsFor(row).length">—</span>
            </td>
          </tr>
          <tr v-if="row.queueError">
            <td :colspan="columns.length + 1" class="error-text">
              {{ row.queueError }}
              <button class="link" type="button" @click="retryAction(row)">重试</button>
            </td>
          </tr>
        </template>
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
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null> & {
  id: number
  queueError?: string
  lastAction?: string
  lastReason?: string
}

const ENDPOINT = '/api/marshalling'
const columns = ["引导编号", "对应航班", "机位编号", "引导车编号", "引导员", "预计到位", "实际到位", "引导状态"]
// 每个状态允许执行的动作；已到位、已取消是终态，不再出现动作入口
const STATUS_ACTIONS: Record<string, string[]> = {
  待下达: ['下达引导', '取消引导'],
  已下达: ['确认到位', '取消引导'],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 看板卡片跟着队列一起重算：在途引导单数就是队列里已下达的张数
const stats = computed(() => [
  { label: '待下达引导单', value: rows.value.filter((row) => row.status === '待下达').length },
  { label: '在途引导单', value: rows.value.filter((row) => row.status === '已下达').length },
  { label: '已到位引导单', value: rows.value.filter((row) => row.status === '已到位').length },
])

function actionsFor(row: Row): string[] {
  return STATUS_ACTIONS[String(row.status)] ?? []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '引导任务登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row, reason = '') {
  errorMessage.value = ''
  row.queueError = ''
  let cancelReason = reason
  if (action === '取消引导' && !cancelReason) {
    const input = window.prompt(`请填写引导单 ${row['引导编号'] ?? row.id} 的取消原因`)
    if (input === null) {
      return
    }
    cancelReason = input.trim()
    if (!cancelReason) {
      errorMessage.value = '取消引导必须填写取消原因'
      return
    }
  }
  row.lastAction = action
  row.lastReason = cancelReason
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, 取消原因: cancelReason } }),
    })
    if (!response.ok) {
      throw new Error(`接口返回 ${response.status}`)
    }
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '引导入位动作未生效'
      return
    }
    if (payload.entry) {
      Object.assign(row, payload.entry, { queueError: '', lastAction: '', lastReason: '' })
    }
    await reload()
  } catch (error) {
    const detail = error instanceof Error ? error.message : '服务无响应'
    row.queueError = `动作「${action}」未生效：${detail}，可点击重试`
  }
}

function retryAction(row: Row) {
  if (row.lastAction) {
    void runAction(row.lastAction, row, row.lastReason ?? '')
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
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

onMounted(reload)
</script>
