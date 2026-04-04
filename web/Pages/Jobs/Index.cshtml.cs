using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using WindowsCodex2Timeline.Web.Models;
using WindowsCodex2Timeline.Web.Services;

namespace WindowsCodex2Timeline.Web.Pages.Jobs;

public sealed class IndexModel(
    RunStore runStore,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    public IReadOnlyList<RunSummary> RecentRuns { get; private set; } = [];

    public RunSummary? ActiveRun { get; private set; }

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
            return RedirectToPage(new { lang = CurrentLang() });
        }
        catch (InvalidOperationException ex)
        {
            ModelState.AddModelError(string.Empty, LocalizeMessage(ex.Message));
            return Page();
        }
    }

    private async Task LoadPageAsync(CancellationToken cancellationToken)
    {
        var runs = await runStore.ListRunsAsync(cancellationToken);
        ActiveRun = runs.FirstOrDefault(static run =>
                       string.Equals(run.State, "running", StringComparison.OrdinalIgnoreCase))
                   ?? runs.FirstOrDefault(static run =>
                       string.Equals(run.State, "pending", StringComparison.OrdinalIgnoreCase));
        RecentRuns = runs;
    }

    private string CurrentLang() => languageService.Resolve(Request);

    private string L(string key) => localizer.Get(CurrentLang(), key);

    private string LocalizeMessage(string message)
    {
        var localized = L(message);
        return localized == message ? message : localized;
    }
}
