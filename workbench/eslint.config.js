// T-09：ESLint flat config（零构建前端，仅静态检查；vendor 目录忽略）
// 用法：npx eslint static/ （在 workbench/ 下）
import js from "@eslint/js";

export default [
  js.configs.recommended,
  {
    ignores: ["static/vendor/**", "static/**/*.meta.json"],
  },
  {
    files: ["static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "module",
      globals: {
        window: "readonly", document: "readonly", localStorage: "readonly",
        fetch: "readonly", URL: "readonly", Blob: "readonly",
        EventSource: "readonly", CustomEvent: "readonly",
        console: "readonly", setTimeout: "readonly", setInterval: "readonly",
        clearTimeout: "readonly", clearInterval: "readonly",
        btoa: "readonly", encodeURIComponent: "readonly", decodeURIComponent: "readonly",
        confirm: "readonly", prompt: "readonly", alert: "readonly",
        location: "readonly", navigator: "readonly",
        FormData: "readonly", requestAnimationFrame: "readonly",
        getComputedStyle: "readonly", matchMedia: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "no-empty": ["error", { allowEmptyCatch: true }],  // catch{} 是本项目的静默策略
      "no-undef": "error",
      "eqeqeq": ["warn", "smart"],
      "no-var": "warn",
      "prefer-const": "warn",
    },
  },
];
