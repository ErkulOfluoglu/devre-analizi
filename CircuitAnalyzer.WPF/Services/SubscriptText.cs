using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;

namespace CircuitAnalyzer.WPF.Services
{
    internal static class SubscriptText
    {
        private static readonly Regex Pattern = new(
            @"(?<![\p{L}\p{N}_])(\p{L})(?:_([\p{L}\p{N}₀-₉]+)|([₀-₉]+))",
            RegexOptions.Compiled);

        public static string Plain(string text)
        {
            if (string.IsNullOrEmpty(text))
                return text ?? "";

            return Pattern.Replace(text, m => m.Groups[1].Value + ToPlainDigits(
                m.Groups[2].Success ? m.Groups[2].Value : m.Groups[3].Value));
        }

        public static IReadOnlyList<Inline> ToInlines(string text, double baseFontSize)
        {
            if (string.IsNullOrEmpty(text))
                return Array.Empty<Inline>();

            var matches = Pattern.Matches(text);
            if (matches.Count == 0)
            {
                return new Inline[] { new Run(text) };
            }

            // Çok satırlı bloklar (Sarrus) karakter genişliğiyle hizalıdır: orada boyut küçülmez
            bool aligned = text.Contains('\n');
            double subFontSize = baseFontSize > 0 && !aligned ? baseFontSize * 0.75 : baseFontSize;
            var inlines = new List<Inline>();
            int lastIndex = 0;

            foreach (Match m in matches)
            {
                int plainEnd = m.Groups[1].Index + m.Groups[1].Length;
                if (plainEnd > lastIndex)
                {
                    inlines.Add(new Run(text.Substring(lastIndex, plainEnd - lastIndex)));
                }

                // Hazır Unicode alt simge rakamları bu yazı tiplerinde çok küçük kalır: normal rakamla yazılır
                string sub = ToPlainDigits(m.Groups[2].Success ? m.Groups[2].Value : m.Groups[3].Value);
                inlines.Add(new Run(sub)
                {
                    BaselineAlignment = BaselineAlignment.Subscript,
                    FontSize = subFontSize
                });

                lastIndex = m.Index + m.Length;
            }

            if (lastIndex < text.Length)
            {
                inlines.Add(new Run(text.Substring(lastIndex)));
            }

            return inlines;
        }

        private static string ToPlainDigits(string text)
        {
            var chars = text.ToCharArray();
            for (int i = 0; i < chars.Length; i++)
            {
                if (chars[i] >= '₀' && chars[i] <= '₉')
                    chars[i] = (char)('0' + (chars[i] - '₀'));
            }
            return new string(chars);
        }

        public static void Apply(TextBlock tb)
        {
            if (tb == null)
                return;

            string? text = tb.Text;
            if (string.IsNullOrEmpty(text) || !Pattern.IsMatch(text))
                return;

            double fontSize = tb.FontSize;
            var inlines = ToInlines(text, fontSize);
            tb.Inlines.Clear();
            foreach (var inline in inlines)
            {
                tb.Inlines.Add(inline);
            }
        }
    }
}
