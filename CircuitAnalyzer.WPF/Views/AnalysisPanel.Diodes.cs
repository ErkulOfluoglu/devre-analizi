// AnalysisPanel — Diyot ve Zener durum/gerilim biçimlendirme yardımcıları.

using System;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel
{
    internal static string FormatDiodeModel(string? model) => (model ?? "").Trim().ToUpperInvariant() switch
    {
        "SI" => "Si",
        "GE" => "Ge",
        "IDEAL" => "İdeal",
        "ZENER" => "Zener",
        var m when !string.IsNullOrEmpty(m) => model!.Trim(),
        _ => "Si",
    };

    internal static string FormatDiodeState(string? state) => (state ?? "").Trim().ToUpperInvariant() switch
    {
        "ON" => "iletimde",
        "ZENER" => "ters iletimde (V_Z)",
        "OFF" => "yalıtımda",
        _ => state?.Trim() ?? "",
    };

    internal static string FormatDiodeLine(DiodeResultDto diode)
    {
        bool isZener = string.Equals(diode.Model?.Trim(), "ZENER", StringComparison.OrdinalIgnoreCase);
        string model = isZener && diode.Vz.HasValue
            ? $"Zener, V_Z = {FormatDiodeVoltage(diode.Vz.Value)}"
            : FormatDiodeModel(diode.Model);
        string state = FormatDiodeState(diode.State);
        string vAk = FormatDiodeVoltage(diode.VAk);
        string current = EngFormat.Format(diode.I, "A");
        string currentSymbol = isZener ? "I_Z" : "I";
        return $"{diode.Id} ({model}): {state} · V_AK = {vAk} · {currentSymbol} = {current}";
    }

    /// <summary>
    /// Diyot gerilimi kitaptaki gibi volt olarak: 0,7 V (700 mV değil), 4,3 V, −8 V.
    /// 1 mV altı ve 1000 V üstü değerler olağan önekli biçimde kalır.
    /// </summary>
    internal static string FormatDiodeVoltage(double v)
    {
        double a = Math.Abs(v);
        if (a < 1e-3 || a >= 1000 || double.IsNaN(v))
            return EngFormat.Format(v, "V");
        string s = a.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture).Replace('.', ',');
        return (v < 0 ? "−" : "") + s + " V";
    }
}
