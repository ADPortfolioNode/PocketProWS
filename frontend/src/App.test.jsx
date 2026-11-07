import { describe, expect, it } from "vitest";
import App from "./App.jsx";

// Minimal smoke test: the dashboard module loads and exports a function
// component. (Full DOM rendering tests need @testing-library/react, which
// is intentionally not in the minimal scaffold.)
describe("App smoke", () => {
  it("exports a function component", () => {
    expect(typeof App).toBe("function");
  });
});
