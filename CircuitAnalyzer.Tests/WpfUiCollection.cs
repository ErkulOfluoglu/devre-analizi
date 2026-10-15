using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// WPF denetimleri oluşturan test sınıfları bu koleksiyonda sırayla çalışır.
/// WPF'in tema/kaynak önbellekleri, farklı STA iş parçacıklarında aynı anda
/// ilk kez yüklenince nadiren hata veriyor (AnalysisPanelTests bir kez
/// rastgele başarısız olmuştu); UI içermeyen testler paralel kalır.
/// </summary>
[CollectionDefinition(Name)]
public class WpfUiCollection
{
    public const string Name = "WpfUi";
}
