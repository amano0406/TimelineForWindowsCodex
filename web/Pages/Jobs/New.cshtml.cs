using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.AspNetCore.WebUtilities;
using WindowsCodex2Timeline.Web.Infrastructure;
using WindowsCodex2Timeline.Web.Models;
using WindowsCodex2Timeline.Web.Services;

namespace WindowsCodex2Timeline.Web.Pages.Jobs;

public sealed class NewModel(
    RunStore runStore,
    SettingsStore settingsStore,
    CodexDiscoveryService discoveryService,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    [BindProperty]
    public string PrimaryCodexHomePath { get; set; } = string.Empty;

    [BindProperty]
    public string BackupCodexHomePathsText { get; set; } = string.Empty;

    [BindProperty]
    public bool IncludeArchivedSources { get; set; }

    [BindProperty]
    public bool IncludeToolOutputs { get; set; }

    [BindProperty]
    public string RedactionProfile { get; set; } = "strict";

    [BindProperty]
    public string? DateFrom { get; set; }

    [BindProperty]
    public string? DateTo { get; set; }

    [BindProperty]
    public List<string> SelectedThreadIds { get; set; } = [];

    [TempData]
    public string? StatusMessage { get; set; }

    public IReadOnlyList<DiscoveredThreadDocument> DiscoveredThreads { get; private set; } = [];

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        await LoadDefaultsAsync(cancellationToken);
        await LoadThreadsAsync(cancellationToken);
        if (DiscoveredThreads.Count == 1)
        {
            SelectedThreadIds = [DiscoveredThreads[0].ThreadId];
        }
    }

    public async Task<IActionResult> OnPostRefreshAsync(CancellationToken cancellationToken)
    {
        await LoadThreadsAsync(cancellationToken);
        return Page();
    }

    public async Task<IActionResult> OnPostExecuteAsync(CancellationToken cancellationToken)
    {
        await LoadThreadsAsync(cancellationToken);

        if (string.IsNullOrWhiteSpace(PrimaryCodexHomePath))
        {
            ModelState.AddModelError(string.Empty, L("error.primary_root_required"));
            return Page();
        }

        if (SelectedThreadIds.Count == 0)
        {
            ModelState.AddModelError(string.Empty, L("error.select_thread"));
            return Page();
        }

        if (!string.IsNullOrWhiteSpace(DateFrom) &&
            !string.IsNullOrWhiteSpace(DateTo) &&
            string.CompareOrdinal(DateFrom, DateTo) > 0)
        {
            ModelState.AddModelError(string.Empty, L("error.date_range_invalid"));
            return Page();
        }

        var created = await runStore.CreateJobAsync(
            new CreateJobCommand
            {
                PrimaryCodexHomePath = PrimaryCodexHomePath.Trim(),
                BackupCodexHomePaths = ParseLines(BackupCodexHomePathsText),
                IncludeArchivedSources = IncludeArchivedSources,
                IncludeToolOutputs = IncludeToolOutputs,
                RedactionProfile = string.Equals(RedactionProfile, "loose", StringComparison.OrdinalIgnoreCase)
                    ? "loose"
                    : "strict",
                DateFrom = NormalizeDate(DateFrom),
                DateTo = NormalizeDate(DateTo),
                SelectedThreadIds = SelectedThreadIds
                    .Where(static item => !string.IsNullOrWhiteSpace(item))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .ToList(),
            },
            cancellationToken);

        return Redirect(QueryHelpers.AddQueryString(JobUrls.Details(created.JobId), "lang", CurrentLang()));
    }

    private async Task LoadDefaultsAsync(CancellationToken cancellationToken)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        PrimaryCodexHomePath = settings.DefaultPrimaryCodexHomePath;
        BackupCodexHomePathsText = string.Join(Environment.NewLine, settings.DefaultBackupCodexHomePaths);
        IncludeArchivedSources = settings.DefaultIncludeArchivedSources;
        IncludeToolOutputs = settings.DefaultIncludeToolOutputs;
        RedactionProfile = settings.DefaultRedactionProfile;
    }

    private async Task LoadThreadsAsync(CancellationToken cancellationToken)
    {
        var primary = string.IsNullOrWhiteSpace(PrimaryCodexHomePath)
            ? "/input/codex-home"
            : PrimaryCodexHomePath.Trim();
        var backups = ParseLines(BackupCodexHomePathsText);
        DiscoveredThreads = await discoveryService.DiscoverAsync(primary, backups, cancellationToken);
    }

    private static string? NormalizeDate(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private string CurrentLang() => languageService.Resolve(Request);

    private string L(string key) => localizer.Get(CurrentLang(), key);

    private static List<string> ParseLines(string? raw) =>
        (raw ?? string.Empty)
        .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Where(static item => !string.IsNullOrWhiteSpace(item))
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .ToList();
}
