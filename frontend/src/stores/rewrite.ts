import { defineStore } from 'pinia';
import { ref } from 'vue';
import { rewriteApi } from 'src/services/api';
import type { Mode } from 'src/types/detection';
import type { RewriteResponse, VoicePreset } from 'src/types/rewrite';

export const useRewriteStore = defineStore('rewrite', () => {
  const result = ref<RewriteResponse | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function rewrite(
    text: string,
    mode: Mode,
    voice: VoicePreset | null,
    customInstructions: string | null,
    targetAi: number,
    maxIterations: number,
  ): Promise<void> {
    loading.value = true;
    error.value = null;
    result.value = null;
    try {
      result.value = await rewriteApi.rewrite({
        text,
        mode,
        custom_voice_instructions: customInstructions,
        options: {
          voice,
          target_ai_probability: targetAi,
          max_iterations: maxIterations,
        },
      });
    } catch (err: unknown) {
      error.value = err instanceof Error ? err.message : 'Rewrite failed';
    } finally {
      loading.value = false;
    }
  }

  function reset(): void {
    result.value = null;
    error.value = null;
    loading.value = false;
  }

  return { result, loading, error, rewrite, reset };
});
