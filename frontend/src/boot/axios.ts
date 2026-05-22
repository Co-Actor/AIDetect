import { boot } from 'quasar/wrappers';
import apiClient from 'src/services/api';

export default boot(({ app }) => {
  app.config.globalProperties.$axios = apiClient;
});

export { apiClient };
