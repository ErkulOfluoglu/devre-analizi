using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Kullanıcı ayarları: %AppData%\CircuitAnalyzer\settings.json
    ///
    /// Tek bir JSON nesnesi; her ayar kendi anahtarını okur/yazar, bilinmeyen
    /// anahtarlar korunur (tema kaydedilirken "tanıtım görüldü" silinmez).
    /// Okuma/yazma hataları sessizce yutulur: ayar kaydedilemezse program
    /// varsayılanlarla çalışmaya devam eder.
    /// </summary>
    public static class AppSettings
    {
        private static readonly object Gate = new();
        private const int MaxRecentFiles = 8;

        /// <summary>Ayar dosyası (testler geçici bir yol verebilir).</summary>
        public static string SettingsPath { get; set; } = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "CircuitAnalyzer", "settings.json");

        /// <summary>"System" | "Light" | "Dark"</summary>
        public static string? Theme
        {
            get => GetString("Theme");
            set => Set("Theme", value);
        }

        /// <summary>İlk açılış tanıtımı gösterildi mi (atlandıysa da true).</summary>
        public static bool OnboardingCompleted
        {
            get => GetBool("OnboardingCompleted");
            set => Set("OnboardingCompleted", value);
        }

        /// <summary>Son açılan dosyaların mutlak yolları (en fazla 8, en son açılan başta).</summary>
        public static IReadOnlyList<string> RecentFiles
        {
            get => GetRecentFiles();
            set => SetRecentFiles(value);
        }

        private static IReadOnlyList<string> GetRecentFiles()
        {
            lock (Gate)
            {
                try
                {
                    var node = Load()["RecentFiles"];
                    if (node is JsonArray arr)
                    {
                        var list = new List<string>();
                        foreach (var item in arr)
                        {
                            if (item?.GetValue<string>() is { Length: > 0 } s)
                                list.Add(s);
                        }
                        return list;
                    }
                }
                catch (Exception)
                {
                }
                return Array.Empty<string>();
            }
        }

        private static void SetRecentFiles(IEnumerable<string>? files)
        {
            lock (Gate)
            {
                var list = new List<string>();
                if (files != null)
                {
                    foreach (var f in files)
                    {
                        if (string.IsNullOrWhiteSpace(f)) continue;
                        string path = Path.GetFullPath(f);
                        if (!list.Any(p => string.Equals(p, path, StringComparison.OrdinalIgnoreCase)))
                        {
                            list.Add(path);
                            if (list.Count >= MaxRecentFiles) break;
                        }
                    }
                }
                var arr = new JsonArray();
                foreach (var p in list)
                    arr.Add(p);
                Set("RecentFiles", arr);
            }
        }

        public static void AddRecentFile(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return;
            string fullPath;
            try
            {
                fullPath = Path.GetFullPath(path);
            }
            catch
            {
                fullPath = path;
            }

            lock (Gate)
            {
                var existing = new List<string>(GetRecentFiles());
                existing.RemoveAll(p => string.Equals(p, fullPath, StringComparison.OrdinalIgnoreCase));
                existing.Insert(0, fullPath);
                if (existing.Count > MaxRecentFiles)
                    existing = existing.Take(MaxRecentFiles).ToList();

                var arr = new JsonArray();
                foreach (var p in existing)
                    arr.Add(p);
                Set("RecentFiles", arr);
            }
        }

        public static void RemoveRecentFile(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return;
            lock (Gate)
            {
                var existing = new List<string>(GetRecentFiles());
                int removed = existing.RemoveAll(p => string.Equals(p, path, StringComparison.OrdinalIgnoreCase));
                if (removed > 0)
                {
                    var arr = new JsonArray();
                    foreach (var p in existing)
                        arr.Add(p);
                    Set("RecentFiles", arr);
                }
            }
        }

        private static JsonObject Load()
        {
            try
            {
                if (File.Exists(SettingsPath) && JsonNode.Parse(File.ReadAllText(SettingsPath)) is JsonObject o)
                    return o;
            }
            catch (Exception)
            {
                // Bozuk dosya: varsayılanlarla başla (dosya bir sonraki kayıtta düzelir)
            }
            return new JsonObject();
        }

        private static string? GetString(string key)
        {
            lock (Gate)
            {
                try
                {
                    return Load()[key]?.GetValue<string>();
                }
                catch (Exception)
                {
                    return null;
                }
            }
        }

        private static bool GetBool(string key)
        {
            lock (Gate)
            {
                try
                {
                    return Load()[key]?.GetValue<bool>() ?? false;
                }
                catch (Exception)
                {
                    return false;
                }
            }
        }

        private static readonly JsonSerializerOptions JsonIndentOptions = new()
        {
            WriteIndented = true,
            TypeInfoResolver = new System.Text.Json.Serialization.Metadata.DefaultJsonTypeInfoResolver(),
        };

        private static void Set(string key, JsonNode? value)
        {
            lock (Gate)
            {
                try
                {
                    var o = Load();
                    o[key] = value;
                    Directory.CreateDirectory(Path.GetDirectoryName(SettingsPath)!);
                    File.WriteAllText(SettingsPath, o.ToJsonString(JsonIndentOptions));
                }
                catch (Exception)
                {
                    // Yazılamıyorsa (salt okunur profil) ayar yalnız bu oturumda geçerli
                }
            }
        }
    }
}
