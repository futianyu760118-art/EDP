/**
 * 24 小时事件量柱图（T6，示意性质：确定性伪高，W5 EDP-030 真实时序接入后替换）。
 * 峰值柱固定第 14 根 warning 高亮；peak 用于 aria 标注（原型亦静态示意图）。
 */
export function MiniBarChart({ peak }: { peak?: number }) {
  const bars = Array.from({ length: 24 }, (_, i) => {
    const h = 20 + ((i * 37) % 70) + (i === 14 ? 10 : 0); // 确定性伪高
    return { i, h };
  });
  const maxH = Math.max(...bars.map((b) => b.h));
  return (
    <svg
      viewBox="0 0 240 80"
      className="w-full h-20"
      data-dom-id="overview-bar-chart"
      role="img"
      aria-label={peak != null ? `24 小时事件量柱图（峰值 ${peak} / 小时）` : "24 小时事件量柱图"}
    >
      {bars.map(({ i, h }) => (
        <rect
          key={i}
          x={i * 10}
          y={80 - (h / maxH) * 72}
          width={7}
          height={(h / maxH) * 72}
          rx={1.5}
          className={i === 14 ? "fill-state-warning" : "fill-primary-50"}
        />
      ))}
    </svg>
  );
}
