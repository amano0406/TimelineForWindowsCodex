using System.Globalization;
using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace TimelineForWindowsCodex.Web.Services;

public sealed partial class CodexDiscoveryService
{
    private async Task MergeStateCatalogAsync(
        string rootPath,
        string rootKind,
        int priority,
        Dictionary<string, MutableThread> threads,
        CancellationToken cancellationToken)
    {
        var stateDatabasePath = Path.Combine(rootPath, "state_5.sqlite");
        if (!File.Exists(stateDatabasePath))
        {
            return;
        }

        try
        {
            await using var connection = new SqliteConnection(
                new SqliteConnectionStringBuilder
                {
                    DataSource = stateDatabasePath,
                    Mode = SqliteOpenMode.ReadOnly,
                }.ToString());
            await connection.OpenAsync(cancellationToken);

            await using var command = connection.CreateCommand();
            command.CommandText = """
                SELECT
                    id,
                    rollout_path,
                    updated_at,
                    cwd,
                    first_user_message
                FROM threads
                """;

            await using var reader = await command.ExecuteReaderAsync(cancellationToken);
            while (await reader.ReadAsync(cancellationToken))
            {
                var threadId = reader.IsDBNull(0) ? null : reader.GetString(0);
                if (string.IsNullOrWhiteSpace(threadId))
                {
                    continue;
                }

                var rolloutPath = reader.IsDBNull(1) ? null : reader.GetString(1);
                var updatedAt = reader.IsDBNull(2) ? null : ToIsoFromUnix(reader.GetInt64(2));
                var cwd = reader.IsDBNull(3) ? null : reader.GetString(3);
                var firstUserMessage = reader.IsDBNull(4) ? null : reader.GetString(4);

                var thread = GetOrCreate(threadId!, rootPath, rootKind, priority, threads);

                if ((string.IsNullOrWhiteSpace(thread.SessionPath) || !File.Exists(thread.SessionPath)) &&
                    !string.IsNullOrWhiteSpace(rolloutPath))
                {
                    thread.SourceRootPath = rootPath;
                    thread.SourceRootKind = rootKind;
                    thread.SessionPath = rolloutPath!;
                    thread.Priority = Math.Min(thread.Priority, priority);
                }

                if (string.IsNullOrWhiteSpace(thread.Cwd) && !string.IsNullOrWhiteSpace(cwd))
                {
                    thread.Cwd = cwd;
                }

                if (string.IsNullOrWhiteSpace(thread.FirstUserMessageExcerpt) &&
                    !string.IsNullOrWhiteSpace(firstUserMessage))
                {
                    thread.FirstUserMessageExcerpt = SanitizeText(firstUserMessage, 240);
                }

                if (!string.IsNullOrWhiteSpace(updatedAt) &&
                    ParseUpdatedAt(updatedAt) >= ParseUpdatedAt(thread.UpdatedAt))
                {
                    thread.UpdatedAt = updatedAt;
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Skipping unreadable state database {StateDatabasePath}", stateDatabasePath);
        }
    }

    private async Task MergeThreadReadFilesAsync(
        string rootPath,
        string rootKind,
        int priority,
        Dictionary<string, MutableThread> threads,
        CancellationToken cancellationToken)
    {
        foreach (var threadReadRoot in EnumerateThreadReadRoots(rootPath))
        {
            foreach (var threadReadPath in Directory.EnumerateFiles(threadReadRoot, "*.json", SearchOption.TopDirectoryOnly))
            {
                cancellationToken.ThrowIfCancellationRequested();
                try
                {
                    var preview = await ReadThreadReadPreviewAsync(threadReadPath, cancellationToken);
                    if (string.IsNullOrWhiteSpace(preview.ThreadId))
                    {
                        continue;
                    }

                    var thread = GetOrCreate(preview.ThreadId!, rootPath, rootKind, priority, threads);
                    if (priority < thread.Priority ||
                        string.IsNullOrWhiteSpace(thread.SessionPath) ||
                        !File.Exists(thread.SessionPath))
                    {
                        thread.SourceRootPath = rootPath;
                        thread.SourceRootKind = rootKind;
                        thread.SessionPath = threadReadPath;
                        thread.Priority = priority;
                    }

                    if (!string.IsNullOrWhiteSpace(preview.Title))
                    {
                        var sanitizedTitle = SanitizeText(preview.Title, 120);
                        AddObservedThreadName(thread, sanitizedTitle, preview.UpdatedAt, "thread_reads");
                    }

                    if (string.IsNullOrWhiteSpace(thread.Cwd) && !string.IsNullOrWhiteSpace(preview.Cwd))
                    {
                        thread.Cwd = preview.Cwd;
                    }

                    if (string.IsNullOrWhiteSpace(thread.FirstUserMessageExcerpt) &&
                        !string.IsNullOrWhiteSpace(preview.FirstUserMessageExcerpt))
                    {
                        thread.FirstUserMessageExcerpt = preview.FirstUserMessageExcerpt;
                    }

                    if (!string.IsNullOrWhiteSpace(preview.UpdatedAt) &&
                        ParseUpdatedAt(preview.UpdatedAt) >= ParseUpdatedAt(thread.UpdatedAt))
                    {
                        thread.UpdatedAt = preview.UpdatedAt;
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Skipping unreadable archived thread file {ThreadReadPath}", threadReadPath);
                }
            }
        }
    }

    private static IEnumerable<string> EnumerateThreadReadRoots(string rootPath)
    {
        var candidates = new[]
        {
            rootPath,
            Path.Combine(rootPath, "thread_reads"),
            Path.Combine(rootPath, "_codex_tools"),
            Path.Combine(rootPath, "_codex_tools", "thread_reads"),
        };

        return candidates
            .Where(Directory.Exists)
            .Select(path => path.EndsWith("thread_reads", StringComparison.OrdinalIgnoreCase)
                ? path
                : Path.Combine(path, "thread_reads"))
            .Where(Directory.Exists)
            .Distinct(StringComparer.OrdinalIgnoreCase);
    }

    private static async Task<(string? ThreadId, string? Title, string? UpdatedAt, string? Cwd, string? FirstUserMessageExcerpt)> ReadThreadReadPreviewAsync(
        string threadReadPath,
        CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(threadReadPath);
        using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);

        var thread = TryGetThreadReadThread(document.RootElement);
        if (thread.ValueKind == JsonValueKind.Undefined)
        {
            return (null, null, null, null, null);
        }

        var threadId = thread.TryGetProperty("id", out var idElement) ? idElement.GetString() : null;
        var title = thread.TryGetProperty("name", out var titleElement)
            ? titleElement.GetString()
            : null;
        var updatedAt = thread.TryGetProperty("updatedAt", out var updatedAtElement)
            ? ToIsoFromUnknown(updatedAtElement)
            : null;
        var cwd = thread.TryGetProperty("cwd", out var cwdElement) ? cwdElement.GetString() : null;
        var preview = thread.TryGetProperty("preview", out var previewElement) ? previewElement.GetString() : null;
        var firstUserExcerpt = string.IsNullOrWhiteSpace(preview)
            ? ExtractFirstUserExcerpt(thread)
            : SanitizeText(preview, 240);

        return (threadId, title, updatedAt, cwd, firstUserExcerpt);
    }

    private static JsonElement TryGetThreadReadThread(JsonElement root)
    {
        if (root.TryGetProperty("result", out var result) &&
            result.ValueKind == JsonValueKind.Object &&
            result.TryGetProperty("thread", out var resultThread) &&
            resultThread.ValueKind == JsonValueKind.Object)
        {
            return resultThread;
        }

        if (root.TryGetProperty("thread", out var thread) &&
            thread.ValueKind == JsonValueKind.Object)
        {
            return thread;
        }

        return default;
    }

    private static string? ExtractFirstUserExcerpt(JsonElement thread)
    {
        if (!thread.TryGetProperty("turns", out var turns) || turns.ValueKind != JsonValueKind.Array)
        {
            return null;
        }

        foreach (var turn in turns.EnumerateArray())
        {
            if (!turn.TryGetProperty("items", out var items) || items.ValueKind != JsonValueKind.Array)
            {
                continue;
            }

            foreach (var item in items.EnumerateArray())
            {
                if (!item.TryGetProperty("type", out var typeElement) ||
                    !string.Equals(typeElement.GetString(), "userMessage", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                if (!item.TryGetProperty("content", out var content) || content.ValueKind != JsonValueKind.Array)
                {
                    continue;
                }

                var parts = new List<string>();
                foreach (var contentItem in content.EnumerateArray())
                {
                    if (contentItem.TryGetProperty("text", out var textElement))
                    {
                        parts.Add(textElement.GetString() ?? string.Empty);
                    }
                }

                var combined = string.Join(" ", parts);
                return string.IsNullOrWhiteSpace(combined) ? null : SanitizeText(combined, 240);
            }
        }

        return null;
    }

    private static string? ToIsoFromUnknown(JsonElement value)
    {
        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt64(out var unixSeconds) => ToIsoFromUnix(unixSeconds),
            JsonValueKind.String when DateTimeOffset.TryParse(value.GetString(), out var parsed) => parsed.ToString("O", CultureInfo.InvariantCulture),
            _ => null,
        };
    }

    private static string ToIsoFromUnix(long unixSeconds) =>
        DateTimeOffset.FromUnixTimeSeconds(unixSeconds).ToString("O", CultureInfo.InvariantCulture);

    private static bool IsDefaultTitle(MutableThread thread) =>
        string.IsNullOrWhiteSpace(thread.PreferredTitle) ||
        string.Equals(thread.PreferredTitle, thread.ThreadId, StringComparison.Ordinal);
}
