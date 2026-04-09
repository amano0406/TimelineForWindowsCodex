namespace TimelineForWindowsCodex.Web.Services;

public sealed class AppPaths
{
    public AppPaths(IConfiguration configuration)
    {
        RuntimeDefaultsPath = NormalizePath(
            configuration["TIMELINE_FOR_WINDOWS_CODEX_RUNTIME_DEFAULTS"],
            "/app/config/runtime.defaults.json");
        AppDataRoot = NormalizePath(
            configuration["TIMELINE_FOR_WINDOWS_CODEX_APPDATA_ROOT"],
            "/shared/app-data");
        OutputsRoot = NormalizePath(
            configuration["TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT"],
            Path.Combine(AppDataRoot, "outputs"));
        InstanceId = $"{DateTimeOffset.UtcNow:yyyyMMddHHmmss}-{Guid.NewGuid():N}"[..24];
    }

    public string RuntimeDefaultsPath { get; }

    public string AppDataRoot { get; }

    public string OutputsRoot { get; }

    public string SettingsPath => Path.Combine(AppDataRoot, "settings.json");

    public string InstanceId { get; }

    private static string NormalizePath(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value)
            ? fallback
            : value.Trim();
}
