"use client";

import type { CurveData } from "@/lib/api";
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

interface Props {
  numerical: CurveData;
  analytical: CurveData;
}

export function RecoveryChart({ numerical, analytical }: Props) {
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={{
        title: { text: "Recovery vs Time", left: "center", textStyle: { fontSize: 14 } },
        tooltip: { trigger: "axis" },
        legend: { top: 28, textStyle: { fontSize: 11 } },
        grid: { top: 70, bottom: 40, left: 60, right: 20 },
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
            data: analytical.x.map((x, i) => [x, analytical.y[i]]),
            lineStyle: { width: 2, type: "dashed" },
            itemStyle: { color: "#1f2937" },
            showSymbol: false,
          },
          {
            name: "Diffusion model",
            type: "line",
            data: numerical.x.map((x, i) => [x, numerical.y[i]]),
            lineStyle: { width: 2 },
            itemStyle: { color: "#3b82f6" },
            showSymbol: false,
          },
        ],
      }}
      style={{ height: 350, width: "100%" }}
    />
  );
}
