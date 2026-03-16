<template>
  <div class="thesis-page">
    <div class="page-header">
      <div>
        <h1>InvestMind Thesis</h1>
        <p>管理 Thesis、观察池和历史导入。</p>
      </div>
      <div class="actions">
        <el-button @click="loadAll">刷新</el-button>
        <el-button type="primary" @click="generateEdge">生成 Edge</el-button>
      </div>
    </div>

    <el-row :gutter="16" class="overview-grid">
      <el-col :span="6"><el-card shadow="never"><div class="metric"><span>激活</span><strong>{{ overview?.active_count || 0 }}</strong></div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="metric"><span>观察池</span><strong>{{ overview?.watchlist_count || 0 }}</strong></div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="metric"><span>已关闭</span><strong>{{ overview?.closed_count || 0 }}</strong></div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="metric"><span>破裂</span><strong>{{ overview?.broken_count || 0 }}</strong></div></el-card></el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="16">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>Thesis 列表</span>
              <el-input v-model="keyword" placeholder="筛选代码或标题" clearable style="width: 240px" />
            </div>
          </template>
          <el-table :data="filteredItems" v-loading="loading">
            <el-table-column prop="symbol" label="代码" width="120" />
            <el-table-column prop="thesis_title" label="标题" min-width="220" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'active' ? 'success' : row.status === 'closed' ? 'info' : 'warning'">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="健康度" width="120">
              <template #default="{ row }">
                <span>{{ Number(row.health_score || 0).toFixed(2) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="watch_reason" label="观察原因" min-width="180" />
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="viewVersions(row)">版本</el-button>
                <el-button v-if="row.status !== 'active'" link type="success" @click="activate(row)">激活</el-button>
                <el-button v-if="row.status !== 'closed'" link type="danger" @click="closeThesis(row)">关闭</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card shadow="never">
          <template #header><span>历史交易导入</span></template>
          <el-upload :auto-upload="false" :show-file-list="false" accept=".csv" :on-change="handleFileChange">
            <el-button type="primary">选择 CSV</el-button>
          </el-upload>
          <div class="import-meta" v-if="preview">
            <p>识别列: {{ preview.columns.join(', ') }}</p>
            <p>总行数: {{ preview.row_count }}</p>
            <p>代码列: {{ preview.detected_symbol_field || '-' }}</p>
            <p>方向列: {{ preview.detected_side_field || '-' }}</p>
            <el-button type="success" @click="commitImport" :disabled="!preview.sample_rows.length">确认导入</el-button>
          </div>
          <el-table v-if="preview?.sample_rows?.length" :data="preview.sample_rows" size="small" style="margin-top: 12px">
            <el-table-column v-for="column in preview.columns.slice(0, 4)" :key="column" :prop="column" :label="column" />
          </el-table>
        </el-card>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header><span>最近版本</span></template>
          <div v-if="versions.length === 0" class="empty">选择一条 Thesis 查看版本</div>
          <div v-else class="version-list">
            <div v-for="item in versions.slice(0, 6)" :key="item._id" class="version-item">
              <div>{{ item.change_description }}</div>
              <small>{{ item.created_at }}</small>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import { thesesApi, type ThesisItem, type ThesisOverview, type TradeImportPreview } from '@/api/theses'

const route = useRoute()
const loading = ref(false)
const keyword = ref('')
const items = ref<ThesisItem[]>([])
const overview = ref<ThesisOverview | null>(null)
const versions = ref<any[]>([])
const preview = ref<TradeImportPreview | null>(null)
const currentThesisId = ref('')

const filteredItems = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return items.value
  return items.value.filter(item =>
    [item.symbol, item.thesis_title, item.thesis_summary].some(value => String(value || '').toLowerCase().includes(text))
  )
})

async function loadAll() {
  try {
    loading.value = true
    const [listRes, overviewRes] = await Promise.all([thesesApi.list(), thesesApi.overview()])
    if (listRes.success) items.value = listRes.data || []
    if (overviewRes.success) overview.value = overviewRes.data || null
  } catch (error: any) {
    ElMessage.error(error?.message || '加载 Thesis 失败')
  } finally {
    loading.value = false
  }
}

async function viewVersions(row: ThesisItem) {
  currentThesisId.value = row._id
  const res = await thesesApi.versions(row._id)
  if (res.success) versions.value = res.data || []
}

async function activate(row: ThesisItem) {
  const res = await thesesApi.activate(row._id)
  if (res.success) {
    ElMessage.success('已激活')
    await loadAll()
  }
}

async function closeThesis(row: ThesisItem) {
  const reason = await ElMessageBox.prompt('请输入关闭原因', '关闭 Thesis', {
    inputValue: 'manual_exit'
  }).catch(() => null)
  if (!reason?.value) return
  const res = await thesesApi.close(row._id, { reason: reason.value })
  if (res.success) {
    ElMessage.success('已关闭')
    await loadAll()
  }
}

async function generateEdge() {
  const res = await thesesApi.generateEdgeProfile()
  if (res.success) {
    ElMessage.success('Edge Discovery 已生成')
  }
}

async function handleFileChange(file: any) {
  if (!file?.raw) return
  const res = await thesesApi.previewTradeImport(file.raw)
  if (res.success) preview.value = res.data || null
}

async function commitImport() {
  if (!preview.value) return
  const rows = preview.value.rows || []
  const res = await thesesApi.commitTradeImport(rows)
  if (res.success) {
    ElMessage.success(`已导入 ${res.data.inserted_count} 条样例记录`)
    preview.value = null
    await loadAll()
  }
}

async function hydrateRouteSelection() {
  const thesisId = typeof route.query.thesisId === 'string' ? route.query.thesisId : ''
  if (!thesisId) return

  const res = await thesesApi.get(thesisId)
  if (res.success && res.data) {
    currentThesisId.value = res.data._id
    keyword.value = res.data.symbol || res.data.thesis_title || ''
    await viewVersions(res.data)
  }
}

onMounted(async () => {
  await loadAll()
  await hydrateRouteSelection()
})
</script>

<style scoped>
.thesis-page { padding: 16px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h1 { margin: 0; font-size: 24px; }
.page-header p { margin: 6px 0 0; color: var(--el-text-color-secondary); }
.actions { display: flex; gap: 12px; }
.overview-grid { margin-bottom: 16px; }
.metric { display: flex; justify-content: space-between; align-items: center; }
.metric strong { font-size: 28px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.import-meta p { margin: 10px 0; color: var(--el-text-color-regular); }
.version-list { display: flex; flex-direction: column; gap: 10px; }
.version-item { padding: 10px 12px; background: var(--el-fill-color-light); border-radius: 8px; }
.empty { color: var(--el-text-color-secondary); }
</style>
