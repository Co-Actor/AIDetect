import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { DetectionResult, Mode } from 'src/types/detection';
import { detectionApi } from 'src/services/api';

export const useDetectionStore = defineStore('detection', () => {
  const result = ref<DetectionResult | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  // The exact source text the current `result` was produced from. The view
  // layer compares incoming edits to this to decide whether to invalidate
  // the result (text changed) or keep it (text unchanged — just toggling
  // between annotated preview and editor).
  const lastAnalyzedText = ref<string>('');

  async function detect(text: string, mode: Mode): Promise<void> {
    loading.value = true;
    error.value = null;
    result.value = null;
    try {
      result.value = await detectionApi.analyze({ text, mode });
      lastAnalyzedText.value = text;
    } catch (err: unknown) {
      error.value = err instanceof Error ? err.message : 'Detection failed';
      lastAnalyzedText.value = '';
    } finally {
      loading.value = false;
    }
  }

  function reset(): void {
    result.value = null;
    error.value = null;
    loading.value = false;
    lastAnalyzedText.value = '';
  }

  return { result, loading, error, lastAnalyzedText, detect, reset };
});
