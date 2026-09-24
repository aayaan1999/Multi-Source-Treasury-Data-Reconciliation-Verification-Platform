import { describe, expect, it } from "vitest";
import { KPI_BY_KEY, applyLimits } from "./kpiConfig";
import { statusOf } from "./status";

describe("tiles read the database limits (BRC-4)", () => {
  it("replaces the built-in thresholds so tiles and breach tasks agree", () => {
    applyLimits([
      { kpi_key: "car_pct", early_warning_value: 14, threshold_value: 13, regulatory_value: 11 },
      { kpi_key: "npl_ratio_pct", early_warning_value: 2, threshold_value: 4, regulatory_value: null },
      { kpi_key: "not_a_tile", threshold_value: 1 },
    ]);
    const car = KPI_BY_KEY.car_pct;
    expect([car.amber, car.red, car.limit, car.limitLabel]).toEqual([14, 13, 11, "regulatory minimum"]);
    expect(statusOf(car, 12.9)).toBe("action");            // below the database's 13, fine under the old 12.5
    expect(KPI_BY_KEY.npl_ratio_pct.limit).toBe(4);
    expect(KPI_BY_KEY.npl_ratio_pct.limitLabel).toBe("internal limit");
  });

  it("keeps the built-in values when nothing could be loaded", () => {
    const before = { ...KPI_BY_KEY.lcr_pct };
    applyLimits(undefined);
    expect(KPI_BY_KEY.lcr_pct.red).toBe(before.red);
  });
});
