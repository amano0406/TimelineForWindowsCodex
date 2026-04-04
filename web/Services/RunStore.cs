using System.IO.Compression;
using System.Text.Json;
using WindowsCodex2Timeline.Web.Infrastructure;
using WindowsCodex2Timeline.Web.Models;

namespace WindowsCodex2Timeline.Web.Services;

public sealed class RunStore(AppPaths paths, CodexDiscoveryService discoveryService)
{
    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public async Task<(string JobId, string RunDirectory)> CreateJobAsync(
        CreateJobCommand command,
        CancellationToken cancellationToken = default)
    {
        Directory.CreateDirectory(paths.OutputsRoot);

        var discovered = await discoveryService.DiscoverAsync(
            command.PrimaryCodexHomePath,
            command.BackupCodexHomePaths,
            cancellationToken);

        var selectedIds = command.SelectedThreadIds
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var selectedThreads = discovered
            .Where(thread => selectedIds.Contains(thread.ThreadId))
            .ToList();

        if (selectedThreads.Count == 0)
        {
            throw new InvalidOperationException("error.select_thread");
        }

        var jobId = $"run-{DateTimeOffset.Now:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}"[..32];
        var runDirectory = Path.Combine(paths.OutputsRoot, jobId);
        Directory.CreateDirectory(runDirectory);
        Directory.CreateDirectory(Path.Combine(runDirectory, "threads"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "llm"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "normalized"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "derived"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "export"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "logs"));

        var request = new JobRequestDocument
        {
            JobId = jobId,
            CreatedAt = DateTimeOffset.Now.ToString("O"),
            PrimaryCodexHomePath = command.PrimaryCodexHomePath,
            BackupCodexHomePaths = command.BackupCodexHomePaths.ToList(),
            IncludeArchivedSources = command.IncludeArchivedSources,
            IncludeToolOutputs = command.IncludeToolOutputs,
            RedactionProfile = command.RedactionProfile,
            DateFrom = command.DateFrom,
            DateTo = command.DateTo,
            SelectedThreads = selectedThreads,
        };

        var status = new JobStatusDocument
        {
            JobId = jobId,
            State = "pending",
            CurrentStage = "queued",
            Message = "Waiting for worker pickup.",
            ThreadsTotal = selectedThreads.Count,
            ThreadsDone = 0,
            EventsTotal = 0,
            EventsDone = 0,
            ProgressPercent = 0,
        };

        var result = new JobResultDocument
        {
            JobId = jobId,
            State = "pending",
        };

        var manifest = new ManifestDocument
        {
            JobId = jobId,
            GeneratedAt = DateTimeOffset.Now.ToString("O"),
            Items = selectedThreads.Select(thread => new ManifestThreadItemDocument
            {
                ThreadId = thread.ThreadId,
                PreferredTitle = thread.PreferredTitle,
                SessionPath = thread.SessionPath,
                SourceRootPath = thread.SourceRootPath,
                Status = "pending",
                EventCount = 0,
            }).ToList(),
        };

        await WriteJsonAsync(Path.Combine(runDirectory, "request.json"), request, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "status.json"), status, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "result.json"), result, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "manifest.json"), manifest, cancellationToken);
        await File.WriteAllTextAsync(
            Path.Combine(runDirectory, "README.md"),
            "# windowscodex2timeline run\n\nThis directory is the source of truth for one timeline run.\n",
            cancellationToken);
        await File.WriteAllTextAsync(
            Path.Combine(runDirectory, "NOTICE.md"),
            "Sensitive data may exist in raw source material. Exported outputs should use redacted views.\n",
            cancellationToken);

        return (jobId, runDirectory);
    }

    public async Task<IReadOnlyList<RunSummary>> ListRunsAsync(CancellationToken cancellationToken = default)
    {
        if (!Directory.Exists(paths.OutputsRoot))
        {
            return [];
        }

        var rows = new List<RunSummary>();
        foreach (var runDirectory in Directory.EnumerateDirectories(paths.OutputsRoot))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
            var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
            if (request is null || status is null)
            {
                continue;
            }

            rows.Add(new RunSummary
            {
                JobId = request.JobId,
                State = status.State,
                CurrentStage = status.CurrentStage,
                ThreadsTotal = status.ThreadsTotal,
                ThreadsDone = status.ThreadsDone,
                EventsTotal = status.EventsTotal,
                EventsDone = status.EventsDone,
                ProgressPercent = status.ProgressPercent,
                EstimatedRemainingSec = status.EstimatedRemainingSec,
                CreatedAt = request.CreatedAt,
                UpdatedAt = status.UpdatedAt,
                ElapsedWallSec = DisplayFormatters.CalculateElapsedSeconds(status.StartedAt, status.CompletedAt, status.UpdatedAt),
                HasDownloadableArchive = File.Exists(Path.Combine(runDirectory, "export", "windowscodex2timeline-export.zip")),
            });
        }

        return rows
            .OrderByDescending(static item => item.CreatedAt)
            .ToList();
    }

    public async Task<RunDetails?> GetRunDetailsAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = Path.Combine(paths.OutputsRoot, jobId);
        if (!Directory.Exists(runDirectory))
        {
            return null;
        }

        var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
        var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
        var result = await ReadJsonAsync<JobResultDocument>(Path.Combine(runDirectory, "result.json"), cancellationToken);
        var manifest = await ReadJsonAsync<ManifestDocument>(Path.Combine(runDirectory, "manifest.json"), cancellationToken);
        if (request is null || status is null || result is null)
        {
            return null;
        }

        var timelineItems = new List<TimelineItemDocument>();
        var threadsRoot = Path.Combine(runDirectory, "threads");
        if (Directory.Exists(threadsRoot))
        {
            foreach (var threadDirectory in Directory.EnumerateDirectories(threadsRoot))
            {
                var timelinePath = Path.Combine(threadDirectory, "timeline.md");
                if (!File.Exists(timelinePath))
                {
                    continue;
                }

                var threadId = Path.GetFileName(threadDirectory);
                var preferredTitle = manifest?.Items.FirstOrDefault(item => string.Equals(item.ThreadId, threadId, StringComparison.OrdinalIgnoreCase))?.PreferredTitle
                                     ?? threadId;
                var preview = string.Join("\n", File.ReadLines(timelinePath).Take(20));
                timelineItems.Add(new TimelineItemDocument
                {
                    ThreadId = threadId,
                    PreferredTitle = preferredTitle,
                    TimelinePath = timelinePath,
                    Preview = preview,
                });
            }
        }

        return new RunDetails
        {
            JobId = request.JobId,
            RunDirectory = runDirectory,
            Request = request,
            Status = status,
            Result = result,
            ManifestItems = manifest?.Items ?? [],
            TimelineItems = timelineItems.OrderBy(static item => item.PreferredTitle, StringComparer.CurrentCultureIgnoreCase).ToList(),
            ArchivePath = Path.Combine(runDirectory, "export", "windowscodex2timeline-export.zip"),
            ElapsedWallSec = DisplayFormatters.CalculateElapsedSeconds(status.StartedAt, status.CompletedAt, status.UpdatedAt),
        };
    }

    public async Task DeleteRunAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = Path.Combine(paths.OutputsRoot, jobId);
        if (!Directory.Exists(runDirectory))
        {
            throw new InvalidOperationException("error.job_not_found");
        }

        var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
        if (status is not null &&
            (string.Equals(status.State, "pending", StringComparison.OrdinalIgnoreCase) ||
             string.Equals(status.State, "running", StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidOperationException("error.active_job_delete");
        }

        Directory.Delete(runDirectory, recursive: true);
    }

    public async Task<string?> GetArchivePathAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var details = await GetRunDetailsAsync(jobId, cancellationToken);
        if (details is null || string.IsNullOrWhiteSpace(details.ArchivePath))
        {
            return null;
        }

        return File.Exists(details.ArchivePath) ? details.ArchivePath : null;
    }

    private async Task<T?> ReadJsonAsync<T>(string path, CancellationToken cancellationToken)
    {
        if (!File.Exists(path))
        {
            return default;
        }

        await using var stream = File.OpenRead(path);
        return await JsonSerializer.DeserializeAsync<T>(stream, _jsonOptions, cancellationToken);
    }

    private async Task WriteJsonAsync<T>(string path, T payload, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var json = JsonSerializer.Serialize(payload, _jsonOptions);
        await File.WriteAllTextAsync(path, json, cancellationToken);
    }
}
