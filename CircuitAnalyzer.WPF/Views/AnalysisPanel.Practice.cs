// AnalysisPanel — Alıştırma modu ve soru kodu yönetimi.

using System;
using System.Globalization;
using System.Threading.Tasks;
using System.Windows;
using CircuitAnalyzer.WPF.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel
{
    public bool IsPracticeMode
    {
        get => ChkPracticeMode.IsChecked == true;
        set => ChkPracticeMode.IsChecked = value;
    }

    public void SetProblemCode(int? code)
    {
        if (code is { } c)
        {
            TxtProblemCode.Text = $"Soru #{c}";
            TxtProblemCode.Visibility = Visibility.Visible;
            TxtProblemCodeBig.Text = $"Soru kodu: {c}";
            CardProblemCode.Visibility = Visibility.Visible;
            if (TxtCopyProblemCode != null)
                TxtCopyProblemCode.Text = "Kopyala";
            if (IconCopyProblemCode != null)
                IconCopyProblemCode.SetResourceReference(Icon.DataProperty, "Icon.Copy");
        }
        else
        {
            TxtProblemCode.Text = "";
            TxtProblemCode.Visibility = Visibility.Collapsed;
            CardProblemCode.Visibility = Visibility.Collapsed;
        }
        _problemCode = code;
    }

    private void BtnCopyProblemCode_Click(object sender, RoutedEventArgs e)
    {
        if (_problemCode is not { } c)
            return;
        try
        {
            Clipboard.SetText(c.ToString(CultureInfo.InvariantCulture));
            if (TxtCopyProblemCode != null)
                TxtCopyProblemCode.Text = "Kopyalandı";
            if (IconCopyProblemCode != null)
                IconCopyProblemCode.SetResourceReference(Icon.DataProperty, "Icon.Check");
        }
        catch (System.Runtime.InteropServices.COMException)
        {
            // Pano başka bir program tarafından kilitliyse sessizce geç
        }
    }

    public string? ProblemCodeText => TxtProblemCode.Visibility == Visibility.Visible ? TxtProblemCode.Text : null;

    public Func<AnswerCheckRequestDto, Task<AnswerCheckResponseDto>>? AnswerChecker { get; set; }

    public bool IsShowingPractice { get; private set; }

    public PracticeView? CurrentPracticeView { get; private set; }

    public void RevealSolution()
    {
        if (_lastPracticeResponse != null)
        {
            var resp = _lastPracticeResponse;
            _lastPracticeResponse = null;
            if (CurrentAssistantView != null && CurrentRequest != null)
            {
                CurrentAssistantView.Configure(CurrentRequest, practice: false, Array.Empty<PracticeQuestionDto>());
            }
            ShowFullResults(resp);
            SelectExplanationView(true);
            SolutionRevealed?.Invoke(this, EventArgs.Empty);
        }
    }
}
