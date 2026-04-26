using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForWindowsCodex.Web.Models;
using TimelineForWindowsCodex.Web.Services;

namespace TimelineForWindowsCodex.Web.Pages;

public sealed class IndexModel(RunStore runStore) : PageModel
{
    public CurrentArtifactDocument? CurrentArtifact { get; private set; }

    public RunDetails? CurrentRun { get; private set; }

    public RunSummary? ActiveRun { get; private set; }

    public IReadOnlyList<RefreshHistoryDocument> RefreshHistory { get; private set; } = [];

    public IReadOnlyList<RunSummary> RecentExports { get; private set; } = [];

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        var runs = await runStore.ListRunsAsync(cancellationToken);
        ActiveRun = runs.FirstOrDefault(static run =>
                       string.Equals(run.State, "running", StringComparison.OrdinalIgnoreCase))
                   ?? runs.FirstOrDefault(static run =>
                       string.Equals(run.State, "pending", StringComparison.OrdinalIgnoreCase));
        RecentExports = runs.Take(5).ToList();
        RefreshHistory = await runStore.GetRefreshHistoryAsync(5, cancellationToken);
        CurrentArtifact = await runStore.GetCurrentArtifactAsync(cancellationToken);

        if (!string.IsNullOrWhiteSpace(CurrentArtifact?.JobId))
        {
            CurrentRun = await runStore.GetRunDetailsAsync(CurrentArtifact.JobId, cancellationToken);
        }
    }
}
