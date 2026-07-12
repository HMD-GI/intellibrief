<template>
  <div class="chip-group">
    <button
      v-for="topic in topics"
      :key="topic"
      type="button"
      class="chip"
      :class="{ active: modelValue.includes(topic) }"
      @click="$emit('toggle', topic)"
    >
      {{ topic }}
    </button>
  </div>
</template>

<script setup>
defineProps({
  topics: {
    type: Array,
    default: () => [],
  },
  modelValue: {
    type: Array,
    default: () => [],
  },
});

defineEmits(["toggle"]);
</script>
