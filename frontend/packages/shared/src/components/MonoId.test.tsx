import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MonoId } from "./MonoId";

const writeText = vi.fn().mockResolvedValue(undefined);

beforeAll(() => {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});

afterEach(() => writeText.mockClear());

describe("MonoId", () => {
  it("短格式：prefix + id 前 8 位；title 携带全量", () => {
    render(
      <MonoId prefix="evt" id="8f32a1c49e07" full="evt-8f32a1c4-9e07-full" />,
    );
    const value = screen.getByText("evt-8f32a1c4");
    expect(value).toBeInTheDocument();
    expect(value.closest("span[title]")).toHaveAttribute("title", "evt-8f32a1c4-9e07-full");
  });

  it("自定义 length 截取", () => {
    render(<MonoId prefix="evt" id="8f32a1c49e07" length={4} />);
    expect(screen.getByText("evt-8f32")).toBeInTheDocument();
  });

  it("hashFormat：首4…尾4", () => {
    render(<MonoId id="a4c19f3d8827b6e5" hashFormat full="a4c19f3d8827b6e5xxxx" />);
    expect(screen.getByText("a4c1…b6e5")).toBeInTheDocument();
  });

  it("复制：点击后写入 full 值并变 check 图标", async () => {
    render(<MonoId prefix="ev" id="2b9077aa" full="ev-2b9077aa-full-uuid" />);
    fireEvent.click(screen.getByRole("button", { name: /复制 ev-2b9077aa-full-uuid/ }));
    expect(writeText).toHaveBeenCalledWith("ev-2b9077aa-full-uuid");
    await waitFor(() => expect(document.querySelector(".lucide-check")).not.toBeNull());
    await waitFor(
      () => expect(document.querySelector(".lucide-check")).toBeNull(),
      { timeout: 2200 },
    );
  });

  it("copyable=false 不渲染复制按钮", () => {
    render(<MonoId prefix="dc" id="1048" copyable={false} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("dc-1048")).toBeInTheDocument();
  });
});
