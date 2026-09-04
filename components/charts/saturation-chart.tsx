"use client";

import type { ProfileSeries } from "@/lib/api";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { LineChart } from "echarts/charts";
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
  GridComponent,
  TooltipComponent,
  LegendComponent,
  ToolboxComponent,
  TitleComponent,
  CanvasRenderer,
]);

const COLORS = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];

interface Props {
  numerical: ProfileSeries[];
  analytical: ProfileSeries[];
}

export function SaturationChart({ numerical, analytical }: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const series: any[] = [];

  numerical.forEach((p, i) => {
    const color = COLORS[i % COLORS.length];
    series.push({
      name: p.time_label,
      type: "line",
      data: p.x_m.map((x, j) => [x, p.values[j]]),
      lineStyle: { width: 2 },
      itemStyle: { color },
      showSymbol: false,
    });
  });

  analytical.forEach((p, i) => {
    const color = COLORS[i % COLORS.length];
    series.push({
      name: p.time_label,
      type: "line",
      data: p.x_m.map((x, j) => [x, p.values[j]]),
      lineStyle: { width: 1.5, type: "dashed" },
      itemStyle: { color },
      showSymbol: false,
    });
  });

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={{
        title: { text: "Saturation Distribution", left: "center", textStyle: { fontSize: 14 } },
        tooltip: { trigger: "axis" },
        legend: { top: 28, type: "scroll", textStyle: { fontSize: 11 } },
        grid: { top: 70, bottom: 40, left: 60, right: 20 },
        toolbox: {
          feature: { saveAsImage: { title: "Save" } },
          right: 10,
          top: 0,
        },
        xAxis: {
          type: "value",
          name: "Distance from inlet (m)",
          nameLocation: "center",
          nameGap: 28,
        },
        yAxis: {
          type: "value",
          name: "Normalized water saturation",
          min: 0,
          max: 1.02,
        },
        series,
      }}
      style={{ height: 400, width: "100%" }}
    />
  );
}
