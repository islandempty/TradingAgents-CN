<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Cognitive Mirror</h1>
        <p>查看认知盲点、能力维度和阶段性改进记录。</p>
      </div>
      <el-button type="primary" @click="generate" :loading="loading">生成快照</el-button>
    </div>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" v-for="item in items" :key="item._id" class="snapshot-card">
          <template #header>
            <div class="card-header">
              <span>{{ item.generated_at }}</span>
            </div>
          </template>
          <div class="section">
            <h3>Strengths</h3>
            <p v-for="text in item.strengths || []" :key="text">{{ text }}</p>
          </div>
          <div class="section">
            <h3>Blind Spots</h3>
            <p v-for="text in item.blind_spots || []" :key="text">{{ text }}</p>
          </div>
          <div class="section">
            <h3>Maturity</h3>
            <p v-for="(score, key) in item.maturity_dimensions || {}" :key="key">{{ key }}: {{ score }}</p>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { thesesApi, type CognitiveSnapshot } from '@/api/theses'

const loading = ref(false)
const items = ref<CognitiveSnapshot[]>([])

async function load() {
  try {
    loading.value = true
    const res = await thesesApi.listCognitiveSnapshots()
    if (res.success) items.value = res.data || []
  } catch (error: any) {
    ElMessage.error(error?.message || '加载认知快照失败')
  } finally {
    loading.value = false
  }
}

async function generate() {
  const res = await thesesApi.generateCognitiveSnapshot()
  if (res.success) {
    ElMessage.success('认知快照已生成')
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
.snapshot-card { margin-bottom: 16px; }
.section h3 { margin: 0 0 8px; font-size: 14px; }
.section p { margin: 6px 0; color: var(--el-text-color-regular); }
</style>
