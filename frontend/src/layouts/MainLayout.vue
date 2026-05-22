<script setup lang="ts"></script>

<template>
  <q-layout view="hHh lpR fFf">
    <q-header :elevated="false" class="atelier-header">
      <q-toolbar class="atelier-toolbar">
        <div class="row items-center q-gutter-md">
          <span class="brand-mark font-display">v</span>
          <div class="column items-start" style="line-height: 1">
            <span class="brand-title">AIDetect</span>
            <span class="eyebrow brand-tag">Veracity workbench</span>
          </div>
        </div>
        <q-space />
        <span class="eyebrow brand-version">v0.1</span>
      </q-toolbar>
      <div class="atelier-header-rule" />
    </q-header>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<style scoped lang="scss">
.atelier-header {
  background: var(--paper);
  color: var(--ink);
}
.atelier-toolbar {
  min-height: 64px;
  padding: 0 28px;
}
.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 32px;
  line-height: 1;
  color: var(--accent);
}
.brand-title {
  font-family: var(--font-ui);
  font-weight: 600;
  font-size: 18px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.brand-tag {
  margin-top: 2px;
}
.brand-version {
  color: var(--ink-mute);
}
.atelier-header-rule {
  height: 1px;
  background: var(--rule);
}
</style>
