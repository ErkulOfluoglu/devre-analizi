namespace CircuitAnalyzer.WPF.Views;

public enum BackendState
{
    Starting,
    Ready,
    Failed
}

public sealed record SolveOptions(
    string AnalysisType,
    double? Frequency,
    string? TerminalPositive,
    string TerminalNegative,
    string ValueDisplay = "RMS",
    double? PowerFactorTarget = null,
    string? ReciprocityTarget = null,
    string? ZenerRangeTarget = null,
    double? ZenerRangeGivenMin = null,
    double? ZenerRangeGivenMax = null);
