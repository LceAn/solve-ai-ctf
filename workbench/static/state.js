// G4.1+G4.3：vendored CSP-safe petite-vue fork（无 new Function/eval，script-src 'self' 兼容）
// G4 阶段仅用 reactive() 替换 const S，渲染层仍用既有 innerHTML + setTab（行为不变）
// G5 迁移时每个 renderX → views/*.js 组件，挂载 createApp + v-scope
import { createApp, reactive, nextTick } from "./vendor/petite-vue.es.js";
export { createApp, nextTick } from "./vendor/petite-vue.es.js";

export const S = reactive({
  competitions: [],
  dir: null,          // 当前比赛目录名
  comp: null,         // /api/competition 结果
  caseData: null,     // /api/case 结果
  slug: null,         // 当前题目 slug
  caseDir: null,      // 当前题目 case 相对目录
  result: null,       // 最近一次动作结果（ops 页展示）
  boardQuery: localStorage.getItem("wb.boardQuery") || "",
  boardStatus: localStorage.getItem("wb.boardStatus") || "all",
});
