using System;
using System.Collections.Generic;
using System.Linq;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Seçili elemanın cam kartında yazanlar (DESIGN.md, "Akım ışığı"): ad, değer, akım ve yönü,
    /// uçlarındaki gerilim, güç ve DC'de akımın girdiği düğümdeki akım dengesi (KCL).
    /// </summary>
    public sealed record ElementReadout(
        string Name,
        string? Value,
        string Current,
        string Direction,
        string? Voltage,
        string? Power,
        string? NodeBalance,
        string? Note = null);

    public static class ElementReadoutBuilder
    {
        /// <summary>Kart için değerleri toplar; akımı bilinmeyen eleman için null.</summary>
        public static ElementReadout? Build(
            CircuitElement element,
            IEnumerable<CircuitElement> elements,
            IReadOnlyDictionary<Pin, int> nodeMap,
            AnalysisResultsDto results,
            bool isDc)
        {
            if (!results.ElementCurrents.TryGetValue(element.Id, out var dto)
                || !CurrentFlow.TryBranch(element, nodeMap, results.ElementCurrents, out var from, out var to, out _))
                return null;

            var (currentValue, _) = CurrentDisplay.Normalize(element.Id, dto);
            int a = nodeMap[from], b = nodeMap[to];

            string? value = string.IsNullOrEmpty(element.Unit) || element.Value == 0
                ? null
                : EngFormat.Format(element.Value, element.Unit);

            string? voltage = TryNodeVoltage(results, a, out var va) && TryNodeVoltage(results, b, out var vb)
                ? EngFormat.Format(Subtract(va, vb), "V")
                : null;

            string? power = null;
            if (results.Power?.Elements.TryGetValue(element.Id, out var p) == true)
            {
                bool source = string.Equals(p.Role, "source", StringComparison.OrdinalIgnoreCase);
                power = EngFormat.Format(Math.Abs(p.ActivePower), "W") + (source ? " (verir)" : "");
            }

            // Akım dengesi yalnız DC'de: AC'de akımlar fazördür, genlikleri toplanmaz
            string? balance = isDc ? NodeBalance(a != 0 ? a : b, elements, nodeMap, results.ElementCurrents) : null;

            return new ElementReadout(
                element.Id,
                value,
                EngFormat.Format(currentValue, dto.Unit),
                $"Düğüm {a} → {b}",
                voltage,
                power,
                balance,
                isDc ? null : "AC: akım yön değiştirir; ışık bu salınımı yavaşlatarak gösterir. Faz, akımın ∠ açısıdır.");
        }

        /// <summary>"Düğüm 2: giren 33,15 mA (R1) = çıkan 26,32 mA (R3) + 6,832 mA (R5)"; eksik akım varsa null.</summary>
        public static string? NodeBalance(
            int node,
            IEnumerable<CircuitElement> elements,
            IReadOnlyDictionary<Pin, int> nodeMap,
            IReadOnlyDictionary<string, ElementCurrentDto> currents)
        {
            if (node == 0)
                return null;
            var ins = new List<string>();
            var outs = new List<string>();
            foreach (var element in elements)
            {
                if (element is GroundElement or TestProbe or JunctionElement)
                    continue;
                bool touches = element.Pins.Any(p => nodeMap.TryGetValue(p, out int n) && n == node);
                if (!touches)
                    continue;
                if (!CurrentFlow.TryBranch(element, nodeMap, currents, out var from, out var to, out double amps))
                    return null; // akımı bilinmeyen bir eleman var: denge yazılamaz
                if (amps < 1e-15)
                    continue;
                string part = $"{EngFormat.Format(amps, "A")} ({element.Id})";
                if (nodeMap[to] == node)
                    ins.Add(part);
                else if (nodeMap[from] == node)
                    outs.Add(part);
            }
            if (ins.Count == 0 || outs.Count == 0)
                return null;
            return $"Düğüm {node}: giren {string.Join(" + ", ins)} = çıkan {string.Join(" + ", outs)}";
        }

        private static bool TryNodeVoltage(AnalysisResultsDto results, int node, out ResultValue value)
        {
            if (node == 0)
            {
                value = ResultValue.FromReal(0);
                return true;
            }
            if (results.NodeVoltages.TryGetValue(node.ToString(), out var nv))
            {
                value = nv.Value;
                return true;
            }
            value = ResultValue.FromReal(0);
            return false;
        }

        // DC'de uçlar arası gerilimin büyüklüğü (yönü akım satırı söyler); AC'de fazör farkı
        private static ResultValue Subtract(ResultValue x, ResultValue y) =>
            x.IsComplex || y.IsComplex
                ? new ResultValue { Real = x.Real - y.Real, Imaginary = x.Imaginary - y.Imaginary, IsComplex = true }
                : ResultValue.FromReal(Math.Abs(x.Real - y.Real));
    }
}
