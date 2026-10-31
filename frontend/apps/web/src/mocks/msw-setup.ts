/** 仅 VITE_USE_MSW=1 时启用浏览器 Service Worker（真实模式零影响）。 */
export async function setupMsw(): Promise<void> {
  if (import.meta.env.VITE_USE_MSW !== "1") return;
  const { worker } = await import("./browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}
