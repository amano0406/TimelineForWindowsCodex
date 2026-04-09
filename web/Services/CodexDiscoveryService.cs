using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using TimelineForWindowsCodex.Web.Models;

namespace TimelineForWindowsCodex.Web.Services;

public sealed partial class CodexDiscoveryService(ILogger<CodexDiscoveryService> logger)
{
    private readonly ILogger<CodexDiscoveryService> _logger = logger;

    private sealed class MutableThread
    {
        public string ThreadId { get; init; } = "";
        public string PreferredTitle { get; set; } = "";
        public List<string> TitleHistory { get; } = [];
        public string SourceRootPath { get; set; } = "";
        public string SourceRootKind { get; set; } = "";
        public string SessionPath { get; set; } = "";
        public string? UpdatedAt { get; set; }
        public string? Cwd { get; set; }
        public string? FirstUserMessageExcerpt { get; set; }
        public int Priority { get; set; } = int.MaxValue;
    }

    public async Task<IReadOnlyList<DiscoveredThreadDocument>> DiscoverAsync(
        string primaryRootPath,
        IEnumerable<string> backupRootPaths,
        bool includeArchivedSources = true,
        CancellationToken cancellationToken = default)
    {
        var roots = new List<(string Path, string Kind, int Priority)>();
        if (!string.IsNullOrWhiteSpace(primaryRootPath))
        {
            roots.Add((primaryRootPath.Trim(), "primary", 0));
        }

        var backupPriority = 1;
        foreach (var path in backupRootPaths.Where(static value => !string.IsNullOrWhiteSpace(value)))
        {
            roots.Add((path.Trim(), $"backup_{backupPriority}", backupPriority));
            backupPriority += 1;
        }

        var threads = new Dictionary<string, MutableThread>(StringComparer.OrdinalIgnoreCase);

        foreach (var root in roots
                     .Where(static item => Directory.Exists(item.Path))
                     .DistinctBy(static item => item.Path, StringComparer.OrdinalIgnoreCase))
        {
            cancellationToken.ThrowIfCancellationRequested();
            await MergeSessionIndexAsync(root.Path, root.Kind, root.Priority, threads, cancellationToken);
            await MergeStateCatalogAsync(root.Path, root.Kind, root.Priority, threads, cancellationToken);
            await MergeSessionFilesAsync(root.Path, root.Kind, root.Priority, threads, includeArchivedSources, cancellationToken);
            if (includeArchivedSources)
            {
                await MergeThreadReadFilesAsync(root.Path, root.Kind, root.Priority, threads, cancellationToken);
            }
        }

        return threads.Values
            .Select(static item => new DiscoveredThreadDocument
            {
                ThreadId = item.ThreadId,
                PreferredTitle = item.PreferredTitle,
                TitleHistory = item.TitleHistory.ToList(),
                SourceRootPath = item.SourceRootPath,
                SourceRootKind = item.SourceRootKind,
                SessionPath = item.SessionPath,
                UpdatedAt = item.UpdatedAt,
                Cwd = item.Cwd,
                FirstUserMessageExcerpt = item.FirstUserMessageExcerpt,
            })
            .OrderByDescending(static item => ParseUpdatedAt(item.UpdatedAt))
            .ThenBy(static item => item.PreferredTitle, StringComparer.CurrentCultureIgnoreCase)
            .ToList();
    }

    private static DateTimeOffset ParseUpdatedAt(string? value)
    {
        return DateTimeOffset.TryParse(value, out var parsed) ? parsed : DateTimeOffset.MinValue;
    }

    private async Task MergeSessionIndexAsync(
        string rootPath,
        string rootKind,
        int priority,
        Dictionary<string, MutableThread> threads,
        CancellationToken cancellationToken)
    {
        var sessionIndexPath = Path.Combine(rootPath, "session_index.jsonl");
        if (!File.Exists(sessionIndexPath))
        {
            return;
        }

        foreach (var line in File.ReadLines(sessionIndexPath))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            try
            {
                using var document = JsonDocument.Parse(line);
                var root = document.RootElement;
                var threadId = root.TryGetProperty("id", out var idElement) ? idElement.GetString() : null;
                if (string.IsNullOrWhiteSpace(threadId))
                {
                    continue;
                }

                var rawTitle = root.TryGetProperty("thread_name", out var titleElement)
                    ? titleElement.GetString()
                    : null;
                var sanitizedTitle = SanitizeText(rawTitle, 120);
                var updatedAt = root.TryGetProperty("updated_at", out var updatedAtElement)
                    ? updatedAtElement.GetString()
                    : null;

                var thread = GetOrCreate(threadId, rootPath, rootKind, priority, threads);
                if (!string.IsNullOrWhiteSpace(sanitizedTitle) &&
                    !thread.TitleHistory.Contains(sanitizedTitle, StringComparer.Ordinal))
                {
                    thread.TitleHistory.Add(sanitizedTitle);
                    thread.PreferredTitle = sanitizedTitle;
                }

                if (!string.IsNullOrWhiteSpace(updatedAt) &&
                    ParseUpdatedAt(updatedAt) >= ParseUpdatedAt(thread.UpdatedAt))
                {
                    thread.UpdatedAt = updatedAt;
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Skipping unreadable session index row from {SessionIndexPath}", sessionIndexPath);
            }
        }

        await Task.CompletedTask;
    }

    private async Task MergeSessionFilesAsync(
        string rootPath,
        string rootKind,
        int priority,
        Dictionary<string, MutableThread> threads,
        bool includeArchivedSources,
        CancellationToken cancellationToken)
    {
        var paths = new List<string>();
        var sessionsRoot = Path.Combine(rootPath, "sessions");
        if (Directory.Exists(sessionsRoot))
        {
            paths.AddRange(Directory.EnumerateFiles(sessionsRoot, "*.jsonl", SearchOption.AllDirectories));
        }

        var archivedSessionsRoot = Path.Combine(rootPath, "archived_sessions");
        if (includeArchivedSources && Directory.Exists(archivedSessionsRoot))
        {
            paths.AddRange(Directory.EnumerateFiles(archivedSessionsRoot, "*.jsonl", SearchOption.TopDirectoryOnly));
        }

        foreach (var sessionPath in paths.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var preview = await ReadSessionPreviewAsync(sessionPath, cancellationToken);
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
                    thread.SessionPath = sessionPath;
                    thread.Priority = priority;
                    thread.Cwd = thread.Cwd ?? preview.Cwd;
                    thread.FirstUserMessageExcerpt = thread.FirstUserMessageExcerpt ?? preview.FirstUserMessageExcerpt;
                }

                var updatedAt = preview.UpdatedAt ?? File.GetLastWriteTimeUtc(sessionPath).ToString("O", CultureInfo.InvariantCulture);
                if (ParseUpdatedAt(updatedAt) >= ParseUpdatedAt(thread.UpdatedAt))
                {
                    thread.UpdatedAt = updatedAt;
                }

                if (string.IsNullOrWhiteSpace(thread.PreferredTitle))
                {
                    thread.PreferredTitle = $"Thread {thread.ThreadId}";
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Skipping unreadable session file {SessionPath}", sessionPath);
            }
        }
    }

    private static MutableThread GetOrCreate(
        string threadId,
        string rootPath,
        string rootKind,
        int priority,
        Dictionary<string, MutableThread> threads)
    {
        if (!threads.TryGetValue(threadId, out var thread))
        {
            thread = new MutableThread
            {
                ThreadId = threadId,
                SourceRootPath = rootPath,
                SourceRootKind = rootKind,
                Priority = priority,
                PreferredTitle = $"Thread {threadId}",
            };
            threads[threadId] = thread;
        }

        return thread;
    }

    private static async Task<(string? ThreadId, string? UpdatedAt, string? Cwd, string? FirstUserMessageExcerpt)> ReadSessionPreviewAsync(
        string sessionPath,
        CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(sessionPath);
        using var reader = new StreamReader(stream);

        string? threadId = null;
        string? updatedAt = null;
        string? cwd = null;
        string? firstUserMessageExcerpt = null;

        while (threadId is null || firstUserMessageExcerpt is null)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var line = await reader.ReadLineAsync(cancellationToken);
            if (line is null)
            {
                break;
            }
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            using var document = JsonDocument.Parse(line);
            var root = document.RootElement;
            var type = root.TryGetProperty("type", out var typeElement) ? typeElement.GetString() : null;
            if (string.Equals(type, "session_meta", StringComparison.OrdinalIgnoreCase) &&
                root.TryGetProperty("payload", out var payload))
            {
                if (payload.TryGetProperty("id", out var idElement))
                {
                    threadId = idElement.GetString();
                }

                if (payload.TryGetProperty("cwd", out var cwdElement))
                {
                    cwd = cwdElement.GetString();
                }

                if (payload.TryGetProperty("timestamp", out var timestampElement))
                {
                    updatedAt = timestampElement.GetString();
                }
            }
            else if (string.Equals(type, "event_msg", StringComparison.OrdinalIgnoreCase) &&
                     root.TryGetProperty("payload", out var eventPayload) &&
                     eventPayload.TryGetProperty("type", out var eventTypeElement) &&
                     string.Equals(eventTypeElement.GetString(), "user_message", StringComparison.OrdinalIgnoreCase))
            {
                if (eventPayload.TryGetProperty("message", out var messageElement))
                {
                    firstUserMessageExcerpt = SanitizeText(messageElement.GetString(), 240);
                }
            }
        }

        if (string.IsNullOrWhiteSpace(threadId))
        {
            var match = SessionIdRegex().Match(Path.GetFileName(sessionPath));
            if (match.Success)
            {
                threadId = match.Value;
            }
        }

        return (threadId, updatedAt, cwd, firstUserMessageExcerpt);
    }

    private static string SanitizeText(string? rawText, int maxLength)
    {
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return string.Empty;
        }

        var text = rawText.Replace("\r", " ").Replace("\n", " ").Trim();
        text = EmailRegex().Replace(text, "[email]");
        text = UrlRegex().Replace(text, "[url]");
        text = PasswordRegex().Replace(text, "$1[redacted]");
        text = TokenRegex().Replace(text, "$1[redacted]");
        text = WhitespaceRegex().Replace(text, " ").Trim();
        return text.Length > maxLength ? $"{text[..(maxLength - 3)]}..." : text;
    }

    [GeneratedRegex("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}", RegexOptions.IgnoreCase)]
    private static partial Regex EmailRegex();

    [GeneratedRegex("https?://[^\\s)\\]>]+", RegexOptions.IgnoreCase)]
    private static partial Regex UrlRegex();

    [GeneratedRegex("(?i)(password\\s*[:=]\\s*)\\S+")]
    private static partial Regex PasswordRegex();

    [GeneratedRegex("(?i)(token\\s*[:=]\\s*)\\S+")]
    private static partial Regex TokenRegex();

    [GeneratedRegex("\\s+")]
    private static partial Regex WhitespaceRegex();

    [GeneratedRegex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", RegexOptions.IgnoreCase)]
    private static partial Regex SessionIdRegex();
}
