using System.Text.Json;

namespace TimelineForWindowsCodex.Web.Services;

public sealed record SupportedLanguage(string Code, string NativeName);

internal sealed record LanguageDefinition(string Code, string NativeName, IReadOnlyList<string> Aliases);

internal sealed record LanguageCatalog(string DefaultLanguage, IReadOnlyList<LanguageDefinition> Definitions);

public sealed class LanguageService(
    IWebHostEnvironment environment,
    AppPaths paths,
    ILogger<LanguageService> logger)
{
    private readonly Lazy<LanguageCatalog> _catalog = new(() => LoadCatalog(environment, logger));

    public IReadOnlyList<SupportedLanguage> GetSupportedLanguages() =>
        _catalog.Value.Definitions.Select(static item => new SupportedLanguage(item.Code, item.NativeName)).ToArray();

    public string Resolve(HttpRequest request)
    {
        var fromQuery = Normalize(request.Query["lang"].ToString());
        if (fromQuery is not null)
        {
            return fromQuery;
        }

        var fromSettings = LoadSavedLanguage(paths, logger);
        if (fromSettings is not null)
        {
            return fromSettings;
        }

        return _catalog.Value.DefaultLanguage;
    }

    public string? Normalize(string? language)
    {
        if (string.IsNullOrWhiteSpace(language))
        {
            return null;
        }

        var lower = language.Trim().ToLowerInvariant();
        foreach (var definition in _catalog.Value.Definitions)
        {
            if (lower.Equals(definition.Code.ToLowerInvariant(), StringComparison.Ordinal))
            {
                return definition.Code;
            }

            foreach (var alias in definition.Aliases)
            {
                var normalizedAlias = alias.Trim().ToLowerInvariant();
                if (lower.Equals(normalizedAlias, StringComparison.Ordinal) ||
                    lower.StartsWith($"{normalizedAlias}-", StringComparison.Ordinal))
                {
                    return definition.Code;
                }
            }
        }

        return null;
    }

    private static LanguageCatalog LoadCatalog(IWebHostEnvironment environment, ILogger<LanguageService> logger)
    {
        var path = ResolveCatalogPath(environment);
        if (path is null)
        {
            logger.LogWarning("Language catalog was not found. Falling back to built-in defaults.");
            return GetDefaultCatalog();
        }

        try
        {
            var json = File.ReadAllText(path);
            var definition = JsonSerializer.Deserialize<LanguageCatalogDocument>(json);
            if (definition?.Languages is { Count: > 0 })
            {
                var languages = definition.Languages
                    .Where(static item => !string.IsNullOrWhiteSpace(item.Code) && !string.IsNullOrWhiteSpace(item.NativeName))
                    .Select(static item => new LanguageDefinition(
                        item.Code,
                        item.NativeName,
                        item.Aliases?.Where(static alias => !string.IsNullOrWhiteSpace(alias)).ToArray()
                            ?? [item.Code]))
                    .ToArray();

                if (languages.Length > 0)
                {
                    var defaultLanguage = languages.Any(item => string.Equals(item.Code, definition.DefaultLanguage, StringComparison.OrdinalIgnoreCase))
                        ? languages.First(item => string.Equals(item.Code, definition.DefaultLanguage, StringComparison.OrdinalIgnoreCase)).Code
                        : languages[0].Code;
                    return new LanguageCatalog(defaultLanguage, languages);
                }
            }
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Failed to load language catalog from {LanguageCatalogPath}", path);
        }

        return GetDefaultCatalog();
    }

    private static string? ResolveCatalogPath(IWebHostEnvironment environment)
    {
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "Resources", "Locales", "languages.json"),
            Path.Combine(environment.ContentRootPath, "Resources", "Locales", "languages.json"),
        };

        return candidates.FirstOrDefault(File.Exists);
    }

    private static LanguageCatalog GetDefaultCatalog() =>
        new(
            "ja",
            [
                new("ja", "日本語", ["ja"]),
                new("en", "English", ["en"]),
            ]);

    private static string? LoadSavedLanguage(AppPaths paths, ILogger<LanguageService> logger)
    {
        if (!File.Exists(paths.SettingsPath))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(paths.SettingsPath));
            if (document.RootElement.TryGetProperty("ui_language", out var value) &&
                value.ValueKind == JsonValueKind.String)
            {
                return value.GetString();
            }
        }
        catch (Exception ex)
        {
            logger.LogDebug(ex, "Failed to read saved language from {SettingsPath}", paths.SettingsPath);
        }

        return null;
    }
}

internal sealed class LanguageCatalogDocument
{
    public string DefaultLanguage { get; set; } = "ja";
    public List<LanguageCatalogLanguageDocument> Languages { get; set; } = [];
}

internal sealed class LanguageCatalogLanguageDocument
{
    public string Code { get; set; } = string.Empty;
    public string NativeName { get; set; } = string.Empty;
    public List<string>? Aliases { get; set; }
}

