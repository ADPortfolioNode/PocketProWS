import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Vitest stubs CSS imports to "", so read the stylesheet from disk
// (tests run from the frontend root).
const cssText = readFileSync("src/theme.css", "utf8");

// Hero title color (Anthony, 2026-11-24: "h1 white"): the title is
// white over the dark hero overlay BY DESIGN, but the generic
// heading rule (.ppws-app h1 → ink, specificity 0-1-1) silently beat
// the lone .ppws-hero-title class (0-1-0) and the title rendered
// dark on dark in real browsers. The rule must stay scoped under
// .ppws-app (0-2-0) so white actually wins.
describe("hero title stays white", () => {
  it("the white rule is scoped to outrank the generic heading rule", () => {
    expect(cssText).toMatch(
      /\.ppws-app \.ppws-hero-title\s*\{[^}]*color:\s*#fff/);
  });
});
