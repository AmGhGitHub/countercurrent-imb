export { cn } from "cn";

export function fmtUpTo4Decimals(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(4).replace(/\.?0+$/, "");
}

function niceNum(range: number, round: boolean): number {
  const exponent = Math.floor(Math.log10(range));
  const fraction = range / 10 ** exponent;
  let niceFraction: number;
  if (round) {
    if (fraction < 1.5) niceFraction = 1;
    else if (fraction < 3) niceFraction = 2;
    else if (fraction < 7) niceFraction = 5;
    else niceFraction = 10;
  } else {
    if (fraction <= 1) niceFraction = 1;
    else if (fraction <= 2) niceFraction = 2;
    else if (fraction <= 5) niceFraction = 5;
    else niceFraction = 10;
  }
  return niceFraction * 10 ** exponent;
}

// Snaps [dataMin, dataMax] to round, evenly-spaced axis bounds so a fixed
// `interval` can be given to the chart (avoids ECharts leaving the
// min/max ticks off the auto-picked grid, which produces uneven spacing).
export function niceAxisRange(
  dataMin: number,
  dataMax: number,
  splitNumber = 5
): { min: number; max: number; interval: number } {
  if (dataMin === dataMax) {
    dataMin -= 1;
    dataMax += 1;
  }
  const range = niceNum(dataMax - dataMin, false);
  const interval = niceNum(range / (splitNumber - 1), true);
  const min = Math.floor(dataMin / interval) * interval;
  const max = Math.ceil(dataMax / interval) * interval;
  return { min, max, interval };
}
