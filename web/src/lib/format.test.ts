import { describe, expect, it } from "vitest";
import { ago, money, pct, stockLabel } from "./format";

describe("money", () => {
  it("formats whole and fractional dollars", () => {
    expect(money(419)).toBe("A$419");
    expect(money("399.5")).toBe("A$399.50");
  });
  it("shows a dash for missing or bad values", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
    expect(money("")).toBe("—");
    expect(money("abc")).toBe("—");
  });
});

describe("pct", () => {
  it("rounds and handles empties", () => {
    expect(pct(27.6)).toBe("28%");
    expect(pct(null)).toBe("—");
  });
});

describe("ago", () => {
  const now = Date.parse("2026-10-27T10:00:00Z");
  it("counts up through the units", () => {
    expect(ago("2026-10-27T09:59:42Z", now)).toBe("18 sec ago");
    expect(ago("2026-10-27T09:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-10-27T08:00:00Z", now)).toBe("2 h ago");
    expect(ago("2026-10-24T10:00:00Z", now)).toBe("3 d ago");
  });
  it("never goes negative when the clock is ahead", () => {
    expect(ago("2026-10-27T10:00:05Z", now)).toBe("0 sec ago");
  });
  it("is a dash when unknown", () => {
    expect(ago(null, now)).toBe("—");
    expect(ago("nonsense", now)).toBe("—");
  });
});

it("stockLabel is human readable", () => {
  expect(stockLabel("OUT_OF_STOCK")).toBe("out of stock");
  expect(stockLabel(undefined)).toBe("unknown");
});
