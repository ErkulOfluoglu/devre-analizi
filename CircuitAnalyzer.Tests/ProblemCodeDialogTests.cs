using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    public class ProblemCodeDialogTests
    {
        private const string ExpectedError = "1000 ile 9999 arasında bir sayı yazın.";

        [Theory]
        [InlineData("4821", 4821)]
        [InlineData(" 1000 ", 1000)]
        [InlineData("9999", 9999)]
        public void TryParseCode_ValidInputs_ReturnTrue(string input, int expectedCode)
        {
            bool ok = ProblemCodeDialog.TryParseCode(input, out int code, out string? error);

            Assert.True(ok);
            Assert.Equal(expectedCode, code);
            Assert.Null(error);
        }

        [Theory]
        [InlineData("999")]
        [InlineData("10000")]
        [InlineData("abc")]
        [InlineData("")]
        [InlineData("12.5")]
        public void TryParseCode_InvalidInputs_ReturnFalseWithTurkishError(string input)
        {
            bool ok = ProblemCodeDialog.TryParseCode(input, out int code, out string? error);

            Assert.False(ok);
            Assert.Equal(0, code);
            Assert.Equal(ExpectedError, error);
        }
    }
}
