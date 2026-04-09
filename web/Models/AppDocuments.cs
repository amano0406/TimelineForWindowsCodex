namespace TimelineForWindowsCodex.Web.Models;

public sealed class AppSettingsDocument
{
    public int SchemaVersion { get; set; } = 1;
    public string DefaultPrimaryCodexHomePath { get; set; } = "/input/codex-home";
    public List<string> DefaultBackupCodexHomePaths { get; set; } = [];
    public List<string> DefaultEnrichmentRootPaths { get; set; } = [];
    public string DefaultRedactionProfile { get; set; } = "strict";
    public bool DefaultIncludeArchivedSources { get; set; } = true;
    public bool DefaultIncludeToolOutputs { get; set; } = true;
    public string UiLanguage { get; set; } = "ja";
    public bool LanguageSelected { get; set; } = true;
}

public sealed class DiscoveredThreadDocument
{
    public string ThreadId { get; set; } = "";
    public string PreferredTitle { get; set; } = "";
    public List<string> TitleHistory { get; set; } = [];
    public string SourceRootPath { get; set; } = "";
    public string SourceRootKind { get; set; } = "";
    public string SessionPath { get; set; } = "";
    public string? UpdatedAt { get; set; }
    public string? Cwd { get; set; }
    public string? FirstUserMessageExcerpt { get; set; }
}

public sealed class CreateJobCommand
{
    public string PrimaryCodexHomePath { get; set; } = "";
    public List<string> BackupCodexHomePaths { get; set; } = [];
    public bool IncludeArchivedSources { get; set; }
    public bool IncludeToolOutputs { get; set; }
    public string RedactionProfile { get; set; } = "strict";
    public string? DateFrom { get; set; }
    public string? DateTo { get; set; }
    public List<string> SelectedThreadIds { get; set; } = [];
}

public sealed class JobRequestDocument
{
    public int SchemaVersion { get; set; } = 1;
    public string JobId { get; set; } = "";
    public string CreatedAt { get; set; } = "";
    public string PrimaryCodexHomePath { get; set; } = "";
    public List<string> BackupCodexHomePaths { get; set; } = [];
    public bool IncludeArchivedSources { get; set; }
    public bool IncludeToolOutputs { get; set; }
    public string RedactionProfile { get; set; } = "strict";
    public string? DateFrom { get; set; }
    public string? DateTo { get; set; }
    public List<DiscoveredThreadDocument> SelectedThreads { get; set; } = [];
}

public sealed class JobStatusDocument
{
    public int SchemaVersion { get; set; } = 1;
    public string JobId { get; set; } = "";
    public string State { get; set; } = "pending";
    public string CurrentStage { get; set; } = "queued";
    public string Message { get; set; } = "";
    public List<string> Warnings { get; set; } = [];
    public int ThreadsTotal { get; set; }
    public int ThreadsDone { get; set; }
    public int EventsTotal { get; set; }
    public int EventsDone { get; set; }
    public double ProgressPercent { get; set; }
    public double? EstimatedRemainingSec { get; set; }
    public string? CurrentThreadId { get; set; }
    public string? CurrentThreadTitle { get; set; }
    public string? StartedAt { get; set; }
    public string? UpdatedAt { get; set; }
    public string? CompletedAt { get; set; }
}

public sealed class JobResultDocument
{
    public int SchemaVersion { get; set; } = 1;
    public string JobId { get; set; } = "";
    public string State { get; set; } = "pending";
    public int ThreadCount { get; set; }
    public int EventCount { get; set; }
    public int SegmentCount { get; set; }
    public string? TimelineIndexPath { get; set; }
    public string? HandoffPath { get; set; }
    public string? ArchivePath { get; set; }
    public List<string> Warnings { get; set; } = [];
}

public sealed class ManifestThreadItemDocument
{
    public string ThreadId { get; set; } = "";
    public string PreferredTitle { get; set; } = "";
    public string SessionPath { get; set; } = "";
    public string SourceRootPath { get; set; } = "";
    public string Status { get; set; } = "pending";
    public int EventCount { get; set; }
    public string? TimelinePath { get; set; }
}

public sealed class ManifestDocument
{
    public int SchemaVersion { get; set; } = 1;
    public string JobId { get; set; } = "";
    public string GeneratedAt { get; set; } = "";
    public List<ManifestThreadItemDocument> Items { get; set; } = [];
}

public sealed class TimelineItemDocument
{
    public string ThreadId { get; set; } = "";
    public string PreferredTitle { get; set; } = "";
    public string TimelinePath { get; set; } = "";
    public string Preview { get; set; } = "";
}

public sealed class RunSummary
{
    public string JobId { get; set; } = "";
    public string State { get; set; } = "pending";
    public string CurrentStage { get; set; } = "queued";
    public int ThreadsTotal { get; set; }
    public int ThreadsDone { get; set; }
    public int EventsTotal { get; set; }
    public int EventsDone { get; set; }
    public double ProgressPercent { get; set; }
    public double? EstimatedRemainingSec { get; set; }
    public string? CreatedAt { get; set; }
    public string? UpdatedAt { get; set; }
    public double? ElapsedWallSec { get; set; }
    public bool HasDownloadableArchive { get; set; }
}

public sealed class RunDetails
{
    public string JobId { get; set; } = "";
    public string RunDirectory { get; set; } = "";
    public JobRequestDocument? Request { get; set; }
    public JobStatusDocument? Status { get; set; }
    public JobResultDocument? Result { get; set; }
    public List<ManifestThreadItemDocument> ManifestItems { get; set; } = [];
    public List<TimelineItemDocument> TimelineItems { get; set; } = [];
    public string? ArchivePath { get; set; }
    public double? ElapsedWallSec { get; set; }
}

