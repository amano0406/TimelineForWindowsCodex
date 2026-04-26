using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.AspNetCore.WebUtilities;
using TimelineForWindowsCodex.Web.Infrastructure;
using TimelineForWindowsCodex.Web.Models;
using TimelineForWindowsCodex.Web.Services;

namespace TimelineForWindowsCodex.Web.Pages.Jobs;

public sealed class IndexModel(
    RunStore runStore,
    SettingsStore settingsStore,
    CodexDiscoveryService discoveryService,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    public IReadOnlyList<RunSummary> RecentRuns { get; private set; } = [];

    public RunSummary? ActiveRun { get; private set; }

    public CurrentArtifactDocument? CurrentArtifact { get; private set; }

    public RunDetails? CurrentRun { get; private set; }

    public IReadOnlyList<RefreshHistoryDocument> RefreshHistory { get; private set; } = [];

    [TempData]
    public string? StatusMessage { get; set; }

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        await LoadPageAsync(cancellationToken);
    }

    public async Task<IActionResult> OnPostDeleteAsync(string jobId, CancellationToken cancellationToken)
    {
        await LoadPageAsync(cancellationToken);
        try
        {
            await runStore.DeleteRunAsync(jobId, cancellationToken);
            StatusMessage = L("status.run_deleted");
            return Redirect(QueryHelpers.AddQueryString("/exports", "lang", CurrentLang()));
        }
        catch (InvalidOperationException ex)
        {
            ModelState.AddModelError(string.Empty, LocalizeMessage(ex.Message));
            return Page();
        }
    }

    public async Task<IActionResult> OnPostRefreshCurrentAsync(CancellationToken cancellationToken)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var discovered = await discoveryService.DiscoverAsync(
            settings.DefaultPrimaryCodexHomePath,
            settings.DefaultBackupCodexHomePaths,
            settings.DefaultIncludeArchivedSources,
            cancellationToken);
        var selectedThreadIds = discovered
            .Select(static item => item.ThreadId)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (selectedThreadIds.Count == 0)
        {
            await LoadPageAsync(cancellationToken);
            ModelState.AddModelError(string.Empty, L("jobs.list.refresh_no_threads"));
            return Page();
        }

        var created = await runStore.CreateJobAsync(
            new CreateJobCommand
            {
                PrimaryCodexHomePath = settings.DefaultPrimaryCodexHomePath,
                BackupCodexHomePaths = settings.DefaultBackupCodexHomePaths,
                IncludeArchivedSources = settings.DefaultIncludeArchivedSources,
                IncludeToolOutputs = settings.DefaultIncludeToolOutputs,
                RedactionProfile = settings.DefaultRedactionProfile,
                SelectedThreadIds = selectedThreadIds,
            },
            cancellationToken);

        return Redirect(QueryHelpers.AddQueryString(JobUrls.Details(created.JobId), "lang", CurrentLang()));
    }

    private async Task LoadPageAsync(CancellationToken cancellationToken)
    {
        var runs = await runStore.ListRunsAsync(cancellationToken);
        ActiveRun = runs.FirstOrDefault(static run =>
                       string.Equals(run.State, "running", StringComparison.OrdinalIgnoreCase))
                   ?? runs.FirstOrDefault(static run =>
                       string.Equals(run.State, "pending", StringComparison.OrdinalIgnoreCase));
        RecentRuns = runs;
        CurrentArtifact = await runStore.GetCurrentArtifactAsync(cancellationToken);
        RefreshHistory = await runStore.GetRefreshHistoryAsync(5, cancellationToken);
        CurrentRun = string.IsNullOrWhiteSpace(CurrentArtifact?.JobId)
            ? null
            : await runStore.GetRunDetailsAsync(CurrentArtifact.JobId, cancellationToken);
    }

    private string CurrentLang() => languageService.Resolve(Request);

    private string L(string key) => localizer.Get(CurrentLang(), key);

    private string LocalizeMessage(string message)
    {
        var localized = L(message);
        return localized == message ? message : localized;
    }
}
