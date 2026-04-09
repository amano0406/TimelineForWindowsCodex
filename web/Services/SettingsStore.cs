using System.Text.Json;
using TimelineForWindowsCodex.Web.Models;

namespace TimelineForWindowsCodex.Web.Services;

public sealed class SettingsStore(AppPaths paths)
{
    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public async Task<AppSettingsDocument> LoadAsync(CancellationToken cancellationToken = default)
    {
        if (File.Exists(paths.SettingsPath))
        {
            await using var stream = File.OpenRead(paths.SettingsPath);
            var loaded = await JsonSerializer.DeserializeAsync<AppSettingsDocument>(
                stream,
                _jsonOptions,
                cancellationToken);
            return Normalize(loaded ?? new AppSettingsDocument());
        }

        if (File.Exists(paths.RuntimeDefaultsPath))
        {
            await using var stream = File.OpenRead(paths.RuntimeDefaultsPath);
            var defaults = await JsonSerializer.DeserializeAsync<AppSettingsDocument>(
                stream,
                _jsonOptions,
                cancellationToken);
            return Normalize(defaults ?? new AppSettingsDocument());
        }

        return Normalize(new AppSettingsDocument());
    }

    public async Task SaveAsync(AppSettingsDocument settings, CancellationToken cancellationToken = default)
    {
        var normalized = Normalize(settings);
        Directory.CreateDirectory(Path.GetDirectoryName(paths.SettingsPath)!);
        await File.WriteAllTextAsync(
            paths.SettingsPath,
            JsonSerializer.Serialize(normalized, _jsonOptions),
            cancellationToken);
    }

    private static AppSettingsDocument Normalize(AppSettingsDocument value)
    {
        value.DefaultPrimaryCodexHomePath = string.IsNullOrWhiteSpace(value.DefaultPrimaryCodexHomePath)
            ? "/input/codex-home"
            : value.DefaultPrimaryCodexHomePath.Trim();

        value.DefaultBackupCodexHomePaths = value.DefaultBackupCodexHomePaths
            .Where(static item => !string.IsNullOrWhiteSpace(item))
            .Select(static item => item.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        value.DefaultEnrichmentRootPaths = value.DefaultEnrichmentRootPaths
            .Where(static item => !string.IsNullOrWhiteSpace(item))
            .Select(static item => item.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        value.DefaultRedactionProfile = value.DefaultRedactionProfile?.Trim().ToLowerInvariant() switch
        {
            "loose" => "loose",
            _ => "strict",
        };

        value.UiLanguage = string.IsNullOrWhiteSpace(value.UiLanguage)
            ? "ja"
            : value.UiLanguage.Trim();

        value.LanguageSelected = true;
        return value;
    }
}

