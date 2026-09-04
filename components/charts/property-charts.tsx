"use client";

import type { PropertiesResponse } from "@/lib/api";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { LineChart } from "echarts/charts";
import {
    DataZoomComponent,
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
  DataZoomComponent,
  TitleComponent,
  CanvasRenderer,
]);

interface Props {
  data: PropertiesResponse;
}

function XYLineChart({
  title,
  series,
  xName,
  yName,
  yScale = "value",
}: {
  title: string;
  series: { name: string; x: number[]; y: number[]; color?: string; dash?: boolean }[];
  xName: string;
  yName: string;
  yScale?: "value" | "log";
}) {
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={{
        title: { text: title, left: "center", textStyle: { fontSize: 13 } },
        tooltip: { trigger: "axis" },
        legend: { top: 26, textStyle: { fontSize: 11 } },
        grid: { top: 65, bottom: 35, left: 65, right: 15 },
        toolbox: {
          feature: { saveAsImage: { title: "Save" } },
          right: 5,
          top: 0,
        },
        xAxis: {
          type: "value",
          name: xName,
          nameLocation: "center",
          nameGap: 25,
          min: 0,
          max: 1,
        },
        yAxis: { type: yScale, name: yName },
        series: series.map((s) => ({
          name: s.name,
          type: "line" as const,
          data: s.x.map((x, i) => [x, s.y[i]]),
          lineStyle: { width: 2, ...(s.dash ? { type: "dashed" } : {}) },
          itemStyle: s.color ? { color: s.color } : undefined,
          showSymbol: false,
        })),
      }}
      style={{ height: 300, width: "100%" }}
    />
  );
}

export function PropertyCharts({ data }: Props) {
  const { relative_permeability: kr, fractional_flow: ff, capillary_pressure: pc, diffusion_coefficient: dc } = data;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <XYLineChart
        title="Relative Permeability (Eq. 19)"
        xName="Normalized saturation, S"
        yName="Relative permeability"
        series={[
          { name: "kro", x: kr.S, y: kr.kro, color: "#ef4444" },
          { name: "krw", x: kr.S, y: kr.krw, color: "#3b82f6" },
        ]}
      />

      <XYLineChart
        title="Fractional Flow (Eq. 3)"
        xName="Normalized saturation, S"
        yName="f(Sw)"
        series={[{ name: "fw", x: ff.S, y: ff.fw, color: "#10b981" }]}
      />

      <XYLineChart
        title="Capillary Pressure (Eq. 20)"
        xName="Normalized saturation, S"
        yName="Pc (psi)"
        series={[
          { name: "Pc", x: pc.S, y: pc.Pc_psi, color: "#6366f1" },
          { name: "-dPc/dSw", x: pc.S, y: pc.dPc_dSw_psi, color: "#f59e0b", dash: true },
        ]}
      />

      <XYLineChart
        title="Diffusion Coefficient D(S) (Eq. 2)"
        xName="Normalized saturation, S"
        yName="D (cm²/s)"
        series={[{ name: "D(S)", x: dc.S, y: dc.D_cm2_s, color: "#8b5cf6" }]}
      />
    </div>
  );
}
