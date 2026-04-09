using System.Text.Json;

namespace TimelineForWindowsCodex.Web.Services;

public sealed class JsonLocalizationService(
    IWebHostEnvironment environment,
    LanguageService languageService,
    ILogger<JsonLocalizationService> logger)
{
    private readonly Lazy<IReadOnlyDictionary<string, IReadOnlyDictionary<string, string>>> _catalog =
        new(() => LoadCatalog(environment, logger));

    public string Get(string? language, string key)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            return string.Empty;
        }

        var normalized = languageService.Normalize(language) ?? "ja";
        var catalog = _catalog.Value;

        if (catalog.TryGetValue(normalized, out var localized) &&
            localized.TryGetValue(key, out var localizedValue) &&
            !string.IsNullOrWhiteSpace(localizedValue))
        {
            return localizedValue;
        }

        if (catalog.TryGetValue("en", out var english) &&
            english.TryGetValue(key, out var englishValue) &&
            !string.IsNullOrWhiteSpace(englishValue))
        {
            return englishValue;
        }

        return key;
    }

    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, string>> LoadCatalog(
        IWebHostEnvironment environment,
        ILogger<JsonLocalizationService> logger)
    {
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "Resources", "Locales"),
            Path.Combine(environment.ContentRootPath, "Resources", "Locales"),
        };

        var folder = candidates.FirstOrDefault(Directory.Exists);
        if (folder is null)
        {
            logger.LogWarning("Localization folder was not found.");
            return new Dictionary<string, IReadOnlyDictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
        }

        var result = new Dictionary<string, IReadOnlyDictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
        foreach (var file in Directory.EnumerateFiles(folder, "*.json", SearchOption.TopDirectoryOnly))
        {
            if (string.Equals(Path.GetFileName(file), "languages.json", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            try
            {
                var json = File.ReadAllText(file);
                var values = JsonSerializer.Deserialize<Dictionary<string, string>>(json)
                    ?? new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                result[Path.GetFileNameWithoutExtension(file)] =
                    new Dictionary<string, string>(values, StringComparer.OrdinalIgnoreCase);
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "Failed to load locale file {LocaleFile}", file);
            }
        }

        return result;
    }
}

