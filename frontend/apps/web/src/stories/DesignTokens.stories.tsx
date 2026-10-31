import type { Meta, StoryObj } from "@storybook/react";
import type { ReactNode } from "react";
import {
  darkSemanticState,
  darkTokens,
  fontFamilyMono,
  fontFamilySans,
  lightTokens,
  semanticState,
} from "@edp/shared";

/* —— 展示数据（原型 `<style id="theme-vars">` 镜像；主值来自 @edp/shared，
      仅 primary-50/100/200 与阴影为 CSS-only 值，tokens.test.ts 锁 shared 侧）—— */

// 原型 tokens.css CSS-only 值（亮）：--edp-primary-50/100/200
const lightPrimaryTints = ["#ececff", "#dcdcff", "#c6c7ed"] as const;
// 原型 tokens.css .dark：--edp-primary-50/100/200
const darkPrimaryTints = ["#1e1f3a", "#2a2b4d", "#3d3e6a"] as const;

const neutralRows: Array<{ name: string; light: string; dark: string }> = [
  { name: "--edp-background", light: lightTokens.colorBgLayout, dark: darkTokens.colorBgLayout },
  { name: "--edp-card", light: lightTokens.colorBgContainer, dark: darkTokens.colorBgContainer },
  { name: "--edp-foreground", light: lightTokens.colorText, dark: darkTokens.colorText },
  {
    name: "--edp-muted-foreground",
    light: lightTokens.colorTextSecondary,
    dark: darkTokens.colorTextSecondary,
  },
  { name: "--edp-border", light: lightTokens.colorBorder, dark: darkTokens.colorBorder },
];

// tokens.css :root --edp-shadow-1/2/3（CSS-only 原值）
const shadows: Array<[string, string]> = [
  ["--edp-shadow-1", "0 1px 2px rgba(15,23,42,.05), 0 1px 1px rgba(15,23,42,.03)"],
  ["--edp-shadow-2", "0 8px 24px -8px rgba(15,23,42,.12)"],
  ["--edp-shadow-3", "0 24px 60px -20px rgba(15,23,42,.18)"],
];

const fontScale = [10, 11, 12, 14, 18, 20, 24] as const;

/* —— 展示组件 —— */

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section
      style={{
        background: "var(--edp-card)",
        color: "var(--edp-foreground)",
        border: "1px solid var(--edp-border)",
        borderRadius: "var(--edp-radius-large)",
        boxShadow: "var(--edp-shadow-1)",
        padding: 16,
      }}
    >
      <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{title}</h3>
      <div style={{ display: "grid", gap: 12, marginTop: 12 }}>{children}</div>
    </section>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>{children}</div>;
}

function Swatch({ name, value }: { name: string; value: string }) {
  return (
    <div style={{ display: "grid", gap: 4, width: 104 }}>
      <div
        style={{
          height: 44,
          borderRadius: "var(--edp-radius-small)",
          background: value,
          border: "1px solid var(--edp-border)",
        }}
      />
      <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-ink-2)" }}>
        {name}
      </div>
      <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-muted-foreground)" }}>
        {value}
      </div>
    </div>
  );
}

function RowLabel({ children }: { children: ReactNode }) {
  return (
    <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-ink-2)", width: 72 }}>
      {children}
    </div>
  );
}

function StateChip({
  fg,
  bg,
  backing,
}: {
  fg: string;
  bg: string;
  backing?: string;
}) {
  return (
    <div style={{ background: backing, padding: backing ? 6 : 0, borderRadius: 6, width: "fit-content" }}>
      <span
        style={{
          display: "inline-block",
          background: bg,
          color: fg,
          borderRadius: "var(--edp-radius-full)",
          padding: "2px 10px",
          fontSize: 10,
          fontWeight: 500,
        }}
      >
        DELIVERED
      </span>
    </div>
  );
}

function DesignTokensGallery() {
  return (
    <div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(480px, 1fr))" }}>
      <Group title="主色阶（亮/暗）">
        <Row>
          <RowLabel>亮 :root</RowLabel>
          <Swatch name="--edp-primary" value={lightTokens.colorPrimary} />
          <Swatch name="--edp-primary-50" value={lightPrimaryTints[0]} />
          <Swatch name="--edp-primary-100" value={lightPrimaryTints[1]} />
          <Swatch name="--edp-primary-200" value={lightPrimaryTints[2]} />
        </Row>
        <Row>
          <RowLabel>暗 .dark</RowLabel>
          <Swatch name="--edp-primary" value={darkTokens.colorPrimary} />
          <Swatch name="--edp-primary-50" value={darkPrimaryTints[0]} />
          <Swatch name="--edp-primary-100" value={darkPrimaryTints[1]} />
          <Swatch name="--edp-primary-200" value={darkPrimaryTints[2]} />
        </Row>
      </Group>

      <Group title="中性色（亮/暗）">
        {neutralRows.map((row) => (
          <Row key={row.name}>
            <RowLabel>{row.name}</RowLabel>
            <Swatch name="亮 :root" value={row.light} />
            <Swatch name="暗 .dark" value={row.dark} />
          </Row>
        ))}
      </Group>

      <Group title="状态色 4 组（fg/bg 对，亮/暗）">
        {(Object.keys(semanticState) as Array<keyof typeof semanticState>).map((key) => (
          <Row key={key}>
            <RowLabel>--edp-state-{key}</RowLabel>
            <Swatch name={`fg 亮`} value={semanticState[key].fg} />
            <Swatch name={`bg 亮`} value={semanticState[key].bg} />
            <Swatch name="fg 暗" value={darkSemanticState[key].fg} />
            <div style={{ display: "grid", gap: 4, width: 104 }}>
              <div
                style={{
                  height: 44,
                  borderRadius: "var(--edp-radius-small)",
                  background: "#0b0c14",
                  border: "1px solid var(--edp-border)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <StateChip fg={darkSemanticState[key].fg} bg={darkSemanticState[key].bg} />
              </div>
              <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-muted-foreground)" }}>
                bg 暗 {darkSemanticState[key].bg}
              </div>
            </div>
          </Row>
        ))}
      </Group>

      <Group title="圆角 3 档">
        <Row>
          {[lightTokens.borderRadiusSM, lightTokens.borderRadius, lightTokens.borderRadiusLG].map(
            (radius) => (
              <div key={radius} style={{ display: "grid", gap: 4 }}>
                <div
                  style={{
                    width: 120,
                    height: 56,
                    background: "var(--edp-primary)",
                    borderRadius: radius,
                  }}
                />
                <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-ink-2)" }}>
                  {radius === lightTokens.borderRadiusSM
                    ? "--edp-radius-small"
                    : radius === lightTokens.borderRadius
                      ? "--edp-radius-medium"
                      : "--edp-radius-large"}
                </div>
                <div
                  className="edp-font-mono"
                  style={{ fontSize: 10, color: "var(--edp-muted-foreground)" }}
                >
                  {radius}px
                </div>
              </div>
            ),
          )}
        </Row>
      </Group>

      <Group title="阴影 3 级">
        {shadows.map(([name, value]) => (
          <div key={name} style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <div
              style={{
                width: 180,
                height: 64,
                background: "var(--edp-card)",
                borderRadius: "var(--edp-radius-medium)",
                boxShadow: `var(${name})`,
                border: "1px solid var(--edp-border)",
                flex: "0 0 auto",
              }}
            />
            <div style={{ display: "grid", gap: 4 }}>
              <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-ink-2)" }}>
                {name}
              </div>
              <div
                className="edp-font-mono"
                style={{ fontSize: 10, color: "var(--edp-muted-foreground)", wordBreak: "break-all" }}
              >
                {value}
              </div>
            </div>
          </div>
        ))}
      </Group>

      <Group title="字体（sans / mono）">
        <div>
          <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-ink-2)" }}>
            .edp-font-sans
          </div>
          <div className="edp-font-sans" style={{ fontFamily: fontFamilySans, fontSize: 13 }}>
            正文样例：EDP 数据平台 —— 对象注册、事件回放与证据闭环（Inter / Noto Sans SC）
          </div>
        </div>
        <div>
          <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-ink-2)" }}>
            .edp-font-mono
          </div>
          <div className="edp-font-mono" style={{ fontFamily: fontFamilyMono, fontSize: 13 }}>
            ID 样例：evt-8f3a91c2 · obj:CUST-771 · sha256:9c2f…（等宽，用于 ID/哈希/日志）
          </div>
        </div>
      </Group>

      <Group title="字号阶">
        {fontScale.map((size) => (
          <div key={size} style={{ display: "flex", gap: 12, alignItems: "baseline" }}>
            <div className="edp-font-mono" style={{ fontSize: 10, color: "var(--edp-ink-2)", width: 72 }}>
              {size}px
            </div>
            <div style={{ fontSize: size, color: "var(--edp-foreground)" }}>
              数据平台 Aa 123 —— 对象注册
            </div>
          </div>
        ))}
      </Group>
    </div>
  );
}

const meta: Meta = {
  title: "Foundation/DesignTokens",
  parameters: {
    layout: "padded",
    docs: {
      description: {
        component: [
          "EDP 设计令牌对照基线：全部色值/圆角/阴影与 `原型设计/pages/*.html` 的 `<style id=\"theme-vars\">` 完全一致（`packages/shared/src/tokens/tokens.test.ts` 锁定）。",
          "本 story 静态展示亮/暗两套原值；切换当前画布主题请用上方 Backgrounds 工具栏（Light/Dark），或查看 `Foundation/ThemeToggle` 的固定亮/暗两个 story。",
        ].join("\n\n"),
      },
    },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => <DesignTokensGallery />,
};
