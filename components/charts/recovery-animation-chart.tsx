"use client";

import type { CurveData } from "@/lib/api";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { LineChart, ScatterChart } from "echarts/charts";
import {
    GridComponent,
    LegendComponent,
    TitleComponent,
    ToolboxComponent,
    TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  ToolboxComponent,
  TitleComponent,
  CanvasRenderer,
]);

interface Props {
  numerical: CurveData;
  analytical: CurveData;
  frameTimes: number[];
  frame: number;
}

function interp(xs: number[], ys: number[], x: number) {
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  const i = xs.findIndex((v) => v > x);
  const x0 = xs[i - 1];
  const x1 = xs[i];
  const y0 = ys[i - 1];
  const y1 = ys[i];
  return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
}

export function RecoveryAnimationChart({ numerical, analytical, frameTimes, frame }: Props) {
  const n = frameTimes.length;
  const idx = Math.min(frame, Math.max(n - 1, 0));
  const t = frameTimes[idx];
  const tMax = frameTimes[Math.max(n - 1, 0)] ?? 1;

  const rCurrent = interp(numerical.x, numerical.y, t);

  // index of the last recorded recovery point at or before current time
  let k = numerical.x.length - 1;
  while (k >= 0 && numerical.x[k] > t) k--;

  const numericalLine: [number, number][] = [];
  for (let i = 0; i <= k; i++) {
    numericalLine.push([numerical.x[i], numerical.y[i]]);
  }
  numericalLine.push([t, rCurrent]);

  const analyticalLine = analytical.x.map((x, i) => [x, analytical.y[i]] as [number, number]);

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={{
        title: {
          text: "Recovery factor",
          left: "center",
          textStyle: { fontSize: 14 },
        },
        tooltip: {
          trigger: "axis",
          formatter: (ps: { value: number[]; seriesName: string }[] | { value: number[]; seriesName: string }) => {
            const p = Array.isArray(ps) ? ps[0] : ps;
            const [x, y] = p.value;
            return `${p.seriesName}<br/>t = ${x.toFixed(2)} d<br/>R = ${y.toFixed(4)}`;
          },
        },
        legend: { data: ["Analytical (M&S)", "Diffusion model"], top: 28, textStyle: { fontSize: 11 } },
        grid: { top: 70, bottom: 40, left: 60, right: 30 },
        toolbox: {
          feature: { saveAsImage: { title: "Save" } },
          right: 10,
          top: 0,
        },
        xAxis: {
          type: "value",
          name: "Time (days)",
          nameLocation: "center",
          nameGap: 28,
          min: 0,
          max: tMax,
        },
        yAxis: {
          type: "value",
          name: "Recovery fraction",
          min: 0,
          max: 1,
        },
        series: [
          {
            name: "Analytical (M&S)",
            type: "line",
            data: analyticalLine,
            lineStyle: { width: 2, type: "dashed" },
            itemStyle: { color: "#6b7280" },
            showSymbol: false,
            animation: false,
          },
          {
            name: "Diffusion model",
            type: "line",
            data: numericalLine,
            lineStyle: { width: 2 },
            itemStyle: { color: "#3b82f6" },
            showSymbol: false,
            animation: false,
          },
          {
            name: "Current",
            type: "scatter",
            data: [[t, rCurrent]],
            symbolSize: 10,
            itemStyle: { color: "#3b82f6", borderColor: "#fff", borderWidth: 2 },
            animation: false,
            z: 10,
          },
        ],
      }}
      notMerge={true}
      style={{ height: 350, width: "100%" }}
    />
  );
}
