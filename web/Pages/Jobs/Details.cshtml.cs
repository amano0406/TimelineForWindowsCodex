using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForWindowsCodex.Web.Models;
using TimelineForWindowsCodex.Web.Services;

namespace TimelineForWindowsCodex.Web.Pages.Jobs;

public sealed class DetailsModel(RunStore runStore) : PageModel
{
    public RunDetails? Run { get; private set; }

    public bool ShouldAutoRefresh =>
        Run?.Status is not null &&
        (string.Equals(Run.Status.State, "pending", StringComparison.OrdinalIgnoreCase) ||
         string.Equals(Run.Status.State, "running", StringComparison.OrdinalIgnoreCase));

    public async Task<IActionResult> OnGetAsync(string id, CancellationToken cancellationToken)
    {
        Run = await runStore.GetRunDetailsAsync(id, cancellationToken);
        return Page();
    }
}
