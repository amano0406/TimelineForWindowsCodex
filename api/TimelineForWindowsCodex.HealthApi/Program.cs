using System.Diagnostics;
using System.Globalization;
using System.IO.Compression;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

var paths = ProductPaths.Resolve(args);
var bindPort = ProductPaths.ReadPort(args, paths.SettingsPath, 19200);

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton(paths);
builder.Services.AddSingleton<ProductCommandRunner>();
if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ASPNETCORE_URLS")))
{
    builder.WebHost.UseUrls($"http://127.0.0.1:{bindPort}");
}

var app = builder.Build();

app.MapGet("/health", () => Results.Json(IsHealthy(paths)));

var items = app.MapGroup("/items");

items.MapPost("/refresh", async (
    HttpContext context,
    ProductCommandRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildItemsRefreshArguments(request),
            TimeSpan.FromSeconds(900),
            cancellationToken);
    });
});

items.MapPost("/list", async (
    HttpContext context,
    ProductCommandRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildPagedArguments(request, "items", "list"),
            TimeSpan.FromSeconds(120),
            cancellationToken);
    });
});

items.MapPost("/detail", async (
    HttpContext context,
    ProductPaths paths,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await BuildItemsDetailResponseAsync(
            paths,
            request,
            ["thread_id", "conversation_id", "item_id", "id"],
            cancellationToken);
    });
});

items.MapPost("/download", async (
    HttpContext context,
    ProductPaths paths,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await BuildItemsDownloadResponseAsync(paths, request, cancellationToken);
    });
});

items.MapPost("/remove", async (
    HttpContext context,
    ProductPaths paths,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await BuildItemsRemoveResponseAsync(paths, request, cancellationToken);
    });
});

var settings = app.MapGroup("/settings");

settings.MapPost("/status", async (
    HttpContext context,
    ProductPaths paths,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        _ = await ReadJsonObjectAsync(context, cancellationToken);
        return await BuildSettingsStatusResponseAsync(paths, cancellationToken);
    });
});

settings.MapPost("/init", async (
    HttpContext context,
    ProductPaths paths,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        var force = GetBoolAny(request, ["force"], false);
        if (File.Exists(paths.SettingsPath) && !force)
        {
            return new JsonObject
            {
                ["ok"] = true,
                ["settingsPath"] = paths.SettingsPath,
                ["created"] = false,
            };
        }

        var settingsDirectory = Path.GetDirectoryName(paths.SettingsPath);
        if (!string.IsNullOrEmpty(settingsDirectory))
        {
            Directory.CreateDirectory(settingsDirectory);
        }

        if (File.Exists(paths.SettingsExamplePath))
        {
            File.Copy(paths.SettingsExamplePath, paths.SettingsPath, overwrite: true);
        }
        else
        {
            await File.WriteAllTextAsync(
                paths.SettingsPath,
                """
                {
                  "schemaVersion": 1,
                  "runtime": {
                    "instanceName": "",
                    "apiPort": 19200
                  },
                  "sourceRoot": "C:\\Users\\amano\\.codex",
                  "outputRoot": "C:\\TimelineData\\windows-codex"
                }
                """,
                cancellationToken);
        }

        return new JsonObject
        {
            ["ok"] = true,
            ["settingsPath"] = paths.SettingsPath,
            ["created"] = true,
        };
    });
});

app.Run();

static bool IsHealthy(ProductPaths paths)
{
    if (!File.Exists(paths.DockerComposePath) || !File.Exists(paths.SettingsPath))
    {
        return false;
    }

    try
    {
        using var stream = File.OpenRead(paths.SettingsPath);
        var node = JsonNode.Parse(stream);
        if (node is not JsonObject settings)
        {
            return false;
        }

        var outputRoot = settings["outputRoot"]?.GetValue<string>();
        return !string.IsNullOrWhiteSpace(outputRoot);
    }
    catch
    {
        return false;
    }
}

static async Task<IResult> ExecuteJsonEndpointAsync(Func<Task<JsonNode?>> operation)
{
    try
    {
        return Results.Json(await operation());
    }
    catch (ProductCommandException ex)
    {
        return Results.Json(
            ex.Payload ?? ErrorPayload(ex.Message),
            statusCode: StatusCodes.Status500InternalServerError);
    }
    catch (Exception ex) when (ex is not OperationCanceledException)
    {
        return Results.Json(
            ErrorPayload(ex.Message),
            statusCode: StatusCodes.Status500InternalServerError);
    }
}

static async Task<JsonObject?> ReadJsonObjectAsync(HttpContext context, CancellationToken cancellationToken)
{
    if (context.Request.ContentLength == 0)
    {
        return null;
    }

    try
    {
        return await context.Request.ReadFromJsonAsync<JsonObject>(cancellationToken: cancellationToken);
    }
    catch (JsonException ex)
    {
        throw new InvalidOperationException($"Invalid JSON request body: {ex.Message}", ex);
    }
}

static IReadOnlyList<string> BuildItemsRefreshArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "items",
        "refresh",
        "--json",
    };
    AddOptionalValue(arguments, "--download-to", GetStringAny(request, ["downloadTo", "download_to", "to"]));
    return arguments;
}

static IReadOnlyList<string> BuildPagedArguments(JsonObject? request, string command, string subcommand)
{
    var arguments = new List<string>
    {
        command,
        subcommand,
        "--json",
    };
    AddOptionalInt(arguments, "--page", GetIntAny(request, ["page"]));
    AddOptionalInt(arguments, "--page-size", GetIntAny(request, ["pageSize", "page_size"]));
    return arguments;
}

static async Task<JsonObject> BuildItemsDownloadResponseAsync(
    ProductPaths paths,
    JsonObject? request,
    CancellationToken cancellationToken)
{
    var outputRoot = await ResolveOutputRootAsync(paths, cancellationToken);
    var itemIds = GetStringArrayAny(request, ["itemIds", "item_ids", "itemId", "item_id"]);
    var rows = await CollectMasterItemsAsync(outputRoot, itemIds, cancellationToken);
    if (rows.Count == 0)
    {
        throw new FileNotFoundException($"No master items were found. Run items refresh first: {outputRoot}");
    }

    var destinationText = GetStringAny(request, ["to", "downloadTo", "download_to", "outputPath", "output_path"]);
    if (string.IsNullOrWhiteSpace(destinationText))
    {
        throw new InvalidOperationException("Download destination is required.");
    }

    var destinationRoot = Path.GetFullPath(destinationText.Trim());
    Directory.CreateDirectory(destinationRoot);
    var archivePath = Path.Combine(destinationRoot, $"TimelineForWindowsCodex-export-{DateTime.Now:yyyyMMdd-HHmmss}.zip");
    var overwrite = GetBoolAny(request, ["overwrite"], false);
    if (File.Exists(archivePath))
    {
        if (!overwrite)
        {
            throw new IOException($"Destination already exists. Pass overwrite to replace it: {archivePath}");
        }
        File.Delete(archivePath);
    }

    using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
    {
        AddTextEntry(archive, "README.md", BuildWindowsCodexDownloadReadme(rows));
        foreach (var row in rows)
        {
            var itemDirName = GetStringAny(row, ["item_dir_name", "itemDirName"]);
            archive.CreateEntryFromFile(
                GetStringAny(row, ["convert_info_path", "convertInfoPath"]),
                $"items/{itemDirName}/convert_info.json");
            archive.CreateEntryFromFile(
                GetStringAny(row, ["timeline_path", "timelinePath"]),
                $"items/{itemDirName}/timeline.json");
        }
    }

    return new JsonObject
    {
        ["schema_version"] = 1,
        ["state"] = "completed",
        ["destination_path"] = archivePath,
        ["master_root"] = outputRoot,
        ["thread_count"] = rows.Count,
        ["item_count"] = rows.Count,
        ["message_count"] = rows.Sum(row => GetIntAny(row, ["message_count", "messageCount"]) ?? 0),
        ["attachment_count"] = rows.Sum(row => GetIntAny(row, ["attachment_count", "attachmentCount"]) ?? 0),
        ["items"] = CloneArray(rows),
    };
}

static async Task<JsonObject> BuildItemsRemoveResponseAsync(
    ProductPaths paths,
    JsonObject? request,
    CancellationToken cancellationToken)
{
    var outputRoot = await ResolveOutputRootAsync(paths, cancellationToken);
    var itemIds = GetStringArrayAny(request, ["itemIds", "item_ids", "itemId", "item_id"]);
    if (itemIds.Count == 0)
    {
        throw new InvalidOperationException("Pass at least one item id to remove master items.");
    }

    var rows = await CollectMasterItemsAsync(outputRoot, itemIds, cancellationToken);
    var root = Path.GetFullPath(outputRoot);
    var rootPrefix = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
    var removed = new JsonArray();
    var totalMessages = 0;
    var totalAttachments = 0;
    foreach (var row in rows)
    {
        var itemDirName = GetStringAny(row, ["item_dir_name", "itemDirName"]);
        var itemDirectory = Path.GetFullPath(Path.Combine(outputRoot, itemDirName));
        if (!itemDirectory.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException($"Refusing to remove item outside master root: {itemDirectory}");
        }

        Directory.Delete(itemDirectory, recursive: true);
        totalMessages += GetIntAny(row, ["message_count", "messageCount"]) ?? 0;
        totalAttachments += GetIntAny(row, ["attachment_count", "attachmentCount"]) ?? 0;
        removed.Add(new JsonObject
        {
            ["thread_id"] = GetStringAny(row, ["thread_id", "threadId"]),
            ["item_dir_name"] = itemDirName,
            ["title"] = GetStringAny(row, ["title"]),
        });
    }

    return new JsonObject
    {
        ["schema_version"] = 1,
        ["state"] = "completed",
        ["master_root"] = outputRoot,
        ["removed_count"] = rows.Count,
        ["item_count"] = rows.Count,
        ["message_count"] = totalMessages,
        ["attachment_count"] = totalAttachments,
        ["items"] = removed,
    };
}

static async Task<JsonObject> BuildSettingsStatusResponseAsync(
    ProductPaths paths,
    CancellationToken cancellationToken)
{
    var outputRoot = await ResolveOutputRootAsync(paths, cancellationToken);
    return new JsonObject
    {
        ["settings_path"] = paths.SettingsPath,
        ["outputRoot"] = outputRoot,
        ["outputs_root"] = outputRoot,
    };
}

static async Task<JsonObject> BuildItemsDetailResponseAsync(
    ProductPaths paths,
    JsonObject? request,
    string[] itemIdNames,
    CancellationToken cancellationToken)
{
    var requestedItemId = GetStringAny(
        request,
        ["itemId", "item_id", "threadId", "thread_id", "conversationId", "conversation_id", "id"]);
    if (string.IsNullOrWhiteSpace(requestedItemId))
    {
        return NewUnavailableThreadDetail(
            string.Empty,
            string.Empty,
            string.Empty,
            string.Empty,
            "Item id is required.");
    }

    var outputRoot = await ResolveOutputRootAsync(paths, cancellationToken);
    if (string.IsNullOrWhiteSpace(outputRoot) || !Directory.Exists(outputRoot))
    {
        return NewUnavailableThreadDetail(
            requestedItemId,
            outputRoot,
            string.Empty,
            string.Empty,
            "Output directory is not configured.");
    }

    string itemDirectory;
    try
    {
        itemDirectory = GetSafeChildDirectory(outputRoot, requestedItemId);
    }
    catch (InvalidOperationException ex)
    {
        return NewUnavailableThreadDetail(
            requestedItemId,
            outputRoot,
            string.Empty,
            string.Empty,
            ex.Message);
    }

    var timelinePath = Path.Combine(itemDirectory, "timeline.json");
    var convertInfoPath = Path.Combine(itemDirectory, "convert_info.json");
    if (!File.Exists(timelinePath))
    {
        return NewUnavailableThreadDetail(
            requestedItemId,
            itemDirectory,
            timelinePath,
            convertInfoPath,
            "Thread was not found.");
    }

    var timeline = await ReadJsonFileAsync(timelinePath, cancellationToken);
    if (timeline is null)
    {
        return NewUnavailableThreadDetail(
            requestedItemId,
            itemDirectory,
            timelinePath,
            convertInfoPath,
            "Thread could not be read.",
            requestedItemId);
    }

    var messages = new JsonArray();
    var index = 0;
    foreach (var messageNode in GetArray(timeline, "messages"))
    {
        if (messageNode is JsonObject message)
        {
            messages.Add(ConvertThreadMessage(message, index));
        }

        index++;
    }

    var itemId = GetStringAnyOrDefault(timeline, itemIdNames, requestedItemId);
    var title = GetStringAnyOrDefault(timeline, ["title"], itemId);

    return new JsonObject
    {
        ["available"] = true,
        ["itemId"] = itemId,
        ["title"] = title,
        ["createdAt"] = GetStringAny(timeline, ["created_at", "createdAt"]),
        ["updatedAt"] = GetStringAny(timeline, ["updated_at", "updatedAt"]),
        ["messageCount"] = messages.Count,
        ["messages"] = messages,
        ["directoryPath"] = itemDirectory,
        ["timelinePath"] = timelinePath,
        ["convertInfoPath"] = convertInfoPath,
        ["message"] = string.Empty,
    };
}

static async Task<string> ResolveOutputRootAsync(ProductPaths paths, CancellationToken cancellationToken)
{
    var settings = await ReadJsonFileAsync(paths.SettingsPath, cancellationToken);
    var outputRootNode = GetNode(settings, "outputRoot");
    var outputRoot = outputRootNode is JsonObject outputRootObject
        ? GetStringAny(outputRootObject, ["path", "displayPath", "value"])
        : ConvertJsonText(outputRootNode);

    if (string.IsNullOrWhiteSpace(outputRoot))
    {
        return string.Empty;
    }

    return Path.GetFullPath(Path.IsPathRooted(outputRoot)
        ? outputRoot
        : Path.Combine(paths.ProductRoot, outputRoot));
}

static async Task<JsonObject?> ReadJsonFileAsync(string path, CancellationToken cancellationToken)
{
    if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
    {
        return null;
    }

    try
    {
        await using var stream = File.OpenRead(path);
        return await JsonNode.ParseAsync(stream, cancellationToken: cancellationToken) as JsonObject;
    }
    catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
    {
        return null;
    }
}

static async Task<List<JsonObject>> CollectMasterItemsAsync(
    string outputRoot,
    List<string> selectedItemIds,
    CancellationToken cancellationToken)
{
    if (string.IsNullOrWhiteSpace(outputRoot) || !Directory.Exists(outputRoot))
    {
        return [];
    }

    var selected = selectedItemIds
        .SelectMany(item => item.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        .Where(item => !string.IsNullOrWhiteSpace(item))
        .Select(item => item.ToLowerInvariant())
        .ToHashSet(StringComparer.OrdinalIgnoreCase);
    var rows = new List<JsonObject>();
    foreach (var itemDirectory in Directory.EnumerateDirectories(outputRoot).OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
    {
        cancellationToken.ThrowIfCancellationRequested();
        var convertInfoPath = Path.Combine(itemDirectory, "convert_info.json");
        var timelinePath = Path.Combine(itemDirectory, "timeline.json");
        if (!File.Exists(convertInfoPath) || !File.Exists(timelinePath))
        {
            continue;
        }

        var convertInfo = await ReadJsonFileAsync(convertInfoPath, cancellationToken) ?? new JsonObject();
        var timeline = await ReadJsonFileAsync(timelinePath, cancellationToken) ?? new JsonObject();
        var itemDirName = Path.GetFileName(itemDirectory);
        var threadId = GetStringAnyOrDefault(convertInfo, ["thread_id", "threadId"], itemDirName);
        if (selected.Count > 0
            && !selected.Contains(threadId.ToLowerInvariant())
            && !selected.Contains(itemDirName.ToLowerInvariant()))
        {
            continue;
        }

        rows.Add(new JsonObject
        {
            ["thread_id"] = threadId,
            ["item_dir_name"] = itemDirName,
            ["title"] = GetStringAnyOrDefault(timeline, ["title"], threadId),
            ["message_count"] = ResolveMessageCount(convertInfo, timeline),
            ["attachment_count"] = ResolveAttachmentCount(convertInfo, timeline),
            ["convert_info_path"] = convertInfoPath,
            ["timeline_path"] = timelinePath,
        });
    }

    if (selected.Count > 0)
    {
        var found = rows
            .SelectMany(row => new[]
            {
                GetStringAny(row, ["thread_id", "threadId"]),
                GetStringAny(row, ["item_dir_name", "itemDirName"]),
            })
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Select(value => value.ToLowerInvariant())
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var missing = selected.Where(item => !found.Contains(item)).OrderBy(item => item, StringComparer.OrdinalIgnoreCase).ToList();
        if (missing.Count > 0)
        {
            throw new InvalidOperationException($"Unknown item ids in master: {string.Join(", ", missing)}");
        }
    }

    return rows;
}

static int ResolveMessageCount(JsonObject convertInfo, JsonObject timeline)
    => GetIntAny(convertInfo, ["message_count", "messageCount"])
        ?? GetArray(timeline, "messages").Count;

static int ResolveAttachmentCount(JsonObject convertInfo, JsonObject timeline)
{
    var fromConvert = GetIntAny(convertInfo, ["attachment_count", "attachmentCount"]);
    if (fromConvert is not null)
    {
        return fromConvert.Value;
    }

    var total = 0;
    foreach (var message in GetArray(timeline, "messages").OfType<JsonObject>())
    {
        total += GetArray(message, "attachments").Count;
    }

    return total;
}

static JsonArray CloneArray(IEnumerable<JsonObject> rows)
{
    var array = new JsonArray();
    foreach (var row in rows)
    {
        array.Add(row.DeepClone());
    }

    return array;
}

static string BuildWindowsCodexDownloadReadme(List<JsonObject> rows)
{
    var messageCount = rows.Sum(row => GetIntAny(row, ["message_count", "messageCount"]) ?? 0);
    return string.Join(
        "\n",
        [
            "# TimelineForWindowsCodex Export",
            "",
            "This package was generated by TimelineForWindowsCodex.",
            "",
            "It contains normalized Windows Codex thread items converted from local Codex Desktop history.",
            "",
            $"- Item count: {rows.Count}",
            $"- Message count: {messageCount}",
            "",
            "## Layout",
            "",
            "- `items/<thread_id>/convert_info.json`: conversion metadata",
            "- `items/<thread_id>/timeline.json`: normalized user/assistant/system messages",
            "",
        ]);
}

static void AddTextEntry(ZipArchive archive, string name, string text)
{
    var entry = archive.CreateEntry(name);
    using var stream = entry.Open();
    using var writer = new StreamWriter(stream, new UTF8Encoding(false));
    writer.Write(text);
}

static List<JsonNode?> GetArray(JsonObject? source, string name)
{
    var node = GetNode(source, name);
    return node is JsonArray array ? array.ToList() : [];
}

static JsonObject ConvertThreadMessage(JsonObject message, int index)
    => new()
    {
        ["index"] = index,
        ["role"] = GetStringAny(message, ["role"]),
        ["createdAt"] = GetStringAny(message, ["created_at", "createdAt"]),
        ["text"] = GetStringAny(message, ["text"]),
    };

static JsonObject NewUnavailableThreadDetail(
    string itemId,
    string directoryPath,
    string timelinePath,
    string convertInfoPath,
    string message,
    string title = "")
    => new()
    {
        ["available"] = false,
        ["itemId"] = itemId,
        ["title"] = title,
        ["createdAt"] = string.Empty,
        ["updatedAt"] = string.Empty,
        ["messageCount"] = 0,
        ["messages"] = new JsonArray(),
        ["directoryPath"] = directoryPath,
        ["timelinePath"] = timelinePath,
        ["convertInfoPath"] = convertInfoPath,
        ["message"] = message,
    };

static string GetSafeChildDirectory(string rootPath, string childName)
{
    var fullRoot = Path.GetFullPath(rootPath);
    var safeRootPrefix = fullRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
    var normalizedChild = childName.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
    var fullCandidate = Path.GetFullPath(Path.Combine(fullRoot, normalizedChild));
    if (!fullCandidate.StartsWith(safeRootPrefix, StringComparison.OrdinalIgnoreCase))
    {
        throw new InvalidOperationException("Invalid item id.");
    }

    return fullCandidate;
}

static JsonObject ErrorPayload(string message)
{
    return new JsonObject
    {
        ["ok"] = false,
        ["error"] = new JsonObject
        {
            ["message"] = message,
        },
    };
}

static void AddOptionalValue(List<string> arguments, string name, string value)
{
    if (string.IsNullOrWhiteSpace(value))
    {
        return;
    }

    arguments.Add(name);
    arguments.Add(value.Trim());
}

static void AddOptionalInt(List<string> arguments, string name, int? value)
{
    if (value is not > 0)
    {
        return;
    }

    arguments.Add(name);
    arguments.Add(value.Value.ToString(CultureInfo.InvariantCulture));
}

static List<string> GetStringArrayAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var values = GetStringArray(source, name);
        if (values.Count > 0)
        {
            return values;
        }
    }

    return [];
}

static List<string> GetStringArray(JsonObject? source, string name)
{
    var node = GetNode(source, name);
    if (node is null)
    {
        return [];
    }
    if (node is JsonArray array)
    {
        return array
            .Select(ConvertJsonText)
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .ToList();
    }

    var text = ConvertJsonText(node);
    if (string.IsNullOrWhiteSpace(text))
    {
        return [];
    }

    return text
        .Replace("\r", ",", StringComparison.Ordinal)
        .Replace("\n", ",", StringComparison.Ordinal)
        .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Where(value => !string.IsNullOrWhiteSpace(value))
        .ToList();
}

static string GetStringAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is not null)
        {
            return ConvertJsonText(node);
        }
    }

    return string.Empty;
}

static string GetStringAnyOrDefault(JsonObject? source, string[] names, string fallback)
{
    var value = GetStringAny(source, names);
    return string.IsNullOrEmpty(value) ? fallback : value;
}

static int? GetIntAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is null)
        {
            continue;
        }

        if (node is JsonValue value)
        {
            if (value.TryGetValue<int>(out var intValue))
            {
                return intValue;
            }
            if (value.TryGetValue<string>(out var textValue)
                && int.TryParse(textValue, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed))
            {
                return parsed;
            }
        }
    }

    return null;
}

static bool GetBoolAny(JsonObject? source, string[] names, bool fallback)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is not JsonValue value)
        {
            continue;
        }

        if (value.TryGetValue<bool>(out var boolValue))
        {
            return boolValue;
        }
        if (value.TryGetValue<string>(out var textValue))
        {
            var text = textValue.Trim().ToLowerInvariant();
            if (text is "1" or "true" or "yes" or "on")
            {
                return true;
            }
            if (text is "0" or "false" or "no" or "off")
            {
                return false;
            }
        }
    }

    return fallback;
}

static JsonNode? GetNode(JsonObject? source, string name)
{
    if (source is null)
    {
        return null;
    }
    if (source.TryGetPropertyValue(name, out var node))
    {
        return node;
    }

    foreach (var property in source)
    {
        if (property.Key.Equals(name, StringComparison.OrdinalIgnoreCase))
        {
            return property.Value;
        }
    }

    return null;
}

static string ConvertJsonText(JsonNode? node)
{
    if (node is null)
    {
        return string.Empty;
    }
    if (node is JsonValue value)
    {
        if (value.TryGetValue<string>(out var text))
        {
            return text.Trim();
        }
        if (value.TryGetValue<int>(out var intValue))
        {
            return intValue.ToString(CultureInfo.InvariantCulture);
        }
        if (value.TryGetValue<bool>(out var boolValue))
        {
            return boolValue ? "true" : "false";
        }
    }

    return node.ToJsonString();
}

public sealed record ProductPaths(
    string ProductRoot,
    string SettingsPath,
    string SettingsExamplePath,
    string DockerComposePath)
{
    public static ProductPaths Resolve(string[] args)
    {
        var productRoot = ArgValue(args, "--product-root");
        if (string.IsNullOrWhiteSpace(productRoot))
        {
            productRoot = Environment.GetEnvironmentVariable("TIMELINE_FOR_WINDOWS_CODEX_PRODUCT_ROOT");
        }
        if (string.IsNullOrWhiteSpace(productRoot))
        {
            productRoot = Directory.GetCurrentDirectory();
        }

        productRoot = Path.GetFullPath(productRoot);
        var settingsPath = Environment.GetEnvironmentVariable("TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH")
            ?? Environment.GetEnvironmentVariable("HOST_TFWC_SETTINGS_FILE")
            ?? Path.Combine(productRoot, "settings.json");
        if (!Path.IsPathRooted(settingsPath))
        {
            settingsPath = Path.Combine(productRoot, settingsPath);
        }

        return new ProductPaths(
            productRoot,
            Path.GetFullPath(settingsPath),
            Path.Combine(productRoot, "settings.example.json"),
            Path.Combine(productRoot, "docker-compose.yml"));
    }

    public static int ReadPort(string[] args, string settingsPath, int fallback)
    {
        var configured = ArgValue(args, "--port")
            ?? Environment.GetEnvironmentVariable("TIMELINE_FOR_WINDOWS_CODEX_API_PORT")
            ?? ReadApiPort(settingsPath);

        return int.TryParse(configured, NumberStyles.Integer, CultureInfo.InvariantCulture, out var port)
            && port is >= 1 and <= 65535
            ? port
            : fallback;
    }

    public static string? ArgValue(string[] args, string name)
    {
        for (var index = 0; index < args.Length; index += 1)
        {
            if (args[index].Equals(name, StringComparison.OrdinalIgnoreCase)
                && index + 1 < args.Length)
            {
                return args[index + 1];
            }
            if (args[index].StartsWith(name + "=", StringComparison.OrdinalIgnoreCase))
            {
                return args[index][(name.Length + 1)..];
            }
        }

        return null;
    }

    private static string? ReadApiPort(string settingsPath)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(settingsPath));
            if (document.RootElement.TryGetProperty("runtime", out var runtime)
                && runtime.ValueKind == JsonValueKind.Object
                && runtime.TryGetProperty("apiPort", out var apiPort))
            {
                return apiPort.ValueKind == JsonValueKind.Number
                    ? apiPort.GetInt32().ToString(CultureInfo.InvariantCulture)
                    : apiPort.GetString();
            }
        }
        catch
        {
            return null;
        }

        return null;
    }
}

public sealed class ProductCommandException : Exception
{
    public ProductCommandException(string message, int exitCode, JsonNode? payload)
        : base(message)
    {
        ExitCode = exitCode;
        Payload = payload;
    }

    public int ExitCode { get; }

    public JsonNode? Payload { get; }
}

public sealed class ProductCommandRunner
{
    private readonly ProductPaths _paths;

    public ProductCommandRunner(ProductPaths paths)
    {
        _paths = paths;
    }

    public async Task<JsonNode?> RunJsonAsync(
        IReadOnlyList<string> arguments,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var runtime = WindowsCodexRuntime.Ensure(_paths);
        var dockerPath = ResolveDockerCommand();
        var composeArguments = BuildComposeArguments(runtime);

        var workerState = await GetWorkerStateAsync(dockerPath, composeArguments, runtime, timeout, cancellationToken);
        if (!workerState.IsRunning)
        {
            throw new InvalidOperationException(workerState.Message);
        }

        var dockerArguments = new List<string>
        {
            "compose",
        };
        dockerArguments.AddRange(composeArguments);
        dockerArguments.AddRange([
            "exec",
            "-T",
            "worker",
            "python",
            "-m",
            "timeline_for_windows_codex_worker",
        ]);
        dockerArguments.AddRange(arguments);

        var result = await RunProcessAsync(
            dockerPath,
            dockerArguments,
            _paths.ProductRoot,
            runtime,
            timeout,
            cancellationToken);

        var stdout = result.Stdout;
        var stderr = result.Stderr;
        var payload = TryParseJson(stdout) ?? TryParseJson(stderr);
        if (result.ExitCode != 0)
        {
            var message = GetErrorMessage(payload);
            if (string.IsNullOrWhiteSpace(message))
            {
                message = !string.IsNullOrWhiteSpace(stderr)
                    ? stderr.Trim()
                    : !string.IsNullOrWhiteSpace(stdout)
                        ? stdout.Trim()
                        : $"exit code {result.ExitCode}";
            }

            throw new ProductCommandException(message, result.ExitCode, payload);
        }

        if (payload is null)
        {
            throw new InvalidOperationException("TimelineForWindowsCodex command did not return JSON.");
        }

        return payload;
    }

    private async Task<WorkerState> GetWorkerStateAsync(
        string dockerPath,
        IReadOnlyList<string> composeArguments,
        WindowsCodexRuntime runtime,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var arguments = new List<string>
        {
            "compose",
        };
        arguments.AddRange(composeArguments);
        arguments.AddRange(["ps", "--status", "running", "--services"]);

        var result = await RunProcessAsync(
            dockerPath,
            arguments,
            _paths.ProductRoot,
            runtime,
            timeout,
            cancellationToken);
        if (result.ExitCode != 0)
        {
            var message = !string.IsNullOrWhiteSpace(result.Stderr)
                ? result.Stderr.Trim()
                : !string.IsNullOrWhiteSpace(result.Stdout)
                    ? result.Stdout.Trim()
                    : "TimelineForWindowsCodex worker status could not be checked.";
            return new WorkerState(false, message);
        }

        var isRunning = result.Stdout
            .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Any(service => string.Equals(service, "worker", StringComparison.Ordinal));
        return isRunning
            ? new WorkerState(true, string.Empty)
            : new WorkerState(false, "TimelineForWindowsCodex worker is not running.");
    }

    private static List<string> BuildComposeArguments(WindowsCodexRuntime runtime)
    {
        var arguments = new List<string>();
        if (!string.IsNullOrWhiteSpace(runtime.ComposeProject))
        {
            arguments.Add("-p");
            arguments.Add(runtime.ComposeProject);
        }
        return arguments;
    }

    private static async Task<CommandResult> RunProcessAsync(
        string fileName,
        IReadOnlyList<string> arguments,
        string workingDirectory,
        WindowsCodexRuntime runtime,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = fileName,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        startInfo.Environment["COMPOSE_PROJECT_NAME"] = runtime.ComposeProject;
        startInfo.Environment["TIMELINE_FOR_WINDOWS_CODEX_INSTANCE_NAME"] = runtime.InstanceName;
        startInfo.Environment["TIMELINE_FOR_WINDOWS_CODEX_API_PORT"] = runtime.ApiPort.ToString(CultureInfo.InvariantCulture);
        startInfo.Environment["HOST_TFWC_SETTINGS_FILE"] = runtime.SettingsPath;
        startInfo.Environment["TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH"] = runtime.SettingsPath;
        startInfo.Environment["HOST_TFWC_CONFIGURED_OUTPUT_ROOT"] = runtime.OutputRoot;
        startInfo.Environment["HOST_TFWC_CONFIGURED_OUTPUT_ROOT_CONTAINER"] = runtime.ContainerOutputRoot;
        startInfo.Environment["HOST_TIMELINE_DATA"] = Environment.GetEnvironmentVariable("HOST_TIMELINE_DATA") ?? @"C:\TimelineData";
        startInfo.Environment["HOST_CODEX_HOME"] = Environment.GetEnvironmentVariable("HOST_CODEX_HOME") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex");
        startInfo.Environment["HOST_CODEX_BACKUP_HOME"] = Environment.GetEnvironmentVariable("HOST_CODEX_BACKUP_HOME") ?? @"C:\Codex\archive\migration-backup-2026-03-27\codex-home";
        startInfo.Environment["HOST_CODEX_ROOT"] = Environment.GetEnvironmentVariable("HOST_CODEX_ROOT") ?? @"C:\Codex";
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("TimelineForWindowsCodex command process could not be started.");
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();

        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(timeout);
        try
        {
            await process.WaitForExitAsync(timeoutSource.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            KillProcessTree(process);
            throw new TimeoutException($"TimelineForWindowsCodex command timed out after {(int)timeout.TotalSeconds} seconds.");
        }
        catch
        {
            KillProcessTree(process);
            throw;
        }

        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        return new CommandResult(process.ExitCode, stdout, stderr);
    }

    private static void KillProcessTree(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
        }
    }

    private static JsonNode? TryParseJson(string text)
    {
        var trimmed = text.Trim();
        if (string.IsNullOrEmpty(trimmed))
        {
            return null;
        }

        try
        {
            return JsonNode.Parse(trimmed);
        }
        catch (JsonException)
        {
        }

        var objectStart = trimmed.IndexOf('{');
        var objectEnd = trimmed.LastIndexOf('}');
        if (objectStart >= 0 && objectEnd > objectStart)
        {
            try
            {
                return JsonNode.Parse(trimmed[objectStart..(objectEnd + 1)]);
            }
            catch (JsonException)
            {
            }
        }

        return null;
    }

    private static string GetErrorMessage(JsonNode? payload)
    {
        if (payload is not JsonObject obj)
        {
            return string.Empty;
        }

        if (obj["error"] is JsonObject error
            && error["message"] is JsonValue errorMessage
            && errorMessage.TryGetValue<string>(out var message)
            && !string.IsNullOrWhiteSpace(message))
        {
            return message.Trim();
        }

        if (obj["message"] is JsonValue messageValue
            && messageValue.TryGetValue<string>(out var rootMessage)
            && !string.IsNullOrWhiteSpace(rootMessage))
        {
            return rootMessage.Trim();
        }

        return string.Empty;
    }

    private static string ResolveDockerCommand()
    {
        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        if (!string.IsNullOrWhiteSpace(programFiles))
        {
            var dockerExe = Path.Combine(programFiles, "Docker", "Docker", "resources", "bin", "docker.exe");
            if (File.Exists(dockerExe))
            {
                return dockerExe;
            }
        }

        return "docker";
    }
}

internal sealed record CommandResult(int ExitCode, string Stdout, string Stderr);

internal sealed record WorkerState(bool IsRunning, string Message);

internal sealed record WindowsCodexRuntime(
    string InstanceName,
    string ComposeProject,
    int ApiPort,
    string SettingsPath,
    string OutputRoot,
    string ContainerOutputRoot)
{
    public static WindowsCodexRuntime Ensure(ProductPaths paths)
    {
        EnsureSettingsFile(paths);
        var settings = ReadSettings(paths.SettingsPath);
        var runtime = settings["runtime"] as JsonObject ?? new JsonObject();
        settings["runtime"] = runtime;

        var instanceName = SafeName(Environment.GetEnvironmentVariable("TIMELINE_FOR_WINDOWS_CODEX_INSTANCE_NAME") ?? GetString(runtime, "instanceName"));
        var composeProject = SafeName(Environment.GetEnvironmentVariable("COMPOSE_PROJECT_NAME") ?? string.Empty);
        if (string.IsNullOrWhiteSpace(composeProject) && !string.IsNullOrWhiteSpace(instanceName))
        {
            composeProject = $"timeline-for-windows-codex-{instanceName}";
        }

        var apiPort = TryParsePort(Environment.GetEnvironmentVariable("TIMELINE_FOR_WINDOWS_CODEX_API_PORT"))
            ?? GetInt(runtime, "apiPort")
            ?? 19200;
        if (apiPort is < 1 or > 65535)
        {
            apiPort = 19200;
        }

        var outputRoot = GetString(settings, "outputRoot");
        if (string.IsNullOrWhiteSpace(outputRoot))
        {
            outputRoot = @"C:\TimelineData\windows-codex";
        }
        if (!Path.IsPathRooted(outputRoot))
        {
            outputRoot = Path.Combine(paths.ProductRoot, outputRoot);
        }
        outputRoot = Path.GetFullPath(outputRoot);
        Directory.CreateDirectory(outputRoot);

        return new WindowsCodexRuntime(
            instanceName,
            composeProject,
            apiPort,
            paths.SettingsPath,
            outputRoot,
            HostPathToContainerPath(outputRoot));
    }

    private static void EnsureSettingsFile(ProductPaths paths)
    {
        if (File.Exists(paths.SettingsPath))
        {
            return;
        }

        var settingsDirectory = Path.GetDirectoryName(paths.SettingsPath);
        if (!string.IsNullOrWhiteSpace(settingsDirectory))
        {
            Directory.CreateDirectory(settingsDirectory);
        }

        if (File.Exists(paths.SettingsExamplePath))
        {
            File.Copy(paths.SettingsExamplePath, paths.SettingsPath, overwrite: true);
            return;
        }

        File.WriteAllText(
            paths.SettingsPath,
            """
            {
              "schemaVersion": 1,
              "runtime": {
                "instanceName": "",
                "apiPort": 19200
              },
              "sourceRoot": "C:\\Users\\amano\\.codex",
              "outputRoot": "C:\\TimelineData\\windows-codex"
            }
            """,
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    }

    private static JsonObject ReadSettings(string path)
    {
        try
        {
            return JsonNode.Parse(File.ReadAllText(path, Encoding.UTF8)) as JsonObject ?? new JsonObject();
        }
        catch
        {
            return new JsonObject();
        }
    }

    private static string HostPathToContainerPath(string hostPath)
    {
        var fullPath = Path.GetFullPath(hostPath);
        if (fullPath.Length >= 3 && fullPath[1] == ':' && (fullPath[2] == '\\' || fullPath[2] == '/'))
        {
            var drive = char.ToLowerInvariant(fullPath[0]);
            var rest = fullPath[3..].Replace('\\', '/');
            return $"/mnt/{drive}/{rest}";
        }

        return fullPath.Replace('\\', '/');
    }

    private static string SafeName(string value)
    {
        var builder = new StringBuilder();
        var lastWasDash = false;
        foreach (var ch in value.Trim().ToLowerInvariant())
        {
            var isValid = ch is >= 'a' and <= 'z' || ch is >= '0' and <= '9';
            if (isValid)
            {
                builder.Append(ch);
                lastWasDash = false;
            }
            else if (!lastWasDash)
            {
                builder.Append('-');
                lastWasDash = true;
            }
        }
        return builder.ToString().Trim('-');
    }

    private static string GetString(JsonObject source, string name)
    {
        if (source[name] is JsonValue value && value.TryGetValue<string>(out var text))
        {
            return text.Trim();
        }
        return string.Empty;
    }

    private static int? GetInt(JsonObject source, string name)
    {
        if (source[name] is not JsonValue value)
        {
            return null;
        }
        if (value.TryGetValue<int>(out var intValue))
        {
            return intValue;
        }
        if (value.TryGetValue<string>(out var textValue) && int.TryParse(textValue, out var parsed))
        {
            return parsed;
        }
        return null;
    }

    private static int? TryParsePort(string? value)
    {
        if (string.IsNullOrWhiteSpace(value) || !int.TryParse(value, out var port))
        {
            return null;
        }
        return port is >= 1 and <= 65535 ? port : null;
    }
}
