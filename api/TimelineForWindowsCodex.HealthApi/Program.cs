using System.Text.Json;
using System.Text.Json.Nodes;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls(Environment.GetEnvironmentVariable("ASPNETCORE_URLS") ?? "http://0.0.0.0:8080");

var app = builder.Build();

app.MapGet("/health", () => Results.Json(ReadSettingsHealth()));

app.Run();

static bool ReadSettingsHealth()
{
    var settingsPath = Environment.GetEnvironmentVariable("TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH");
    if (string.IsNullOrWhiteSpace(settingsPath) || !File.Exists(settingsPath))
    {
        return false;
    }

    try
    {
        using var stream = File.OpenRead(settingsPath);
        var node = JsonNode.Parse(stream);
        if (node is not JsonObject settings)
        {
            return false;
        }

        var outputRoot = settings["outputRoot"]?.GetValue<string>();
        return !string.IsNullOrWhiteSpace(outputRoot);
    }
    catch (IOException)
    {
        return false;
    }
    catch (UnauthorizedAccessException)
    {
        return false;
    }
    catch (JsonException)
    {
        return false;
    }
    catch (InvalidOperationException)
    {
        return false;
    }
}
