"use client";

import type { PropertiesResponse } from "@/lib/api";
import { fmtUpTo4Decimals } from "@/lib/utils";
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
  tooltipDecimals = 4,
  yAxisFormatter,
}: {
  title: string;
  series: { name: string; x: number[]; y: number[]; color?: string; dash?: boolean }[];
  xName: string;
  yName: string;
  yScale?: "value" | "log";
  tooltipDecimals?: number | null;
  yAxisFormatter?: (value: number) => string;
}) {
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={{
        title: { text: title, left: "center", textStyle: { fontSize: 13 } },
        tooltip: {
          trigger: "axis",
          formatter: tooltipDecimals != null
            ? (ps: { value: number[]; seriesName: string; marker: string }[] | { value: number[]; seriesName: string; marker: string }) => {
                const arr = Array.isArray(ps) ? ps : [ps];
                const x = arr[0].value[0];
                let html = `${xName} = ${fmtUpTo4Decimals(x)}`;
                for (const p of arr) {
                  const y = p.value[1];
                  html += `<br/>${p.marker}${p.seriesName}: ${fmtUpTo4Decimals(y)}`;
                }
                return html;
              }
            : undefined,
        },
        legend: { top: 44, textStyle: { fontSize: 11 } },
        grid: { top: 80, bottom: 35, left: 65, right: 15 },
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
        yAxis: { type: yScale, name: yName, ...(yAxisFormatter ? { axisLabel: { formatter: yAxisFormatter } } : {}) },
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
        xName="Normalized Sw"
        yName="Relative permeability"
        series={[
          { name: "kro", x: kr.S, y: kr.kro, color: "#188d00ff" },
          { name: "krw", x: kr.S, y: kr.krw, color: "#3b82f6" },
        ]}
      />

      <XYLineChart
        title="Fractional Flow (Eq. 3)"
        xName="Normalized Sw"
        yName="f(Sw)"
        series={[{ name: "fw", x: ff.S, y: ff.fw, color: "#106db9ff" }]}
      />

      <XYLineChart
        title="Imbibition capillary pressure Pc = -B ln S, Eq. 20"
        xName="Normalized Sw"
        yName="Pc, psi"
        series={[{ name: "Pc", x: pc.S, y: pc.Pc_psi, color: "#b3a102ff" }]}
      />

      <XYLineChart
        title="Slope -dPc/dSw = B/S"
        xName="Normalized Sw"
        yName="-dPc/dSw, psi"
        yScale="log"
        series={[
          {
            name: "-dPc/dSw",
            x: pc.S,
            y: pc.dPc_dSw_psi.map((v) => -v),
            color: "#b32e02ff",
          },
        ]}
      />

      <XYLineChart
        title="Diffusion Coefficient D(S) (Eq. 2)"
        xName="Normalized Sw"
        yName="D (m²/s)"
        tooltipDecimals={null}
        yAxisFormatter={(v) => (v === 0 ? "0" : v.toExponential(1))}
        series={[{ name: "D(S)", x: dc.S, y: dc.D_cm2_s.map((v) => v / 1e4), color: "#8b5cf6" }]}
      />
    </div>
  );
}
