using System.Collections.Generic;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>Alıştırma ekranının puan satırı ve yazım örneği (Fable denetimi, 3. tur).</summary>
public class PracticeScoreTests
{
    private static List<PracticeQuestionDto> Questions(bool ac = false) => new()
    {
        new() { Id = "V2", Group = "main", IsAc = ac },
        new() { Id = "I_R1", Group = "main", IsAc = ac },
        new() { Id = "P", Group = "extra", IsAc = ac },
        new() { Id = "I_R2", Group = "extra", IsAc = ac },
    };

    [Fact]
    public void Score_CountsMainAndExtraSeparately()
    {
        // Asıl soruların hepsi doğru, ek sorular yanıtlanmamış: "Doğru: 2 / 4" yazmamalı
        var correct = new HashSet<string> { "V2", "I_R1" };
        string text = PracticeView.ScoreText(Questions(), correct.Contains);
        Assert.Equal("Asıl sorular: 2 / 2 doğru · Ek sorular: 0 / 2", text);
    }

    [Fact]
    public void Score_WithoutExtraQuestions_ShowsOnlyMain()
    {
        var qs = new List<PracticeQuestionDto> { new() { Id = "V2", Group = "main" } };
        Assert.Equal("Asıl sorular: 0 / 1 doğru", PracticeView.ScoreText(qs, _ => false));
    }

    [Fact]
    public void FormatHint_ShowsPhasorExampleOnlyForAc()
    {
        Assert.DoesNotContain("∠", PracticeView.FormatHintText(Questions(ac: false)));
        Assert.Contains("∠", PracticeView.FormatHintText(Questions(ac: true)));
    }
}
