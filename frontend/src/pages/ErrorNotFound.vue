<script setup lang="ts">
import { useRouter } from 'vue-router';

const router = useRouter();

function goHome() {
  void router.push('/');
}
</script>

<template>
  <q-page class="flex flex-center column q-gutter-md">
    <q-icon name="search_off" size="6rem" color="grey-5" />
    <div class="text-h5 text-grey-7">Page Not Found</div>
    <div class="text-body1 text-grey-6 text-center">
      The page you are looking for does not exist.
    </div>
    <q-btn label="Go to Detector" color="primary" unelevated no-caps @click="goHome" />
  </q-page>
</template>
