import { defineConfig } from '#q-app/wrappers';

export default defineConfig((ctx) => {
  return {
    boot: ['pinia', 'axios'],

    css: ['app.scss'],

    extras: ['roboto-font', 'material-icons'],

    build: {
      target: {
        browser: ['es2022'],
        node: 'node20',
      },
      vueRouterMode: 'history',
      typescript: {
        strict: true,
        vueShim: true,
      },
      vitePlugins: [],
    },

    devServer: {
      port: 9000,
      open: false,
    },

    framework: {
      config: {
        dark: false,
        notify: {
          position: 'top-right',
          timeout: 3000,
        },
      },
      iconSet: 'material-icons',
      lang: 'en-US',
      plugins: ['Notify', 'Dialog', 'Loading'],
    },

    animations: [],

    ssr: {
      pwa: false,
      prodPort: 3000,
      middlewares: ['render'],
    },

    pwa: {
      workboxMode: 'generateSW',
      injectPwaMetaTags: true,
      swFilename: 'sw.js',
      manifestFilename: 'manifest.json',
      useCredentialsForManifestTag: false,
    },

    cordova: {},

    capacitor: {
      hideSplashscreen: true,
    },

    electron: {
      inspectPort: 5858,
      bundler: 'packager',
      packager: {},
      builder: {
        appId: 'aidetect-frontend',
      },
    },

    bex: {
      contentScripts: ['my-content-script'],
    },
  };
});
