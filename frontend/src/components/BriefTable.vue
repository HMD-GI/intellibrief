<template>
  <div class="brief-table">
    <div class="table-row table-head">
      <div>日期</div>
      <div>标题</div>
      <div>类型</div>
      <div>操作</div>
    </div>
    <div v-if="!items.length" class="empty">暂无数据</div>
    <div v-for="item in items" :key="item.id" class="table-row">
      <div>{{ item.date }}</div>
      <div>{{ item.title }}</div>
      <div>{{ item.type || "daily" }}</div>
      <div class="row-actions">
        <button type="button" class="secondary-btn" @click="$emit('view', item.date)">查看</button>
        <button type="button" class="danger-btn" @click="$emit('remove', item.date)">删除</button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  items: {
    type: Array,
    default: () => [],
  },
});

defineEmits(["view", "remove"]);
</script>
