const C = 2 * Math.PI * 40; // r=40 周长 ≈ 251.33

/**
 * SVG 环形进度（T6 证据链健康，视觉基线：`原型设计/pages/运营总览.html` 行 573~584 ——
 * 底环 border 色 + 进度环 primary，rotate(-90) 自 12 点起，中心数值 + 副文案）。
 */
export function DonutRing({ pct, label }: { pct: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="relative w-24 h-24">
      <svg
        viewBox="0 0 100 100"
        className="w-full h-full"
        data-dom-id="overview-donut"
        role="img"
        aria-label={label != null ? `${clamped}% ${label}` : `${clamped}%`}
      >
        <g transform="rotate(-90 50 50)">
          <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" strokeWidth="8" className="text-border" />
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            stroke="currentColor"
            strokeWidth="8"
            strokeLinecap="round"
            className="text-primary"
            strokeDasharray={`${(clamped / 100) * C} ${C}`}
          />
        </g>
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-lg font-semibold text-foreground">{clamped}%</span>
        {label != null && <span className="text-[9px] text-muted-foreground">{label}</span>}
      </div>
    </div>
  );
}
