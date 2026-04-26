using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForWindowsCodex.Web.Models;
using TimelineForWindowsCodex.Web.Services;

namespace TimelineForWindowsCodex.Web.Pages;

public sealed class EnvironmentModel(
    RunStore runStore,
    SettingsStore settingsStore) : PageModel
{
    public AppSettingsDocument Settings { get; private set; } = new();

    public CurrentArtifactDocument? CurrentArtifact { get; private set; }

    public RunDetails? CurrentRun { get; private set; }

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        Settings = await settingsStore.LoadAsync(cancellationToken);
        CurrentArtifact = await runStore.GetCurrentArtifactAsync(cancellationToken);

        if (!string.IsNullOrWhiteSpace(CurrentArtifact?.JobId))
        {
            CurrentRun = await runStore.GetRunDetailsAsync(CurrentArtifact.JobId, cancellationToken);
        }
    }
}
