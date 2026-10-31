import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HeroCard } from "./HeroCard";
import { health } from "../../mocks/data/health";
import { coverageReport } from "../../mocks/data/quality";

describe("HeroCard 状态卡", () => {
  it("运行 pill / 动态标题（P1 数为 prop）/ 双按钮，查看风险详情触发 onOpenRisk", () => {
    const onOpenRisk = vi.fn();
    render(<HeroCard coverage={coverageReport} health={health} p1Count={3} onOpenRisk={onOpenRisk} />);

    expect(screen.getByText("运行中 · 多租户工作空间")).toBeInTheDocument();
    expect(screen.getByText("今天的 EDP 状态：证据链健康，3 个 P1 风险需要处理")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看风险详情" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出日报" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看风险详情" }));
    expect(onOpenRisk).toHaveBeenCalledOnce();
  });

  it("三指标对齐 fixtures 真实值：覆盖率 96.8% / P95 812ms→0.81s / 成功率 99.5%", () => {
    render(<HeroCard coverage={coverageReport} health={health} p1Count={3} onOpenRisk={() => {}} />);

    expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("96.8%");
    expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("0.81s");
    expect(document.querySelector('[data-dom-id="overview-hero-success"]')?.textContent).toBe("99.5%");
  });

  it("coverage/ops_metrics 缺失（真实模式/加载中）→ 三指标 '—' 兜底", () => {
    render(<HeroCard p1Count={0} onOpenRisk={() => {}} />);

    expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("—");
    expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("—");
    expect(document.querySelector('[data-dom-id="overview-hero-success"]')?.textContent).toBe("—");
  });

  it("真 API 缺 adapters_success_rate → 成功率「—」而 P95 正常，不出现 NaN/undefined", () => {
    const realSubset = {
      events_24h: 120,
      ingest_peak_24h: 20,
      p95_latency_ms: 640,
      idempotency_hit_rate: 0.994,
      dlq: 0,
      evidence_count: 12,
    };
    render(<HeroCard coverage={coverageReport} health={{ ...health, ops_metrics: realSubset }} p1Count={0} onOpenRisk={() => {}} />);

    expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("96.8%");
    expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("0.64s");
    expect(document.querySelector('[data-dom-id="overview-hero-success"]')?.textContent).toBe("—");
    expect(document.body.textContent).not.toMatch(/NaN|undefined/);
  });
});
