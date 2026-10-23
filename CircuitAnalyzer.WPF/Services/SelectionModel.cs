using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Tuval üzerindeki seçili devre elemanlarını ve telleri yöneten saf model sınıfı.
    /// WPF görsel nesnelerine bağımlı değildir; birim testlerde doğrudan kullanılabilir.
    /// </summary>
    public sealed class SelectionModel
    {
        private readonly List<CircuitElement> _elements = new();
        private readonly List<Wire> _wires = new();

        /// <summary>Seçili devre elemanları.</summary>
        public IReadOnlyList<CircuitElement> Elements => _elements;

        /// <summary>Seçili teller.</summary>
        public IReadOnlyList<Wire> Wires => _wires;

        /// <summary>Seçili eleman sayısı.</summary>
        public int Count => _elements.Count;

        /// <summary>En az bir eleman veya tel seçili mi?</summary>
        public bool HasSelection => _elements.Count > 0 || _wires.Count > 0;

        /// <summary>Seçim tamamen boş mu?</summary>
        public bool IsEmpty => _elements.Count == 0 && _wires.Count == 0;

        /// <summary>İlk seçili eleman (yoksa null).</summary>
        public CircuitElement? PrimaryElement => _elements.Count > 0 ? _elements[0] : null;

        /// <summary>Seçim kümesi değiştiğinde tetiklenir.</summary>
        public event EventHandler? Changed;

        /// <summary>Verilen eleman seçili mi?</summary>
        public bool IsSelected(CircuitElement? element)
            => element != null && _elements.Contains(element);

        /// <summary>Verilen tel seçili mi?</summary>
        public bool IsSelected(Wire? wire)
            => wire != null && _wires.Contains(wire);

        /// <summary>Yalnızca verilen elemanı seçer (null ise seçimi temizler).</summary>
        public void Select(CircuitElement? element)
        {
            _elements.Clear();
            _wires.Clear();
            if (element != null)
            {
                _elements.Add(element);
            }
            RaiseChanged();
        }

        /// <summary>Yalnızca verilen teli seçer (null ise seçimi temizler).</summary>
        public void Select(Wire? wire)
        {
            _elements.Clear();
            _wires.Clear();
            if (wire != null)
            {
                _wires.Add(wire);
            }
            RaiseChanged();
        }

        /// <summary>Verilen eleman ve tel kümelerini seçer.</summary>
        public void Select(IEnumerable<CircuitElement> elements, IEnumerable<Wire>? wires = null)
        {
            _elements.Clear();
            _wires.Clear();
            if (elements != null)
            {
                foreach (var el in elements)
                {
                    if (el != null && !_elements.Contains(el))
                        _elements.Add(el);
                }
            }
            if (wires != null)
            {
                foreach (var w in wires)
                {
                    if (w != null && !_wires.Contains(w))
                        _wires.Add(w);
                }
            }
            RaiseChanged();
        }

        /// <summary>Eleman seçiliyse seçimden çıkarır, değilse seçime ekler (Ctrl+tık).</summary>
        public void Toggle(CircuitElement element)
        {
            if (element == null)
                return;

            if (!_elements.Remove(element))
            {
                _elements.Add(element);
            }
            RaiseChanged();
        }

        /// <summary>Tel seçiliyse seçimden çıkarır, değilse seçime ekler.</summary>
        public void Toggle(Wire wire)
        {
            if (wire == null)
                return;

            if (!_wires.Remove(wire))
            {
                _wires.Add(wire);
            }
            RaiseChanged();
        }

        /// <summary>Tüm seçimi temizler.</summary>
        public void Clear()
        {
            _elements.Clear();
            _wires.Clear();
            RaiseChanged();
        }

        /// <summary>Verilen tüm elemanları (ve varsa telleri) seçer (Ctrl+A).</summary>
        public void SelectAll(IEnumerable<CircuitElement> elements, IEnumerable<Wire>? wires = null)
        {
            Select(elements, wires);
        }

        /// <summary>
        /// Bir elemanın dönüş açısını da hesaba katan eksen hizalı sınırlayıcı dikdörtgenini döndürür.
        /// </summary>
        public static Rect GetElementBounds(CircuitElement element)
        {
            if (element == null)
                throw new ArgumentNullException(nameof(element));

            double w = element.VisualWidth;
            double h = element.VisualHeight;
            double normRot = ((element.Rotation % 360) + 360) % 360;

            if (Math.Abs(normRot - 90) < 0.01 || Math.Abs(normRot - 270) < 0.01)
            {
                double cx = element.Position.X + w / 2.0;
                double cy = element.Position.Y + h / 2.0;
                return new Rect(cx - h / 2.0, cy - w / 2.0, h, w);
            }

            return new Rect(element.Position.X, element.Position.Y, w, h);
        }

        /// <summary>
        /// Dikdörtgen seçim testi: sınırlayıcı kutusu dikdörtgenle kesişen elemanları
        /// ve her iki ucu da dikdörtgenin içinde kalan telleri döndürür.
        /// </summary>
        public static (List<CircuitElement> Elements, List<Wire> Wires) HitTest(
            Rect rect,
            IEnumerable<CircuitElement> elements,
            IEnumerable<Wire>? wires = null)
        {
            var hitElements = new List<CircuitElement>();
            if (elements != null)
            {
                foreach (var el in elements)
                {
                    if (el != null && rect.IntersectsWith(GetElementBounds(el)))
                    {
                        hitElements.Add(el);
                    }
                }
            }

            var hitWires = new List<Wire>();
            if (wires != null)
            {
                foreach (var w in wires)
                {
                    if (w?.StartPin != null && w.EndPin != null &&
                        rect.Contains(w.StartPin.AbsolutePosition) &&
                        rect.Contains(w.EndPin.AbsolutePosition))
                    {
                        hitWires.Add(w);
                    }
                }
            }

            return (hitElements, hitWires);
        }

        /// <summary>
        /// Verilen dikdörtgenin isabet ettiği elemanları ve telleri seçer.
        /// additive true ise mevcut seçime ekler (Ctrl+sürükle), false ise mevcut seçimi değiştirir.
        /// </summary>
        public void SelectInRect(
            Rect rect,
            IEnumerable<CircuitElement> elements,
            IEnumerable<Wire>? wires = null,
            bool additive = false)
        {
            var (hitElements, hitWires) = HitTest(rect, elements, wires);

            if (!additive)
            {
                _elements.Clear();
                _wires.Clear();
            }

            foreach (var el in hitElements)
            {
                if (!_elements.Contains(el))
                    _elements.Add(el);
            }

            foreach (var w in hitWires)
            {
                if (!_wires.Contains(w))
                    _wires.Add(w);
            }

            RaiseChanged();
        }

        private void RaiseChanged() => Changed?.Invoke(this, EventArgs.Empty);
    }
}
