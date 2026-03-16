<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Edge Discovery</h1>
        <p>基于已闭环交易与 Thesis 结果生成结构化边际画像。</p>
      </div>
      <el-button type="primary" @click="generate" :loading="loading">重新生成</el-button>
    </div>

    <el-table :data="items" v-loading="loading">
      <el-table-column prop="generated_at" label="生成时间" width="220" />
      <el-table-column prop="total_closed_trades" label="闭环交易数" width="120" />
      <el-table-column label="关键信息" min-width="320">
        <template #default="{ row }">
          <div v-for="finding in row.key_findings || []" :key="finding">{{ finding }}</div>
        </template>
      </el-table-column>
      <el-table-column label="信号权重" min-width="260">
        <template #default="{ row }">
          <div v-for="(value, key) in row.signal_weight_config || {}" :key="key">{{ key }}: {{ value }}</div>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { thesesApi, type EdgeProfile } from '@/api/theses'

const loading = ref(false)
const items = ref<EdgeProfile[]>([])

async function load() {
  try {
    loading.value = true
    const res = await thesesApi.listEdgeProfiles()
    if (res.success) items.value = res.data || []
  } catch (error: any) {
    ElMessage.error(error?.message || '加载 Edge Discovery 失败')
  } finally {
    loading.value = false
  }
}

async function generate() {
  const res = await thesesApi.generateEdgeProfile()
  if (res.success) {
    ElMessage.success('Edge Discovery 已生成')
    await load()
  }
}

onMounted(load)
</script>

<style scoped>
.page { padding: 16px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h1 { margin: 0; }
.page-header p { margin: 6px 0 0; color: var(--el-text-color-secondary); }
</style>
