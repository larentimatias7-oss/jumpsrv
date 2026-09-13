<template>
  <div class="milicic-brand" :style="{ height: `${height}px` }">
    <img 
      src="/milicic-logo.png" 
      alt="Milicic S.A." 
      class="milicic-img" 
      :style="{ height: `${height}px` }"
    />
  </div>
</template>

<script setup>
defineProps({
  height: {
    type: [Number, String],
    default: 28
  }
})
</script>

<style scoped>
.milicic-brand {
  display: inline-flex;
  align-items: center;
}
.milicic-img {
  width: auto;
  object-fit: contain;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.1));
}
</style>
