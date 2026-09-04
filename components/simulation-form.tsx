"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import type { SimulationRequest } from "@/lib/api";
import { useEffect, useRef, useState } from "react";

interface ParamDef {
  key: keyof SimulationRequest;
  label: string;
  unit?: string;
  min: number;
  max: number;
  step: number;
  default: number;
  integer?: boolean;
}

const PARAM_GROUPS: { title: string; params: ParamDef[] }[] = [
  {
    title: "Rock Properties",
    params: [
      { key: "L", label: "Block length", unit: "m", min: 0.01, max: 2.0, step: 0.01, default: 0.20 },
      { key: "k", label: "Permeability", unit: "md", min: 0.1, max: 5000, step: 0.1, default: 20 },
      { key: "phi", label: "Porosity", min: 0.01, max: 0.60, step: 0.01, default: 0.30 },
    ],
  },
  {
    title: "Fluid Properties",
    params: [
      { key: "mu_o", label: "Oil viscosity", unit: "cp", min: 0.1, max: 500, step: 0.1, default: 1.0 },
      { key: "mu_w", label: "Water viscosity", unit: "cp", min: 0.1, max: 100, step: 0.1, default: 1.0 },
    ],
  },
  {
    title: "Relative Permeability",
    params: [
      { key: "kro0", label: "kr oil endpoint", min: 0.01, max: 1.0, step: 0.01, default: 0.75 },
      { key: "krw0", label: "kr water endpoint", min: 0.01, max: 1.0, step: 0.01, default: 0.20 },
      { key: "no", label: "Oil exponent", min: 1, max: 10, step: 0.5, default: 4.0 },
      { key: "nw", label: "Water exponent", min: 1, max: 10, step: 0.5, default: 4.0 },
    ],
  },
  {
    title: "Capillary Pressure",
    params: [
      { key: "B", label: "Constant B", unit: "psi", min: 0.1, max: 50, step: 0.1, default: 1.45 },
    ],
  },
  {
    title: "Initial Conditions",
    params: [
      { key: "Si", label: "Initial saturation", min: 0.001, max: 0.5, step: 0.001, default: 0.001 },
      { key: "Swi", label: "Irreducible Sw", min: 0, max: 0.5, step: 0.01, default: 0.0 },
      { key: "Sor", label: "Residual oil sat.", min: 0, max: 0.5, step: 0.01, default: 0.0 },
    ],
  },
  {
    title: "Numerical",
    params: [
      { key: "tmax", label: "End time", unit: "days", min: 0.1, max: 1000, step: 1, default: 40 },
      { key: "nx", label: "Grid blocks", min: 50, max: 1000, step: 50, default: 300, integer: true },
    ],
  },
];

function buildDefaults(): SimulationRequest {
  const r: Record<string, number> = {};
  for (const g of PARAM_GROUPS) {
    for (const p of g.params) {
      r[p.key] = p.default;
    }
  }
  return r as unknown as SimulationRequest;
}

interface Props {
  onSubmit: (params: SimulationRequest) => void;
  onParamsChange?: (params: SimulationRequest) => void;
  loading: boolean;
}

export function SimulationForm({ onSubmit, onParamsChange, loading }: Props) {
  const [params, setParams] = useState<SimulationRequest>(buildDefaults);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const update = (key: keyof SimulationRequest, value: number) => {
    setParams((prev) => {
      const next = { ...prev, [key]: value };
      // Debounced property fetch on every parameter change
      if (onParamsChange) {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => onParamsChange(next), 300);
      }
      return next;
    });
  };

  // Fetch properties on mount
  useEffect(() => {
    if (onParamsChange) onParamsChange(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-lg">Simulation Parameters</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {PARAM_GROUPS.map((group, gi) => (
          <div key={gi}>
            {gi > 0 && <Separator className="mb-4" />}
            <h3 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wide">
              {group.title}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
              {group.params.map((p) => {
                const val = params[p.key] as number;
                return (
                  <div key={p.key} className="space-y-1.5">
                    <div className="flex justify-between">
                      <Label htmlFor={p.key} className="text-sm">
                        {p.label}
                        {p.unit && <span className="text-muted-foreground ml-1">({p.unit})</span>}
                      </Label>
                      <span className="text-sm tabular-nums text-muted-foreground font-mono">
                        {p.integer ? val : val.toFixed(p.step < 0.01 ? 3 : p.step < 1 ? 2 : 1)}
                      </span>
                    </div>
                    <Slider
                      id={p.key}
                      min={p.min}
                      max={p.max}
                      step={p.step}
                      value={[val]}
                      onValueChange={(next) => {
                        const v = Array.isArray(next) ? next[0] : next;
                        if (v != null) update(p.key, v);
                      }}
                    />
                    <Input
                      type="number"
                      min={p.min}
                      max={p.max}
                      step={p.step}
                      value={val}
                      onChange={(e) => {
                        const v = p.integer
                          ? parseInt(e.target.value, 10)
                          : parseFloat(e.target.value);
                        if (!isNaN(v)) update(p.key, v);
                      }}
                      className="h-7 text-xs"
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        <Separator />
        <Button
          size="lg"
          className="w-full"
          disabled={loading}
          onClick={() => onSubmit(params)}
        >
          {loading ? "Running simulation..." : "Run Simulation"}
        </Button>
      </CardContent>
    </Card>
  );
}
