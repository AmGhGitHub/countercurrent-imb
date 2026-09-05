"use client";

import type { SaturationMap } from "@/lib/api";
import { fmtUpTo4Decimals } from "@/lib/utils";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { HeatmapChart, LineChart } from "echarts/charts";
import {
    GridComponent,
    TitleComponent,
    ToolboxComponent,
    TooltipComponent,
    VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  ToolboxComponent,
  TitleComponent,
  CanvasRenderer,
]);

// Dark green (S = 0) -> dark blue (S = 1) gradient, requested for the timelapse.
const SATURATION_COLORS = [
  "#064e3b", // dark green
  "#059669", // green 600
  "#10b981", // emerald
  "#14b8a6", // teal
  "#06b6d4", // cyan
  "#0ea5e9", // sky
  "#1e40af", // dark blue
];

interface Props {
  map: SaturationMap;
  frame: number;
}

export function SaturationAnimationChart({ map, frame }: Props) {
  const n = map.frames.length;
  const idx = Math.min(frame, n - 1);
  const t = map.times_days[idx];
  const S = map.frames[idx];

  const xLabels = map.x_m.map((x) => x.toFixed(3)); // m
  const lineData = map.x_m.map((x, i) => [x, S[i]]);
  const stripData: [number, number, number][] = S.map((v, i) => [i, 0, v]);

  // block-edge extents of the (uniform, possibly strided) grid
  const dx = map.x_m.length > 1 ? map.x_m[1] - map.x_m[0] : map.x_m[0];

  return (
    <div>
      <ReactEChartsCore
        echarts={echarts}
        option={{
          title: {
            text: "Water saturation",
            left: "center",
            textStyle: { fontSize: 14 },
          },
          tooltip: {
            trigger: "axis",
            formatter: (
              ps: { value: number[]; seriesType: string }[] | { value: number[]; seriesType: string }
            ) => {
              const p = Array.isArray(ps) ? ps[0] : ps;
              if (p.seriesType === "heatmap") {
                const [i, , v] = p.value;
                return `x = ${xLabels[i]} m<br/>Sw = ${fmtUpTo4Decimals(v)}`;
              }
              const [x, v] = p.value;
              return `x = ${x.toFixed(3)} m<br/>Sw = ${fmtUpTo4Decimals(v)}`;
            },
          },
          grid: [
            { top: 48, left: 65, right: 90, height: 190 },
            { top: 268, left: 65, right: 90, height: 55 },
          ],
          toolbox: {
            feature: { saveAsImage: { title: "Save" } },
            right: 10,
            top: 0,
          },
          xAxis: [
            {
              gridIndex: 0,
              type: "value",
              min: map.x_m[0] - dx / 2,
              max: map.x_m[map.x_m.length - 1] + dx / 2,
              axisLabel: { show: false },
              axisTick: { show: false },
            },
            {
              gridIndex: 1,
              type: "category",
              data: xLabels,
              name: "Distance from inlet (m)",
              nameLocation: "center",
              nameGap: 28,
              axisLabel: { hideOverlap: true, fontSize: 10 },
            },
          ],
          yAxis: [
            {
              gridIndex: 0,
              type: "value",
              name: "Normalized water saturation",
              min: 0,
              max: 1.02,
              interval: 0.2,
            },
            {
              gridIndex: 1,
              type: "category",
              data: [""],
              axisLabel: { show: false },
              axisTick: { show: false },
              axisLine: { show: false },
            },
          ],
          visualMap: {
            min: 0,
            max: 1,
            seriesIndex: 1,
            orient: "vertical",
            right: 0,
            top: "center",
            itemHeight: 200,
            inRange: { color: SATURATION_COLORS },
            text: ["Sw = 1", "Sw = 0"],
          },
          series: [
            {
              name: "Sw",
              type: "line",
              xAxisIndex: 0,
              yAxisIndex: 0,
              data: lineData,
              showSymbol: false,
              lineStyle: { width: 2, color: "#3b82f6" },
            },
            {
              name: "Sw",
              type: "heatmap",
              xAxisIndex: 1,
              yAxisIndex: 1,
              data: stripData,
              itemStyle: { borderWidth: 0 },
            },
          ],
        }}
        style={{ height: 400, width: "100%" }}
      />
    </div>
  );
}
