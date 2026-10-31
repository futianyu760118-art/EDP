import { describe, expect, it } from "vitest";
import { clampLimit, decodeCursor, encodeCursor, paginate } from "./cursor";

describe("cursor", () => {
  it("encode/decode 往返", () => {
    expect(decodeCursor(encodeCursor(40))).toBe(40);
  });

  it("非法 cursor 归零", () => {
    expect(decodeCursor("!!!not-base64")).toBe(0);
    expect(decodeCursor(btoa("garbage"))).toBe(0);
    expect(decodeCursor(null)).toBe(0);
  });

  it("paginate 整页→有 next_cursor；末页→null", () => {
    const all = [1, 2, 3, 4, 5];
    const p1 = paginate(all, 2, null);
    expect(p1).toEqual({ items: [1, 2], next_cursor: encodeCursor(2), total: 5 });
    const p3 = paginate(all, 2, encodeCursor(4));
    expect(p3).toEqual({ items: [5], next_cursor: null, total: 5 });
  });

  it("offset 越界→空列表", () => {
    expect(paginate([1], 5, encodeCursor(9)).items).toEqual([]);
  });

  it("clampLimit 夹取 1..100，非法回退", () => {
    expect(clampLimit(null)).toBe(20);
    expect(clampLimit("0")).toBe(1);
    expect(clampLimit("500")).toBe(100);
    expect(clampLimit("abc")).toBe(20);
  });
});
