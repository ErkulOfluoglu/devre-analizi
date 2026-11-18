using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Gerçek süreç açıp kapatan testler (uyuyan python süreçleri, gerçek çözücü) bu koleksiyonda,
/// diğer bütün testler bittikten sonra tek başına çalışır. Tam paket paralel koşarken bu testler
/// ara sıra zamanlama yüzünden başarısız oluyordu; tek başına çalıştırıldıklarında hiç olmadı.
/// </summary>
[CollectionDefinition(Name, DisableParallelization = true)]
public class RealProcessCollection
{
    public const string Name = "GercekSurecler";
}
