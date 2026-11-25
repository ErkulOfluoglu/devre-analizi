// AnalysisPanel — Terminal/düğüm ve eleman hedefi seçicileri (karşıtlık, Zener aralığı, dalga şekli) ve yardımcıları.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel
{
    public void SetAvailableNodes(IReadOnlyList<int> nodes)
    {
        string? prevPos = GetSelectedTerminal(CmbTerminalPositive);
        string? prevNeg = GetSelectedTerminal(CmbTerminalNegative);

        var nodeStrings = nodes.OrderBy(n => n).Select(n => n.ToString()).ToList();

        CmbTerminalPositive.ItemsSource = nodeStrings;
        CmbTerminalNegative.ItemsSource = nodeStrings.ToList();

        if (prevPos != null && nodeStrings.Contains(prevPos))
        {
            CmbTerminalPositive.SelectedItem = prevPos;
        }
        else
        {
            CmbTerminalPositive.SelectedItem = null;
        }

        if (prevNeg != null && nodeStrings.Contains(prevNeg))
        {
            CmbTerminalNegative.SelectedItem = prevNeg;
        }
        else if (nodeStrings.Contains("0"))
        {
            CmbTerminalNegative.SelectedItem = "0";
        }
        else
        {
            CmbTerminalNegative.SelectedItem = null;
        }
    }

    /// <summary>Karşıtlık teoreminde ölçülebilecek pasif elemanların (R, L, C) kimliklerini eleman sırasıyla döndürür.</summary>
    internal static List<string> ReciprocityTargetIds(IEnumerable<CircuitElement> elements) =>
        elements
            .Where(e => e is Resistor or Inductor or Capacitor && !string.IsNullOrWhiteSpace(e.Id))
            .Select(e => e.Id)
            .ToList();

    /// <summary>Varsayılan karşıtlık hedefi: devredeki son R/L/C elemanın kimliği (yoksa null).</summary>
    internal static string? DefaultReciprocityTarget(IEnumerable<CircuitElement> elements)
    {
        var ids = ReciprocityTargetIds(elements);
        return ids.Count > 0 ? ids[^1] : null;
    }

    /// <summary>Karşıtlık hedefini seçer: önceki seçim listede varsa korur, yoksa son R/L/C elemana düşer.</summary>
    internal static string? ResolveReciprocityTarget(IReadOnlyList<string> candidates, string? preferred)
    {
        if (candidates.Count == 0)
            return null;
        if (!string.IsNullOrEmpty(preferred) && candidates.Contains(preferred, StringComparer.Ordinal))
            return preferred;
        return candidates[^1];
    }

    public void SetAvailableReciprocityTargets(IEnumerable<CircuitElement> elements) =>
        SetAvailableReciprocityTargetIds(ReciprocityTargetIds(elements));

    public void SetAvailableReciprocityTargetIds(IReadOnlyList<string> targetIds)
    {
        if (CmbReciprocityTarget == null) return;

        string? prev = GetSelectedTerminal(CmbReciprocityTarget);
        var list = targetIds.ToList();
        CmbReciprocityTarget.ItemsSource = list;
        CmbReciprocityTarget.SelectedItem = ResolveReciprocityTarget(list, prev);
    }

    /// <summary>Zener aralığında değişebilecek elemanların (dirençler ve DC gerilim kaynakları) kimliklerini döndürür.</summary>
    internal static List<string> ZenerRangeTargetIds(IEnumerable<CircuitElement> elements) =>
        elements
            .Where(e => e is Resistor or VoltageSource && !string.IsNullOrWhiteSpace(e.Id))
            .Select(e => e.Id)
            .ToList();

    /// <summary>Zener aralığı hedefini çözer: önceki seçim listede varsa korur, yoksa boş bırakır (API yükü otomatik seçer).</summary>
    internal static string? ResolveZenerRangeTarget(IReadOnlyList<string> candidates, string? preferred)
    {
        if (string.IsNullOrEmpty(preferred))
            return null;
        return candidates.Contains(preferred, StringComparer.Ordinal) ? preferred : null;
    }

    public void SetAvailableZenerRangeTargets(IEnumerable<CircuitElement> elements) =>
        SetAvailableZenerRangeTargetIds(ZenerRangeTargetIds(elements));

    public void SetAvailableZenerRangeTargetIds(IReadOnlyList<string> targetIds)
    {
        if (CmbZenerRangeTarget == null) return;

        string? prev = GetSelectedTerminal(CmbZenerRangeTarget);
        var list = targetIds.ToList();
        string? resolved = ResolveZenerRangeTarget(list, prev);

        // ItemsSource yenilenirken SelectionChanged geçici olarak null tetikler; hedef aynı kaldıysa aralığı silme
        _suppressZenerTargetChanged = true;
        try
        {
            CmbZenerRangeTarget.ItemsSource = list;
            CmbZenerRangeTarget.SelectedItem = resolved;
            _lastZenerRangeTarget = resolved;
        }
        finally
        {
            _suppressZenerTargetChanged = false;
        }

        if (!string.Equals(prev, resolved, StringComparison.Ordinal))
            ClearZenerRangeGiven();
    }

    /// <summary>Dalga şekli çıkış elemanı adayları: yalnızca dirençler.</summary>
    internal static List<string> WaveformOutputIds(IEnumerable<CircuitElement> elements) =>
        elements
            .Where(e => e is Resistor && !string.IsNullOrWhiteSpace(e.Id))
            .Select(e => e.Id)
            .ToList();

    /// <summary>Çıkış elemanı seçimini çözer: listede varsa korur, yoksa boş bırakır (API son direnci seçer).</summary>
    internal static string? ResolveWaveformOutput(IReadOnlyList<string> candidates, string? preferred)
    {
        if (string.IsNullOrEmpty(preferred))
            return null;
        return candidates.Contains(preferred, StringComparer.Ordinal) ? preferred : null;
    }

    public void SetAvailableWaveformOutputs(IEnumerable<CircuitElement> elements) =>
        SetAvailableWaveformOutputIds(WaveformOutputIds(elements));

    public void SetAvailableWaveformOutputIds(IReadOnlyList<string> outputIds)
    {
        if (CmbWaveformOutput == null) return;

        string? prev = GetSelectedTerminal(CmbWaveformOutput);
        var list = outputIds.ToList();
        CmbWaveformOutput.ItemsSource = list;
        CmbWaveformOutput.SelectedItem = ResolveWaveformOutput(list, prev);
    }

    public void SetWaveformOutput(string? outputId)
    {
        if (CmbWaveformOutput?.ItemsSource is IEnumerable<string> items)
        {
            var list = items as IReadOnlyList<string> ?? items.ToList();
            CmbWaveformOutput.SelectedItem = ResolveWaveformOutput(list, outputId);
        }
    }

    private void CmbZenerRangeTarget_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressZenerTargetChanged) return;

        string? current = GetSelectedTerminal(CmbZenerRangeTarget);
        if (!string.Equals(_lastZenerRangeTarget, current, StringComparison.Ordinal))
        {
            _lastZenerRangeTarget = current;
            ClearZenerRangeGiven();
        }
    }

    private void TxtZenerRangeGiven_TextChanged(object sender, TextChangedEventArgs e)
    {
        SetZenerRangeGivenError(null);
    }

    private void ClearZenerRangeGiven()
    {
        if (TxtZenerRangeGivenMin != null) TxtZenerRangeGivenMin.Text = "";
        if (TxtZenerRangeGivenMax != null) TxtZenerRangeGivenMax.Text = "";
        SetZenerRangeGivenError(null);
    }

    private void SetZenerRangeGivenError(string? message)
    {
        if (TxtZenerRangeGivenError == null) return;
        if (string.IsNullOrWhiteSpace(message))
        {
            TxtZenerRangeGivenError.Text = "";
            TxtZenerRangeGivenError.Visibility = Visibility.Collapsed;
        }
        else
        {
            TxtZenerRangeGivenError.Text = message;
            TxtZenerRangeGivenError.Visibility = Visibility.Visible;
        }
    }

    /// <summary>
    /// Zener Aralığı ters problemi için isteğe bağlı [min, maks] girişini ayrıştırır.
    /// İkisi de boşsa ileri mod (null, null); biri boşsa ya da min ≥ maks ise hata döndürür.
    /// </summary>
    internal static bool TryParseZenerRangeGiven(
        string? minText,
        string? maxText,
        out double? min,
        out double? max,
        out string? error)
    {
        min = null;
        max = null;
        error = null;

        string minTrim = minText?.Trim() ?? "";
        string maxTrim = maxText?.Trim() ?? "";

        if (minTrim.Length == 0 && maxTrim.Length == 0)
            return true;

        if (minTrim.Length == 0 || maxTrim.Length == 0)
        {
            error = "Değişim aralığı için alt ve üst sınırın ikisi de girilmelidir.";
            return false;
        }

        if (!TurkishNumber.TryParseSpice(minTrim, out double parsedMin) ||
            !TurkishNumber.TryParseSpice(maxTrim, out double parsedMax))
        {
            error = "Değişim aralığı geçerli bir sayı olmalıdır (ör. 120 V, 1 kΩ).";
            return false;
        }

        if (parsedMin >= parsedMax)
        {
            error = "Alt sınır, üst sınırdan küçük olmalıdır.";
            return false;
        }

        min = parsedMin;
        max = parsedMax;
        return true;
    }

    private static string? GetSelectedTerminal(ComboBox cmb)
    {
        return cmb.SelectedItem switch
        {
            string s => string.IsNullOrWhiteSpace(s) ? null : s.Trim(),
            ComboBoxItem cbi => string.IsNullOrWhiteSpace(cbi.Content?.ToString()) ? null : cbi.Content!.ToString()!.Trim(),
            _ => !string.IsNullOrWhiteSpace(cmb.Text) ? cmb.Text.Trim() : null
        };
    }
}
