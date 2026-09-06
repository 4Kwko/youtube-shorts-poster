import { describe, expect, it } from "vitest";

import { formatDuration, formatTimecode } from "./time";

describe("formatTimecode", () => {
  it.each([
    [0, "00:00"],
    [9, "00:09"],
    [90, "01:30"],
    [599, "09:59"],
    [3600, "1:00:00"],
    [3661, "1:01:01"],
  ])("formata %s segundos como %s", (seconds, expected) => {
    expect(formatTimecode(seconds)).toBe(expected);
  });

  it("trunca floats em vez de arredondar para cima", () => {
    expect(formatTimecode(89.9)).toBe("01:29");
    expect(formatTimecode(90.4)).toBe("01:30");
  });

  it("protege contra valores inválidos", () => {
    expect(formatTimecode(-5)).toBe("00:00");
    expect(formatTimecode(Number.NaN)).toBe("00:00");
  });
});

describe("formatDuration", () => {
  it.each([
    [0, "0s"],
    [45, "45s"],
    [60, "1min"],
    [90, "1min 30s"],
    [3661, "61min 1s"],
  ])("formata %s segundos como %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});
