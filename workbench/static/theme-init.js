/* 首屏主题决策：URL 参数 > 用户选择 > 系统偏好。
   必须在 style.css 之前以阻塞方式加载，否则会先渲染深色再跳浅色（FOUC）。
   CSP 是 script-src 'self'，所以不能写成内联脚本。 */
(function () {
  var saved = null;
  try { saved = localStorage.getItem("wb.theme"); } catch (e) { /* 隐私模式下不可用 */ }
  var fromUrl = null;
  try { fromUrl = new URLSearchParams(location.search).get("theme"); } catch (e) { /* ignore */ }
  var sys = "dark";
  try {
    sys = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  } catch (e) { /* ignore */ }

  var theme = (fromUrl === "light" || fromUrl === "dark")
    ? fromUrl
    : ((saved === "light" || saved === "dark") ? saved : sys);

  document.documentElement.dataset.theme = theme;
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "light" ? "#f5f6f8" : "#10151c";
})();
